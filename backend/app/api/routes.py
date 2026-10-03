from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.agents.pipeline import run_decision_pipeline
from app.agents.scenario_agent import generate_scenario, normalize_scenario
from app.models.schemas import (
    BatchRunSummary,
    Difficulty,
    EnvironmentState,
    ObjectiveBreakdown,
    Objective,
    ScenarioRunResult,
)

router = APIRouter()


def _run_or_503(scenario: EnvironmentState) -> ScenarioRunResult:
    try:
        return run_decision_pipeline(scenario)
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


@router.post("/scenario/normalize", response_model=NormalizeResponse)
def scenario_normalize(req: NormalizeRequest):
    normalized, corrections = normalize_scenario(req.scenario)
    return NormalizeResponse(scenario=normalized, corrections=corrections)


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


class BatchRunRequest(BaseModel):
    n_per_cell: int = 1
    seed: int | None = None
    full_matrix: bool = True
    objectives: list[Objective] | None = None
    strip_objective: bool = False


@router.post("/run/batch", response_model=BatchRunSummary)
def run_batch(req: BatchRunRequest):
    base_seed = req.seed if req.seed is not None else random.SystemRandom().randint(0, 2**31 - 1)

    if req.strip_objective:
        objectives: list[Objective | None] = [None]
    elif req.full_matrix:
        objectives = list(Objective)
    elif req.objectives:
        objectives = list(req.objectives)
    else:
        objectives = list(Objective)

    results: list[ScenarioRunResult] = []
    for d_idx, difficulty in enumerate(Difficulty):
        for o_idx, objective in enumerate(objectives):
            for rep in range(req.n_per_cell):
                cell_seed = base_seed + d_idx * 10_000 + o_idx * 100 + rep
                scenario = generate_scenario(difficulty, objective, seed=cell_seed)
                results.append(_run_or_503(scenario))

    total = len(results)
    passed = sum(1 for r in results if r.evaluation.status.value == "pass")
    failed = sum(1 for r in results if r.evaluation.status.value == "fail")
    flagged = sum(1 for r in results if r.evaluation.status.value == "flagged")
    repaired_count = sum(1 for r in results if r.repaired)

    by_objective: list[ObjectiveBreakdown] = []
    for objective in objectives:
        key = objective.value if objective else "none"
        rows = [r for r in results if (r.scenario.objective.value if r.scenario.objective else "none") == key]
        by_objective.append(
            ObjectiveBreakdown(
                objective=key,
                total=len(rows),
                passed=sum(1 for r in rows if r.evaluation.status.value == "pass"),
                flagged=sum(1 for r in rows if r.evaluation.status.value == "flagged"),
                failed=sum(1 for r in rows if r.evaluation.status.value == "fail"),
            )
        )

    return BatchRunSummary(
        seed=base_seed,
        total=total,
        passed=passed,
        failed=failed,
        flagged=flagged,
        pass_rate_pct=round((passed / total) * 100, 1) if total else 0.0,
        repaired_count=repaired_count,
        repair_rate_pct=round((repaired_count / total) * 100, 1) if total else 0.0,
        by_objective=by_objective,
        results=results,
    )
