from __future__ import annotations

import random
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.agents.pipeline import run_decision_pipeline
from app.agents.scenario_agent import generate_scenario, normalize_scenario
from app.core.llm_client import MODEL
from app.data import physics, recording
from app.data.benchmark_seeds import DEV_SEED_SET, HELD_OUT_SEED_SET
from app.data.recording import LiveRecorder, Recorder, RecordingRecorder, ReplayRecorder
from app.data.tuning import BENCHMARK_ALLOW_HELD_OUT, RULE_CATEGORY_MAP
from app.models.schemas import (
    BatchRunSummary,
    CategoryBreakdown,
    Difficulty,
    EnvironmentState,
    FieldRepair,
    ObjectiveBreakdown,
    Objective,
    ScenarioRunResult,
    UnresolvedRun,
)

router = APIRouter()

RunMode = Literal["live", "record", "replay"]


def _make_recorder(mode: RunMode, run_id: str | None, base_seed: int, seed_set_name: str | None) -> tuple[Recorder, str | None]:
    """Returns (recorder, run_id actually used — None for live)."""
    if mode == "live":
        return LiveRecorder(), None
    if mode == "replay":
        if not run_id:
            raise HTTPException(status_code=400, detail="replay mode requires run_id")
        return ReplayRecorder(run_id=run_id), run_id
    # record
    resolved_run_id = run_id or f"{seed_set_name or 'adhoc'}_{base_seed}_{int(time.time())}"
    return RecordingRecorder(run_id=resolved_run_id), resolved_run_id


def _run_or_503(scenario: EnvironmentState, recorder: Recorder | None = None) -> ScenarioRunResult:
    try:
        return run_decision_pipeline(scenario, recorder=recorder)
    except genai_errors.APIError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Gemini is unavailable after retries ({e.code} {e.status}) — this is usually temporary free-tier overload. Try again in a minute.",
        ) from e


class GenerateScenarioRequest(BaseModel):
    difficulty: Difficulty
    objective: Objective | None = None
    seed: int | None = None


@router.get("/scenario/presets")
def list_presets():
    return {
        "difficulties": [d.value for d in Difficulty],
        "objectives": [o.value for o in Objective],
    }


@router.post("/scenario/generate", response_model=EnvironmentState)
def scenario_generate(req: GenerateScenarioRequest):
    return generate_scenario(req.difficulty, req.objective, req.seed)


class NormalizeRequest(BaseModel):
    scenario: EnvironmentState


class NormalizeResponse(BaseModel):
    scenario: EnvironmentState
    corrections: list[str]
    facts: dict = {}


@router.post("/scenario/normalize", response_model=NormalizeResponse)
def scenario_normalize(req: NormalizeRequest):
    normalized, corrections = normalize_scenario(req.scenario)
    facts = physics.orchestrator_facts(normalized, normalized.previous_floor_pct)
    return NormalizeResponse(scenario=normalized, corrections=corrections, facts=facts)


@router.post("/run/single", response_model=ScenarioRunResult)
def run_single(req: GenerateScenarioRequest):
    scenario = generate_scenario(req.difficulty, req.objective, req.seed)
    return _run_or_503(scenario)


class FromScenarioRequest(BaseModel):
    scenario: EnvironmentState


@router.post("/run/from-scenario", response_model=ScenarioRunResult)
def run_from_scenario(req: FromScenarioRequest):
    """The manual-mode entry point. Normalizes the (possibly hand-edited) scenario server-side
    first, then runs it through the exact same pipeline auto and batch use."""
    normalized, _corrections = normalize_scenario(req.scenario)
    return _run_or_503(normalized)


def _categorize_rule(rule_id: str, repairs: list[FieldRepair]) -> str:
    if rule_id == "rule_3":
        over_allocation = any(
            r.field.startswith("market_amount_mw") or r.field.startswith("curtailment") or "amount_mw" in r.field
            for r in repairs
        )
        return "arithmetic" if over_allocation else "outcome"
    return RULE_CATEGORY_MAP.get(rule_id, "strategy")


