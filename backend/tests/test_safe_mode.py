"""Patch 3, Step 4: safe mode. The dispatcher produces a complete decision when the
Orchestrator can't, the Evaluator judges it like any other decision, and every report splits
agent decisions from safe-mode ones so safe mode never inflates (or deflates) the agent's
own score. No network calls -- the Gemini client is stubbed throughout.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from app.agents import orchestrator_agent, pipeline
from app.data import recording
from app.data.recording import BoundedLiveRecorder, SafeModeRecorder
from app.data.tuning import SAFE_MODE_RETRY_ATTEMPTS
from app.models.schemas import Objective
from tests.test_acceptance import _tick88_scenario


def _client_error(code: int):
    return genai_errors.ClientError(code, {"error": {"message": "x", "status": "UNAVAILABLE"}})


def test_01_falls_back_to_dispatcher_on_infrastructure_failure():
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        result = pipeline.run_decision_pipeline(scenario, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "safe_mode"
    assert "SAFE MODE" in applied.decision.reasoning
    assert "infrastructure" in applied.decision.failure_detail


def test_02_evaluator_judges_safe_mode_decision_normally_not_forced_fail():
    # A balanced, easy scenario -- the dispatcher's own decision should genuinely PASS, not
    # be force-failed the way model_call_failed/parse_failed placeholders are.
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(503)
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY, wind_output_mw=99.0, wind_forecast_mw=99.0)  # generation == demand
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        result = pipeline.run_decision_pipeline(scenario, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "safe_mode"
    assert applied.evaluation.status.value == "pass"  # judged on its merits, not forced to fail


def test_03_no_inner_goes_straight_to_dispatcher_no_client_touched():
    scenario = _tick88_scenario(objective=Objective.MIN_CARBON)
    with patch.object(orchestrator_agent, "get_client") as get_client_mock:
        result = pipeline.run_decision_pipeline(scenario, recorder=SafeModeRecorder(inner=None))
        get_client_mock.assert_not_called()
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "safe_mode"
    assert "Safe mode selected" in applied.decision.failure_detail


def test_04_no_api_key_configured_falls_back_cleanly():
    # get_client() raising RuntimeError (no key) must be caught as CallFailure, not escape
    # as a raw exception -- this is what makes "no key -> safe mode" actually work.
    with patch("app.core.llm_client.GEMINI_API_KEY", ""):
        scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
        result = pipeline.run_decision_pipeline(scenario, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "safe_mode"
    assert "GEMINI_API_KEY" in applied.decision.failure_detail


def test_05_simulate_outage_fails_immediately_no_retries():
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)  # would never be reached
    orchestrator_agent.set_simulate_outage(True)
    try:
        scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
        with patch.object(orchestrator_agent, "get_client", return_value=client):
            result = pipeline.run_decision_pipeline(scenario, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))
        assert client.models.generate_content.call_count == 0  # never even attempted
        applied = next(s for s in result.stages if s.name == "applied")
        assert applied.decision.mode == "safe_mode"
        assert "simulated" in applied.decision.failure_detail.lower()
    finally:
        orchestrator_agent.set_simulate_outage(False)


def test_06_bounded_retry_uses_the_tight_policy_not_the_normal_one():
    client = MagicMock()
    client.models.generate_content.side_effect = _client_error(429)
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
    with patch.object(orchestrator_agent, "get_client", return_value=client), patch("time.sleep", return_value=None):
        try:
            orchestrator_agent.decide(scenario, bounded=True)
            assert False, "expected CallFailure"
        except orchestrator_agent.CallFailure:
            pass
    assert client.models.generate_content.call_count == SAFE_MODE_RETRY_ATTEMPTS  # not GEMINI_RETRY_ATTEMPTS (5)


def test_07_batch_summary_splits_agent_from_safe_mode():
    # One real agent pass, one safe-mode fallback -- the agent's rate must reflect ONLY the
    # first, with the second reported separately and not mixed in either direction.
    good_call = MagicMock()
    good_call.args = {
        "reasoning": "ok", "reserve_floor_pct": 25.0, "floor_justification": "calm",
        "battery_actions": [], "market_action": "hold", "market_amount_mw": 0.0,
        "curtail_solar_mw": 0.0, "curtail_wind_mw": 0.0, "demand_response_triggered": False,
    }
    good_response = MagicMock()
    good_response.function_calls = [good_call]

    client_ok = MagicMock()
    client_ok.models.generate_content.return_value = good_response
    scenario_ok = _tick88_scenario(objective=Objective.COST_EFFICIENCY, wind_output_mw=99.0, wind_forecast_mw=99.0)
    with patch.object(orchestrator_agent, "get_client", return_value=client_ok):
        agent_result = pipeline.run_decision_pipeline(scenario_ok, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))

    client_fail = MagicMock()
    client_fail.models.generate_content.side_effect = _client_error(429)
    scenario_fail = _tick88_scenario(objective=Objective.MIN_CARBON, wind_output_mw=99.0, wind_forecast_mw=99.0)
    with patch.object(orchestrator_agent, "get_client", return_value=client_fail), patch("time.sleep", return_value=None):
        safe_result = pipeline.run_decision_pipeline(scenario_fail, recorder=SafeModeRecorder(inner=BoundedLiveRecorder()))

    from app.api.routes import _summarize
    summary = _summarize([agent_result, safe_result], base_seed=1, seed_set_name=None, objectives=[Objective.COST_EFFICIENCY, Objective.MIN_CARBON])
    assert summary.total == 2
    assert summary.judged_count == 1  # only the agent row
    assert summary.applied_passed == 1
    assert summary.applied_pass_rate_pct == 100.0  # agent's own rate, undiluted by the safe-mode row
    assert summary.safe_mode_count == 1
    assert summary.safe_mode_passed == 1  # the dispatcher's decision also happens to pass here
    assert summary.safe_mode_pass_rate_pct == 100.0  # its own, separate rate
