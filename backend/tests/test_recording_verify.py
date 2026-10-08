"""Direct tests for recording.py's verify() -- the manifest-mismatch path (C.3). No model
calls; uses a temporary RECORDINGS_ROOT (monkeypatched) so nothing touches the real
recordings/ directory.
"""
from __future__ import annotations

import json

from app.data import recording


def _write_run(root, run_id, calls: dict[str, str]):
    calls_dir = root / run_id / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    for name, content in calls.items():
        (calls_dir / name).write_text(content)


def test_verify_passes_on_an_untouched_run(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    _write_run(tmp_path, "run_a", {"call1.json": json.dumps({"status": "ok"})})
    recording.write_manifest("run_a")

    ok, problems = recording.verify("run_a")
    assert ok is True
    assert problems == []


def test_verify_detects_modified_file(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    _write_run(tmp_path, "run_b", {"call1.json": json.dumps({"status": "ok", "response_args": {}})})
    recording.write_manifest("run_b")

    # Modify the call file AFTER the manifest was written -- the exact tamper case verify()
    # exists to catch.
    (tmp_path / "run_b" / "calls" / "call1.json").write_text(json.dumps({"status": "ok", "response_args": {"tampered": True}}))

    ok, problems = recording.verify("run_b")
    assert ok is False
    assert any("modified: calls/call1.json" in p for p in problems)


def test_verify_detects_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    _write_run(tmp_path, "run_c", {"call1.json": "{}", "call2.json": "{}"})
    recording.write_manifest("run_c")

    (tmp_path / "run_c" / "calls" / "call2.json").unlink()

    ok, problems = recording.verify("run_c")
    assert ok is False
    assert any("missing: calls/call2.json" in p for p in problems)


def test_verify_detects_an_untracked_file_added_after_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    _write_run(tmp_path, "run_d", {"call1.json": "{}"})
    recording.write_manifest("run_d")

    (tmp_path / "run_d" / "calls" / "call2.json").write_text("{}")  # added after the manifest, never recorded in it

    ok, problems = recording.verify("run_d")
    assert ok is False
    assert any("untracked" in p and "calls/call2.json" in p for p in problems)


def test_verify_fails_cleanly_with_no_manifest_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "RECORDINGS_ROOT", tmp_path)
    _write_run(tmp_path, "run_e", {"call1.json": "{}"})
    # No write_manifest() call at all.

    ok, problems = recording.verify("run_e")
    assert ok is False
    assert any("no manifest.sha256" in p for p in problems)
