"""Orchestrator Agent (Decision-Maker).

Receives an EnvironmentState + declared objective each tick, judges every decision in two
layers — Layer 1 golden rules (never traded away) and Layer 2 the objective cascade (which
only reorders priorities once Layer 1 holds) — and returns a structured Decision via a
forced tool call. No objective declared means cost_efficiency under the golden rules; this
is a structural default, not a special-cased fallback.
"""
from __future__ import annotations

import hashlib
import json

from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.llm_client import MODEL, get_client
from app.data import physics
from app.data.tuning import (
    FLOOR_MAX,
    FLOOR_MIN,
    FLOOR_STEP_DOWN,
    GEMINI_RETRY_ATTEMPTS,
    GEMINI_RETRY_MAX_WAIT_S,
    GEMINI_TEMPERATURE,
    REASONING_CHAR_CAP,
)
from app.models.schemas import BatteryAction, Decision, EnvironmentState


class CallFailure(Exception):
    """Raised when decide() cannot produce a real Decision — never a rule violation, always
    an infrastructure or parsing problem (Patch 3, Step 1). Caught by the pipeline, which
    turns it into a FAIL-evaluated placeholder decision rather than crashing the whole batch
    or silently dropping the scenario from any count."""

    def __init__(self, kind: str, detail: str):
        self.kind = kind  # "infrastructure" or "parse"
        self.detail = detail
        super().__init__(f"{kind}: {detail}")

SYSTEM_PROMPT = """You are the Orchestrator Agent for a Renewable Energy Orchestrator. Every 15 minutes \
you receive the current grid/market state and must decide battery, market, curtailment, demand-response, \
and reserve-floor actions for this tick.

Every decision is judged in two layers. Layer 1 (golden rules) is never traded away for cost, carbon, \
profit, or anything else. Layer 2 (the objective cascade) only reorders priorities once Layer 1 holds.

LAYER 1 — GOLDEN RULES (always on):
1. Reliability: critical load is always served — from generation, battery, or purchase — with a reserve \
margin above raw demand. This outranks everything else. total_demand_mw is the ONLY demand figure to use \
for this — it is already base_demand_mw + industrial_demand_mw added together; never re-derive or \
re-sum it from the components yourself, and never reason from base_demand_mw alone.
2. Grid stability: transmission_headroom_mw is the remaining capacity for NET flow across the grid \
interconnection this tick (selling minus buying, in either direction) — keep |sale - purchase| within it, \
and keep grid frequency inside its allowed band. transmission_constraint_mw is the line's fixed rating, \
not this tick's available headroom — always check against transmission_headroom_mw.
3. Minimal curtailment: curtail solar/wind only as the very last step, never while also buying from the \
grid. (A stability-forced exception exists only when the transmission line is genuinely at capacity.)
4. Battery protection: respect each battery's charge/discharge rate limits and its reserve floor (below) \
— except in a genuine reliability emergency, where discharging below the floor to keep critical load \
served is the right call, not a mistake.

LAYER 2 — OBJECTIVE CASCADE (reorders priorities, subject to Layer 1 always holding):
- cost_efficiency (the default when no objective is declared): cost, then carbon, then renewable utilisation.
- min_carbon: carbon, then cost, then renewable utilisation.
- max_renewable_utilisation: renewable utilisation, then cost, then carbon.
- max_profit: profit, then cost, then carbon (carbon drops to last). Profit is sale revenue minus purchase \
cost for this tick: a purchase costs buy_price_per_mwh (above electricity_price_per_mwh), a sale earns \
sell_price_per_mwh (below it) — never use electricity_price_per_mwh directly for either side.
Within the cascade: find the best option on the top priority, treat every option within a small tolerance \
of it as tied, then choose the best of those tied options on the next priority. Do not let a lower \
priority override a clearly better option on a higher one.

DISPATCH LADDERS:
- Shortfall (demand > generation): renewables, then battery discharge above its floor, then grid purchase, \
then demand response, then — only as a last-resort emergency — discharging below the reserve floor.
- Surplus (generation > demand): serve load, then charge the battery, then sell to the grid, then curtail \
(curtailment is always the last step).
A correct decision never curtails and buys in the same tick, and never ends the surplus ladder (curtail) \
while also using the shortfall ladder (buy).

RESERVE FLOOR: each tick, propose a reserve_floor_pct — the slice of battery state of charge reserved for \
a genuine reliability emergency only. Guidance bands:
- Stable day, calm forecast: 20-30%
- Some volatility (price spike or forecast change): 30-45%
- Heavy volatility (storm alert, price spike, and asset outage together): 45-60%
Raise the floor ahead of a forecast event (storm, price spike), not in reaction to it — the battery should \
already be charged to the new floor before the event arrives. A high floor has a real cost: it reduces \
usable capacity and can increase curtailment and purchases, so raising it on a calm day with no volatility \
signal is a mistake. Always give a one-line floor_justification naming the specific signals that drove \
your number (price volatility, forecast change, storm alert, asset outage, forecast confidence).

The environment state is followed by a separate "Physics facts" block — total_generation_mw, \
net_position_mw (positive = surplus, negative = shortfall), a position label, the same for the forecast, and \
each battery's discharge_available_mw / charge_headroom_mw. These are computed for you; do not recompute them \
yourself, and do not let them disagree with your own arithmetic — use them directly.

In the reasoning field (written FIRST, before you decide any action): state the position (surplus/shortfall/ \
balanced) from the physics facts, the dispatch-ladder step you are following because of it, which golden \
rules were binding, and which cascade layer and priority drove the choice. Keep it under {reasoning_cap} \
characters.

Always call submit_decision with your chosen actions.""".format(reasoning_cap=REASONING_CHAR_CAP)