def _summarize(results: list[ScenarioRunResult], base_seed: int, seed_set_name: str | None, objectives: list) -> BatchRunSummary:
    # Patch 3, Step 1: N/A is a per-rule result, never a scenario exclusion. Every scenario is
    # in the denominator except an infeasible one (full service was physically impossible no
    # matter the decision). The old na_count-based denominator shrinkage silently dropped a
    # genuine rule_3 FAIL from applied_failed because that scenario's unrelated rule_9
    # happened to be N/A — this replaces that logic entirely rather than patching it further.
    #
    # Patch 3, Step 4 honesty requirement: the headline first_attempt/applied rates count
    # ONLY mode="agent" rows. A safe_mode (or the now-rare model_call_failed/parse_failed)
    # row never inflates OR deflates the agent's own score — it's reported separately below.
    total = len(results)
    infeasible_count = sum(1 for r in results if r.infeasible)
    judged_count = total - infeasible_count
    margin_infeasible_count = sum(1 for r in results if r.margin_infeasible)

    raw_stages = [next(s for s in r.stages if s.name == "raw") for r in results]
    applied_stages = [next(s for s in r.stages if s.name == "applied") for r in results]
    agent_mask = [(not r.infeasible) and a.decision.mode == "agent" for r, a in zip(results, applied_stages)]
    safe_mode_mask = [(not r.infeasible) and a.decision.mode == "safe_mode" for r, a in zip(results, applied_stages)]

    first_attempt_passed = sum(1 for s, j in zip(raw_stages, agent_mask) if j and s.evaluation.status.value == "pass")
    applied_passed = sum(1 for s, j in zip(applied_stages, agent_mask) if j and s.evaluation.status.value == "pass")
    applied_failed = sum(1 for s, j in zip(applied_stages, agent_mask) if j and s.evaluation.status.value == "fail")
    applied_flagged = sum(1 for s, j in zip(applied_stages, agent_mask) if j and s.evaluation.status.value == "flagged")
    agent_judged_count = sum(agent_mask)
    repaired_count = sum(1 for r in results if r.repaired)

    safe_mode_count = sum(safe_mode_mask)
    safe_mode_passed = sum(1 for s, j in zip(applied_stages, safe_mode_mask) if j and s.evaluation.status.value == "pass")
    safe_mode_pass_rate_pct = round((safe_mode_passed / safe_mode_count) * 100, 1) if safe_mode_count else 0.0

    na_counts_by_rule: dict[str, int] = {}
    for stage in applied_stages:
        for rule in stage.evaluation.rules:
            if not rule.applicable:
                na_counts_by_rule[rule.rule_id] = na_counts_by_rule.get(rule.rule_id, 0) + 1

    unresolved: list[UnresolvedRun] = []
    for r, applied_stage in zip(results, applied_stages):
        mode = applied_stage.decision.mode
        if mode in ("model_call_failed", "parse_failed"):  # safe_mode is a resolution, not a failure to report here
            unresolved.append(UnresolvedRun(
                tick=r.scenario.tick, seed=r.scenario.seed,
                profile=r.scenario.difficulty.value, objective=(r.scenario.objective.value if r.scenario.objective else "none"),
                mode=mode, detail=applied_stage.decision.failure_detail or "",
            ))

    category_counts: dict[str, int] = {"arithmetic": 0, "strategy": 0, "outcome": 0}
    for r, raw_stage in zip(results, raw_stages):
        for rule in raw_stage.evaluation.rules:
            if not rule.passed and rule.applicable:
                category = _categorize_rule(rule.rule_id, r.repairs)
                category_counts[category] = category_counts.get(category, 0) + 1

    by_objective: list[ObjectiveBreakdown] = []
    for objective in objectives:
        key = objective.value if objective else "none"
        rows = [(r, a) for r, a in zip(results, applied_stages) if (r.scenario.objective.value if r.scenario.objective else "none") == key]
        by_objective.append(ObjectiveBreakdown(
            objective=key,
            total=len(rows),
            passed=sum(1 for _, a in rows if a.evaluation.status.value == "pass"),
            flagged=sum(1 for _, a in rows if a.evaluation.status.value == "flagged"),
            failed=sum(1 for _, a in rows if a.evaluation.status.value == "fail"),
        ))

    return BatchRunSummary(
        seed=base_seed,
        seed_set=seed_set_name,
        total=total,
        infeasible_count=infeasible_count,
        judged_count=agent_judged_count,
        margin_infeasible_count=margin_infeasible_count,
        na_counts_by_rule=na_counts_by_rule,
        unresolved_count=len(unresolved),
        unresolved=unresolved,
        safe_mode_count=safe_mode_count,
        safe_mode_passed=safe_mode_passed,
        safe_mode_pass_rate_pct=safe_mode_pass_rate_pct,
        first_attempt_passed=first_attempt_passed,
        first_attempt_pass_rate_pct=round((first_attempt_passed / agent_judged_count) * 100, 1) if agent_judged_count else 0.0,
        applied_passed=applied_passed,
        applied_failed=applied_failed,
        applied_flagged=applied_flagged,
        applied_pass_rate_pct=round((applied_passed / agent_judged_count) * 100, 1) if agent_judged_count else 0.0,
        repaired_count=repaired_count,
        repair_rate_pct=round((repaired_count / total) * 100, 1) if total else 0.0,
        raw_category_breakdown=[CategoryBreakdown(category=c, failed_or_flagged=n) for c, n in category_counts.items()],
        by_objective=by_objective,
        results=results,
    )


