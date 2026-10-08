"""HTTP-level tests via FastAPI's TestClient (C.2) -- nothing in the suite touched the API
layer at all before this file existed. No model calls (httpx is already a transitive
dependency of google-genai, already pinned in requirements.txt -- no new dependency).
"""
from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from app.agents.pipeline import reevaluate_stored
from app.data import file_input
from app.main import app
from app.models.schemas import BatteryAction
from tests.test_acceptance import _decision, _tick88_scenario

client = TestClient(app)


def _one_result_payload():
    scenario = _tick88_scenario(tick=1, seed=1, total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    proposal = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=8.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    result = reevaluate_stored(scenario, proposal)
    return result.model_dump(mode="json")


def test_day_report_route_returns_a_well_shaped_report():
    payload = {"results": [_one_result_payload()]}
    res = client.post("/api/file-input/day-report", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 1
    assert "verdict_summary" in body and "counts_first_attempt_raw" in body["verdict_summary"]
    assert "comparison" in body and "cumulative" in body


def test_day_report_csv_route_returns_csv_content_type_and_one_data_row():
    payload = {"results": [_one_result_payload()]}
    res = client.post("/api/file-input/day-report/csv", json=payload)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    lines = res.text.strip().splitlines()
    assert len(lines) == 2  # header + 1 data row


def test_day_report_route_handles_an_empty_results_list_without_crashing():
    # Not a rejection -- a 0-row report is valid (build_day_report guards its
    # division-by-row_count internally); this exercises that guard through the real route.
    res = client.post("/api/file-input/day-report", json={"results": []})
    assert res.status_code == 200
    assert res.json()["row_count"] == 0


def test_file_input_run_row_unknown_run_id_is_a_clear_404_not_a_crash():
    res = client.post("/api/file-input/run-row", json={"run_id": "does-not-exist", "row_index": 0, "mode": "replay"})
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert "does-not-exist" in detail
    assert "preview the file again" in detail


def test_file_input_preview_multipart_upload_of_the_real_example_day():
    headers = [c.name for c in file_input.TEMPLATE_COLUMNS]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    for row in file_input.EXAMPLE_DAY_ROWS:
        w.writerow(row)
    csv_bytes = buf.getvalue().encode("utf-8")

    res = client.post("/api/file-input/preview", files={"file": ("example_day.csv", csv_bytes, "text/csv")})
    assert res.status_code == 200
    body = res.json()
    assert body["ok_count"] == len(file_input.EXAMPLE_DAY_ROWS)
    assert body["error_count"] == 0
    assert "run_id" in body and len(body["rows"]) == len(file_input.EXAMPLE_DAY_ROWS)


def test_file_input_preview_rejects_a_non_spreadsheet_upload():
    res = client.post("/api/file-input/preview", files={"file": ("not_a_sheet.pdf", b"%PDF-1.4 not really a pdf either", "application/pdf")})
    assert res.status_code == 400
    assert "upload a .csv or .xlsx" in res.json()["detail"]
