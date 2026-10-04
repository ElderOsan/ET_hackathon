"""Patch 3, Step 2: record every model call and replay with no key, no network, identical
verdicts. Resume (cache hit), scrub, and tamper-detection are tested directly against a
scratch recordings directory -- never the real one.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.agents import orchestrator_agent, pipeline
from app.data import recording
from app.models.schemas import Objective
from tests.test_acceptance import _tick88_scenario


def _good_response(reasoning="Position balanced. No action needed."):
    call = MagicMock()
    call.args = {
        "reasoning": reasoning,
        "reserve_floor_pct": 25.0,
        "floor_justification": "calm",
        "battery_actions": [{"battery_id": "battery_1", "action": "hold", "amount_mw": 0.0}, {"battery_id": "battery_2", "action": "hold", "amount_mw": 0.0}],
        "market_action": "hold",
        "market_amount_mw": 0.0,
        "curtail_solar_mw": 0.0,
        "curtail_wind_mw": 0.0,
        "demand_response_triggered": False,
    }
    response = MagicMock()
    response.function_calls = [call]
    return response


def test_01_record_then_replay_reproduces_identical_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
    client = MagicMock()
    client.models.generate_content.return_value = _good_response()

    with patch.object(orchestrator_agent, "get_client", return_value=client):
        recorder = recording.RecordingRecorder(run_id="run_a")
        recorded_result = pipeline.run_decision_pipeline(scenario, recorder=recorder)

    # No client stub active at all for replay -- a live call here would raise.
    replay_recorder = recording.ReplayRecorder(run_id="run_a")
    replayed_result = pipeline.run_decision_pipeline(scenario, recorder=replay_recorder)

    recorded_applied = next(s for s in recorded_result.stages if s.name == "applied")
    replayed_applied = next(s for s in replayed_result.stages if s.name == "applied")
    assert recorded_applied.evaluation.status == replayed_applied.evaluation.status
    assert recorded_applied.decision.model_dump(exclude={"mode"}) == replayed_applied.decision.model_dump(exclude={"mode"})
    assert replayed_applied.decision.mode == "agent"  # a successful replay looks like a normal agent decision


def test_02_resume_skips_already_recorded_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    scenario = _tick88_scenario(objective=Objective.MIN_CARBON)
    client = MagicMock()
    client.models.generate_content.return_value = _good_response()

    with patch.object(orchestrator_agent, "get_client", return_value=client):
        recorder = recording.RecordingRecorder(run_id="run_b")
        recorder.get_decision(scenario)
        recorder.get_decision(scenario)  # same scenario -> same cache key -> should hit cache

    assert client.models.generate_content.call_count == 1


def test_03b_scrub_redacts_todays_actual_configured_key_whatever_its_shape():
    # The real key in this project (AQ.<...>, an AI Studio key) does NOT match the AIza
    # pattern -- this is the defense that actually covers it, found by testing against the
    # real configured value rather than assuming the classic shape.
    from app.core.config import GEMINI_API_KEY
    assert GEMINI_API_KEY, "GEMINI_API_KEY must be configured for this test to mean anything"
    text = f"some request text containing {GEMINI_API_KEY} embedded in it"
    scrubbed = recording.scrub(text)
    assert GEMINI_API_KEY not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed


def test_03_scrub_redacts_api_key_pattern():
    fake_key = "AIza" + "x" * 35
    text = f"Authorization used key {fake_key} for this call."
    scrubbed = recording.scrub(text)
    assert fake_key not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed


def test_03c_scrub_redacts_aq_shaped_key_generically():
    # A DIFFERENT AQ.-shaped key than this project's real one -- proves the shape pattern
    # catches a judge's own key, not just the one literal value we happen to have.
    fake_key = "AQ." + "Zz9-xQ_kLm3pR8vWn5tY7cF1hD2bN6" * 2
    text = f"request used {fake_key} as credentials"
    scrubbed = recording.scrub(text)
    assert fake_key not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed


def test_04_recorded_file_never_contains_a_key_shaped_string(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    fake_key = "AIza" + "y" * 35
    scenario = _tick88_scenario(objective=Objective.MAX_RENEWABLE_UTILISATION)
    client = MagicMock()
    # Simulate a key-shaped string leaking into the model's own reasoning text.
    client.models.generate_content.return_value = _good_response(reasoning=f"Using config key {fake_key} as context.")

    with patch.object(orchestrator_agent, "get_client", return_value=client):
        recorder = recording.RecordingRecorder(run_id="run_c")
        pipeline.run_decision_pipeline(scenario, recorder=recorder)

    recording.write_manifest("run_c")
    run_dir = tmp_path / "run_c"
    for path in run_dir.rglob("*.json"):
        assert fake_key not in path.read_text(), f"key-shaped string leaked into {path}"


def test_05_verify_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    scenario = _tick88_scenario(objective=Objective.MAX_PROFIT)
    client = MagicMock()
    client.models.generate_content.return_value = _good_response()

    with patch.object(orchestrator_agent, "get_client", return_value=client):
        recorder = recording.RecordingRecorder(run_id="run_d")
        pipeline.run_decision_pipeline(scenario, recorder=recorder)

    recording.write_manifest("run_d")
    ok, problems = recording.verify("run_d")
    assert ok, problems

    # Modify one byte in a recorded call file.
    call_files = list((tmp_path / "run_d" / "calls").glob("*.json"))
    assert call_files
    target = call_files[0]
    data = json.loads(target.read_text())
    data["response_args"]["market_amount_mw"] = 999.0
    target.write_text(json.dumps(data))

    ok2, problems2 = recording.verify("run_d")
    assert not ok2
    assert any("modified" in p for p in problems2)


def test_07_reevaluate_stored_matches_live_pipeline_with_no_model_call():
    # Patch 3 addendum: reevaluate_stored re-scores an already-obtained proposal under
    # today's rules with zero model calls -- must match what the live pipeline would have
    # produced for that same (scenario, proposal) pair.
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
    from tests.test_acceptance import _original_tick88_proposal
    proposal = _original_tick88_proposal()

    with patch.object(orchestrator_agent, "decide", return_value=proposal):
        live_result = pipeline.run_decision_pipeline(scenario)  # LiveRecorder -> calls decide() (patched)

    # No client, no get_client patch, no recorder at all -- pure re-scoring.
    reeval_result = pipeline.reevaluate_stored(scenario, proposal)

    live_applied = next(s for s in live_result.stages if s.name == "applied")
    reeval_applied = next(s for s in reeval_result.stages if s.name == "applied")
    assert live_applied.evaluation.status == reeval_applied.evaluation.status
    assert live_applied.decision.model_dump() == reeval_applied.decision.model_dump()


def test_06_replay_miss_raises_call_failure_never_falls_back_to_live(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    (tmp_path / "run_e" / "calls").mkdir(parents=True)
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)
    replay_recorder = recording.ReplayRecorder(run_id="run_e")
    # No client stub configured at all -- if this fell back to a live call it would raise a
    # real network/auth error, not CallFailure. get_client is also never patched, proving no
    # attempt was made to reach it.
    with patch.object(orchestrator_agent, "get_client") as get_client_mock:
        result = pipeline.run_decision_pipeline(scenario, recorder=replay_recorder)
        get_client_mock.assert_not_called()
    applied = next(s for s in result.stages if s.name == "applied")
    assert applied.decision.mode == "parse_failed"
    assert applied.evaluation.status.value == "fail"
