"""Patch 3, Step 2: record every model call and replay a recorded run with no API key and no
network. Only the Orchestrator's model call is recorded/replayed — physics, the balancer and
the Evaluator always run live (see pipeline.run_decision_pipeline), so a replayed run proves
the verdicts are reproducible, not that the physics layer was skipped.

Cache key: (scenario_hash, prompt_version, model, temperature, sample_index) — exactly the
Patch 3 brief's key. scenario_hash/prompt_version live in orchestrator_agent.py since they
depend on exactly what's sent to the model; this module only stores/looks things up by them.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Protocol

from app.agents import orchestrator_agent
from app.agents.orchestrator_agent import CallFailure, args_from_response, build_request, decision_from_args
from app.core.config import GEMINI_API_KEY
from app.models.schemas import Decision, EnvironmentState

RECORDINGS_ROOT = Path(__file__).resolve().parents[3] / "recordings"  # .../app/data/recording.py -> repo root

# Two defenses, not one: a shape-based pattern for the classic Google Cloud Console key
# format ("AIza" + 35 chars) AND a literal scrub of today's actual configured key, whatever
# shape it has. Checking only the pattern would have MISSED this project's real key: it's
# "AQ." + base64url-ish chars (an AI Studio key), not "AIza..." — found by actually comparing
# scrub()'s coverage against backend/.env's real value rather than assuming the common shape.
_API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


def scrub(text: str) -> str:
    text = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
    if GEMINI_API_KEY and GEMINI_API_KEY in text:
        text = text.replace(GEMINI_API_KEY, "[REDACTED_API_KEY]")
    return text


def _scrub_json_text(text: str) -> str:
    return scrub(text)


def cache_key(scenario_hash: str, prompt_version: str, model: str, temperature: float, sample_index: int = 0) -> str:
    raw = f"{scenario_hash}:{prompt_version}:{model}:{temperature}:{sample_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class Recorder(Protocol):
    mode: str

    def get_decision(self, scenario: EnvironmentState) -> Decision: ...


class LiveRecorder:
    """Default — calls Gemini, records nothing. Behaviorally identical to the pre-Step-2
    pipeline; every existing caller that passes no recorder gets this."""

    mode = "live"

    def get_decision(self, scenario: EnvironmentState) -> Decision:
        return orchestrator_agent.decide(scenario)


class RecordingRecorder:
    """Calls Gemini and saves every call under recordings/<run_id>/calls/<key>.json. Resume
    is automatic: if a call for this exact key is already on disk, it's reused instead of
    calling again — an interrupted run picks up without repeating calls it already made."""

    mode = "record"

    def __init__(self, run_id: str, sample_index: int = 0):
        self.run_id = run_id
        self.sample_index = sample_index
        self.dir = RECORDINGS_ROOT / run_id / "calls"
        self.dir.mkdir(parents=True, exist_ok=True)

    def get_decision(self, scenario: EnvironmentState) -> Decision:
        request = build_request(scenario)
        key = cache_key(request["scenario_hash"], request["prompt_version"], request["model"], request["temperature"], self.sample_index)
        path = self.dir / f"{key}.json"

        if path.exists():
            record = json.loads(path.read_text())
            if record["status"] == "ok":
                return decision_from_args(scenario, record["response_args"])
            raise CallFailure(record["failure_kind"], record["failure_detail"])

        record = {
            "cache_key": key, "scenario_hash": request["scenario_hash"], "prompt_version": request["prompt_version"],
            "model": request["model"], "temperature": request["temperature"], "sample_index": self.sample_index,
            "tick": scenario.tick, "seed": scenario.seed, "recorded_at": time.time(),
            "request": {"contents": request["contents"]},
        }
        t0 = time.monotonic()
        try:
            response = orchestrator_agent._call_gemini_live(request)
            args = args_from_response(response)
            record["status"] = "ok"
            record["response_args"] = args
            record["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
            path.write_text(_scrub_json_text(json.dumps(record, indent=2, default=str)))
            return decision_from_args(scenario, args)
        except CallFailure as e:
            record["status"] = "failed"
            record["failure_kind"] = e.kind
            record["failure_detail"] = e.detail
            record["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
            path.write_text(_scrub_json_text(json.dumps(record, indent=2, default=str)))
            raise


class ReplayRecorder:
    """No key, no network: looks up a stored recording by recomputing today's cache key and
    reconstructs the Decision from it. Never falls back to a live call — a miss is a
    CallFailure, not a silent live call, so a replay can be trusted not to have quietly
    spent quota. A prompt or scenario-generator change changes the key, so a replay against
    a stale recording fails loudly instead of matching the wrong thing."""

    mode = "replay"

    def __init__(self, run_id: str, sample_index: int = 0):
        self.run_id = run_id
        self.sample_index = sample_index
        self.dir = RECORDINGS_ROOT / run_id / "calls"

    def get_decision(self, scenario: EnvironmentState) -> Decision:
        s_hash = orchestrator_agent.scenario_hash(scenario)
        p_ver = orchestrator_agent.prompt_version()
        key = cache_key(s_hash, p_ver, orchestrator_agent.MODEL, orchestrator_agent.GEMINI_TEMPERATURE, self.sample_index)
        path = self.dir / f"{key}.json"
        if not path.exists():
            raise CallFailure("parse", f"no recording for this scenario in run {self.run_id!r} (key {key})")
        record = json.loads(path.read_text())
        if record["status"] != "ok":
            raise CallFailure(record["failure_kind"], record["failure_detail"])
        return decision_from_args(scenario, record["response_args"])


def write_run_meta(run_id: str, **meta) -> Path:
    run_dir = RECORDINGS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "meta.json"
    path.write_text(_scrub_json_text(json.dumps({"run_id": run_id, **meta}, indent=2, default=str)))
    return path


def list_runs() -> list[dict]:
    if not RECORDINGS_ROOT.exists():
        return []
    runs = []
    for run_dir in sorted(RECORDINGS_ROOT.iterdir()):
        meta_path = run_dir / "meta.json"
        if meta_path.exists():
            runs.append(json.loads(meta_path.read_text()))
        elif run_dir.is_dir():
            runs.append({"run_id": run_dir.name})
    return runs


def write_manifest(run_id: str) -> Path:
    """SHA-256 of every recorded file — `verify()` detects any later modification."""
    run_dir = RECORDINGS_ROOT / run_id
    manifest = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            manifest[str(path.relative_to(run_dir)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = run_dir / "manifest.sha256"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def verify(run_id: str) -> tuple[bool, list[str]]:
    run_dir = RECORDINGS_ROOT / run_id
    manifest_path = run_dir / "manifest.sha256"
    if not manifest_path.exists():
        return False, ["no manifest.sha256 for this run -- call write_manifest() after recording"]
    manifest = json.loads(manifest_path.read_text())
    problems = []
    for rel_path, expected_digest in manifest.items():
        path = run_dir / rel_path
        if not path.exists():
            problems.append(f"missing: {rel_path}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
            problems.append(f"modified: {rel_path}")
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            rel = str(path.relative_to(run_dir)).replace("\\", "/")
            if rel not in manifest:
                problems.append(f"untracked (added after manifest): {rel}")
    return len(problems) == 0, problems