SUBMIT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "maxLength": REASONING_CHAR_CAP,
            "description": "Written FIRST: the position (surplus/shortfall/balanced), the ladder step, which golden rules were binding, and the cascade priority — before any action below.",
        },
        "reserve_floor_pct": {"type": "number", "description": "Proposed reserve floor, before clamping/ramping."},
        "floor_justification": {"type": "string"},
        "battery_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "battery_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["charge", "discharge", "reserve", "hold"]},
                    "amount_mw": {"type": "number"},
                },
                "required": ["battery_id", "action", "amount_mw"],
            },
        },
        "market_action": {"type": "string", "enum": ["buy", "sell", "hold", "delay_sell"]},
        "market_amount_mw": {"type": "number"},
        "curtail_solar_mw": {"type": "number"},
        "curtail_wind_mw": {"type": "number"},
        "demand_response_triggered": {"type": "boolean"},
    },
    "required": [
        "reasoning",
        "reserve_floor_pct",
        "floor_justification",
        "battery_actions",
        "market_action",
        "market_amount_mw",
        "curtail_solar_mw",
        "curtail_wind_mw",
        "demand_response_triggered",
    ],
}

_SUBMIT_DECISION_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="submit_decision",
            description="Submit the orchestration decision for this tick.",
            parameters_json_schema=SUBMIT_DECISION_SCHEMA,
        )
    ]
)

_HIDDEN_FIELDS = {
    "expected_behavior",
    "expected_floor_min_pct",
    "expected_floor_max_pct",
    "expected_ladder_step",
    "expected_emergency",
}


def _is_transient(exc: BaseException) -> bool:
    # Gemini's free tier returns 503 ("model overloaded") or 429 (rate limit) fairly often
    # under load — both are worth retrying. The google-genai SDK raises ClientError for 429
    # and ServerError for 503 (both subclass APIError) — matching on APIError + code catches
    # both; matching ServerError alone (the original bug) let every 429 crash immediately
    # with zero retries, discovered while diagnosing a Patch 2 Step 5 run failure. Network-
    # level failures (timeout, connection drop) are not APIErrors at all and are also
    # transient — anything else (bad request, auth) is not.
    if isinstance(exc, genai_errors.APIError) and getattr(exc, "code", None) in (503, 429):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


@retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(GEMINI_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=GEMINI_RETRY_MAX_WAIT_S),
    reraise=True,
)
def _call_gemini(client, **kwargs):
    return client.models.generate_content(**kwargs)


def _apply_floor_clamp_and_ramp(proposed_floor_pct: float, previous_floor_pct: float) -> float:
    clamped = min(max(proposed_floor_pct, FLOOR_MIN), FLOOR_MAX)
    floor_after_ramp = max(clamped, previous_floor_pct - FLOOR_STEP_DOWN)
    return min(max(floor_after_ramp, FLOOR_MIN), FLOOR_MAX)