def _run_matrix(
    base_seed: int, n_per_cell: int, objectives: list, seed_set_name: str | None = None,
    mode: RunMode = "record", run_id: str | None = None,
) -> BatchRunSummary:
    recorder, resolved_run_id = _make_recorder(mode, run_id, base_seed, seed_set_name)
    results: list[ScenarioRunResult] = []
    for d_idx, difficulty in enumerate(Difficulty):
        for o_idx, objective in enumerate(objectives):
            for rep in range(n_per_cell):
                cell_seed = base_seed + d_idx * 10_000 + o_idx * 100 + rep
                scenario = generate_scenario(difficulty, objective, seed=cell_seed)
                results.append(_run_or_503(scenario, recorder=recorder))
    summary = _summarize(results, base_seed, seed_set_name, objectives)
    if mode == "record" and resolved_run_id:
        recording.write_run_meta(
            resolved_run_id, model=MODEL, seed=base_seed, seed_set=seed_set_name,
            created_at=time.time(), scenario_count=len(results),
        )
        recording.write_manifest(resolved_run_id)
    return summary


class BatchRunRequest(BaseModel):
    n_per_cell: int = 1
    seed: int | None = None
    full_matrix: bool = True
    objectives: list[Objective] | None = None
    strip_objective: bool = False
    mode: RunMode = "record"
    run_id: str | None = None


@router.post("/run/batch", response_model=BatchRunSummary)
def run_batch(req: BatchRunRequest):
    base_seed = req.seed if req.seed is not None else random.SystemRandom().randint(0, 2**31 - 1)

    if req.strip_objective:
        objectives: list = [None]
    elif req.full_matrix:
        objectives = list(Objective)
    elif req.objectives:
        objectives = list(req.objectives)
    else:
        objectives = list(Objective)

    return _run_matrix(base_seed, req.n_per_cell, objectives, mode=req.mode, run_id=req.run_id)


@router.get("/recordings")
def list_recordings():
    return recording.list_runs()


@router.post("/recordings/{run_id}/verify")
def verify_recording(run_id: str):
    ok, problems = recording.verify(run_id)
    return {"run_id": run_id, "ok": ok, "problems": problems}


class BenchmarkEstimateResponse(BaseModel):
    scenario_count: int
    estimated_calls: float


@router.get("/benchmark/estimate", response_model=BenchmarkEstimateResponse)
def benchmark_estimate():
    count = len(Difficulty) * len(Objective)  # n_per_cell=1 for the standard benchmark
    return BenchmarkEstimateResponse(scenario_count=count, estimated_calls=round(count * 1.2, 1))


class BenchmarkRunRequest(BaseModel):
    use_held_out: bool = False
    mode: RunMode = "record"
    run_id: str | None = None


@router.post("/benchmark/run", response_model=BatchRunSummary)
def benchmark_run(req: BenchmarkRunRequest):
    if req.use_held_out:
        if not BENCHMARK_ALLOW_HELD_OUT:
            raise HTTPException(status_code=403, detail="The held-out set is gated by BENCHMARK_ALLOW_HELD_OUT in tuning.py — flip it on only when actually reporting results, not while tuning.")
        seed_set = HELD_OUT_SEED_SET
    else:
        seed_set = DEV_SEED_SET
    return _run_matrix(seed_set["base_seed"], 1, list(Objective), seed_set_name=seed_set["name"], mode=req.mode, run_id=req.run_id)
