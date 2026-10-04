"""Patch 3, Step 1: infrastructure failures are retried (with the 429-ClientError bug fixed)
and, once the retry cap is exhausted, reported as an unresolved FAIL rather than crashing
the batch; parse/schema failures are likewise turned into a FAIL, never a crash. No network
calls -- the Gemini client is stubbed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from app.agents import orchestrator_agent, pipeline
from app.agents.orchestrator_agent import CallFailure, decide
from app.models.schemas import Objective
from tests.test_acceptance import _tick88_scenario


def _client_error(code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}})


def _server_error(code: int) -> genai_errors.ServerError:
    return genai_errors.ServerError(code, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})


def _good_response():
    call = MagicMock()
    call.args = {
        "reasoning": "Position balanced. No action needed.",
        "reserve_floor_pct": 25.0,
        "floor_justification": "calm",
        "battery_actions": [],
        "market_action": "hold",
        "market_amount_mw": 0.0,
        "curtail_solar_mw": 0.0,
        "curtail_wind_mw": 0.0,
        "demand_response_triggered": False,
    }
    response = MagicMock()
    response.function_calls = [call]
    return response


def test_01_429_client_error_is_now_retried_not_fatal():
    # The original bug: _is_transient only matched ServerError, so a 429 ClientError (what
    # the SDK actually raises for rate limits) was never retried and crashed immediately.
    client = MagicMock()
    client.models.generate_content.side_effect = [_client_error(429), _good_response()]
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        decision = decide(scenario)
    assert decision.mode == "agent"
    assert client.models.generate_content.call_count == 2  # one failure, one retried success


def test_02_503_server_error_still_retried():
    client = MagicMock()
    client.models.generate_content.side_effect = [_server_error(503), _good_response()]
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        decision = decide(scenario)
    assert decision.mode == "agent"


def test_03_persistent_infrastructure_failure_raises_call_failure_not_crash():
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)  # every call fails
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        try:
            decide(scenario)
            assert False, "expected CallFailure"
        except CallFailure as e:
            assert e.kind == "infrastructure"


def test_04_pipeline_turns_infrastructure_failure_into_fail_result_not_crash():
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        result = pipeline.run_decision_pipeline(scenario)
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "model_call_failed"
    assert applied.evaluation.status.value == "fail"
    raw = next(s for s in result.stages if s.name == "raw")
    assert raw.evaluation.status.value == "fail"


def test_05_parse_failure_no_function_call_in_response():
    client = MagicMock()
    empty_response = MagicMock()
    empty_response.function_calls = []
    client.models.generate_content.return_value = empty_response
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client):
        try:
            decide(scenario)
            assert False, "expected CallFailure"
        except CallFailure as e:
            assert e.kind == "parse"


def test_06_parse_failure_missing_required_key():
    client = MagicMock()
    call = MagicMock()
    call.args = {"reasoning": "x", "reserve_floor_pct": 25.0}  # missing battery_actions etc.
    response = MagicMock()
    response.function_calls = [call]
    client.models.generate_content.return_value = response
    scenario = _tick88_scenario()
    with patch.object(orchestrator_agent, "get_client", return_value=client):
        try:
            decide(scenario)
            assert False, "expected CallFailure"
        except CallFailure as e:
            assert e.kind == "parse"


def test_07_unresolved_scenarios_reported_separately_not_counted_against_the_agent():
    # Patch 3, Step 4 honesty requirement: an unresolved row (here, no SafeModeRecorder is
    # used, so the CallFailure reaches pipeline.py's own fallback) is excluded from the
    # agent's judged_count entirely -- never silently counted as an agent FAIL -- and
    # reported via unresolved_count/unresolved instead.
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)
    scenario = _tick88_scenario(objective=Objective.MAX_PROFIT)
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        result = pipeline.run_decision_pipeline(scenario)

    from app.api.routes import _summarize
    summary = _summarize([result], base_seed=1, seed_set_name=None, objectives=[Objective.MAX_PROFIT])
    assert summary.total == 1
    assert summary.judged_count == 0  # mode != "agent" -> excluded from the agent's own denominator
    assert summary.applied_failed == 0  # not counted as an agent fail either
    assert summary.unresolved_count == 1
    assert summary.unresolved[0].mode == "model_call_failed"
    assert summary.applied_pass_rate_pct == 0.0  # 0/0 guard, not a real rate
    assert summary.applied_pass_rate_pct == 0.0