# ---- Patch 3, Step 2: request/response boundary, factored out so a Recorder can intercept
# it cleanly — record/replay touch only this boundary, never physics/balancer/Evaluator. ----


def prompt_version() -> str:
    """Changes automatically whenever SYSTEM_PROMPT or the schema text changes — a stale
    recording from a different prompt version should never silently look reusable."""
    h = hashlib.sha256()
    h.update(SYSTEM_PROMPT.encode())
    h.update(json.dumps(SUBMIT_DECISION_SCHEMA, sort_keys=True).encode())
    return h.hexdigest()[:16]


def scenario_hash(scenario: EnvironmentState) -> str:
    """Hash of exactly what gets sent to the model (objective + the non-hidden scenario
    fields + the derived physics facts), excluding `tick` — tick is a process-global counter
    that never affects content (see test_13), so two calls with identical content but
    different tick numbers must hash identically."""
    objective = scenario.objective.value if scenario.objective else None
    user_payload = scenario.model_dump(mode="json", exclude=_HIDDEN_FIELDS | {"tick"})
    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    payload = json.dumps({"objective": objective, "scenario": user_payload, "facts": facts}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_request(scenario: EnvironmentState) -> dict:
    """Everything needed to make (or record, or replay) one call — JSON-serializable, so it
    can be written straight into a recording."""
    objective = scenario.objective.value if scenario.objective else None
    user_payload = scenario.model_dump(mode="json", exclude=_HIDDEN_FIELDS)
    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    contents = (
        f"Declared objective for this tick: {objective or 'NONE — cost_efficiency applies under the golden rules'}\n\n"
        f"Environment state:\n{json.dumps(user_payload, indent=2)}\n\n"
        f"Physics facts (computed — use directly, do not recompute):\n{json.dumps(facts, indent=2)}"
    )
    return {
        "model": MODEL,
        "temperature": GEMINI_TEMPERATURE,
        "prompt_version": prompt_version(),
        "scenario_hash": scenario_hash(scenario),
        "contents": contents,
        "system_instruction": SYSTEM_PROMPT,
    }


def _call_gemini_live(request: dict):
    client = get_client()
    try:
        return _call_gemini(
            client,
            model=request["model"],
            contents=request["contents"],
            config=types.GenerateContentConfig(
                system_instruction=request["system_instruction"],
                temperature=request["temperature"],
                tools=[_SUBMIT_DECISION_TOOL],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=["submit_decision"],
                    )
                ),
            ),
        )
    except genai_errors.APIError as e:
        raise CallFailure("infrastructure", f"{getattr(e, 'code', '?')} {getattr(e, 'status', '')}: {e}") from e
    except (TimeoutError, ConnectionError) as e:
        raise CallFailure("infrastructure", f"{type(e).__name__}: {e}") from e


def args_from_response(response) -> dict:
    """Raises CallFailure('parse', ...) for anything that isn't a usable tool call. Used by
    both the live path and, for a non-live source (a replayed recording), the same parsing —
    a recorded response is re-validated exactly like a fresh one."""
    if not getattr(response, "function_calls", None):
        raise CallFailure("parse", "no function call in the response")
    return dict(response.function_calls[0].args)


def decision_from_args(scenario: EnvironmentState, args: dict) -> Decision:
    objective = scenario.objective.value if scenario.objective else None
    try:
        proposed_floor = float(args["reserve_floor_pct"])
        applied_floor = _apply_floor_clamp_and_ramp(proposed_floor, scenario.previous_floor_pct)
        return Decision(
            tick=scenario.tick,
            objective_used=objective or "cost_efficiency",
            battery_actions=[BatteryAction(**a) for a in args["battery_actions"]],
            market_action=args["market_action"],
            market_amount_mw=args["market_amount_mw"],
            curtail_solar_mw=args["curtail_solar_mw"],
            curtail_wind_mw=args["curtail_wind_mw"],
            demand_response_triggered=args["demand_response_triggered"],
            proposed_floor_pct=proposed_floor,
            applied_floor_pct=applied_floor,
            floor_justification=args["floor_justification"],
            reasoning=args["reasoning"],
            mode="agent",
        )
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as e:
        raise CallFailure("parse", f"{type(e).__name__}: {e}") from e


def decide(scenario: EnvironmentState) -> Decision:
    request = build_request(scenario)
    response = _call_gemini_live(request)
    args = args_from_response(response)
    return decision_from_args(scenario, args)
