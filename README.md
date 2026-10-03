# Renewable Energy Orchestrator

ET × Accenture AI Hackathon — Agentic Edition, Problem 4 (Utilities).

A dual-agent system: a **Scenario Agent** generates realistic 15-minute grid states at
increasing difficulty, an **Orchestrator Agent** (Gemini, via function calling) decides
battery, market, curtailment and demand-response actions, and an **Evaluator** checks each
decision against a deterministic hard-fail checklist plus the scenario's objective-specific
expected behavior. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design rationale and
[NEXT_STEPS.md](NEXT_STEPS.md) for what's left to build before submission.

## Prerequisites

Python, Node.js, and Git — already installed on this machine as of 2026-10-03.

## Backend setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your free Gemini API key (from
[aistudio.google.com](https://aistudio.google.com)):

```bash
copy backend\.env.example backend\.env
```

Run the API:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs at `http://localhost:8000/docs`.

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:5173`.

## What's implemented

- `backend/app/agents/scenario_agent.py` — deterministic, seedable environment generator
  across 4 difficulty profiles (`stable_day`, `cloudy_afternoon`, `price_spike`,
  `multi_failure_cascade`), tagging each scenario with an `expected_behavior` hidden from
  the orchestrator.
- `backend/app/agents/orchestrator_agent.py` — Gemini function-calling call grounded in the
  4 heuristics from the Learning Guide (merit order, battery arbitrage, curtailment-as-last-
  resort, reliability-as-hard-constraint) with the Default Priority fallback when no
  objective is declared.
- `backend/app/data/rules.py` — the 6 hard-fail rules from the Learning Guide, as plain
  deterministic Python.
- `backend/app/agents/evaluator.py` — runs hard-fail rules + an objective-specific
  expected-behavior check, returns pass / fail / flagged.
- `frontend/` — React dashboard: Auto mode (one-click scenario → decision → evaluation),
  Manual mode (generate, hand-edit via the API, then step through), and a Batch Run panel
  that reports pass-rate across N scenarios per difficulty (supports stripping the
  objective to demo the fallback).

This is a working MVP skeleton, not a finished submission — see NEXT_STEPS.md.
