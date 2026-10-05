"""File input (bulk CSV/Excel upload, Patch 3 Step 5): row parsing/validation, the
state-derived floor band, run-store lookup, and the API surface. No model calls.
"""
from __future__ import annotations

import csv
import io

from app.agents.orchestrator_agent import scenario_hash
from app.data import file_input
from app.data.recording import cache_key
from app.models.schemas import Difficulty


def _example_csv_bytes() -> bytes:
    headers = [c.name for c in file_input.TEMPLATE_COLUMNS]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    for row in file_input.EXAMPLE_DAY_ROWS:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def test_01_good_row_round_trips_with_derived_floor_band():
    row = dict(file_input.EXAMPLE_DAY_ROWS[7])  # the price-spike row
    scenario = file_input.row_to_scenario(row, 7)
    assert scenario.difficulty == Difficulty.FILE_INPUT
    assert scenario.electricity_price_per_mwh >= 100.0
    # price >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD -> some_volatility -> 30-45% band, not the
    # neutral 20-60 placeholder the draft used internally.
    assert (scenario.expected_floor_min_pct, scenario.expected_floor_max_pct) == (30.0, 45.0)


def test_02_calm_row_gets_the_stable_band():
    row = dict(file_input.EXAMPLE_DAY_ROWS[0])  # no storm, no outage, price well under threshold
    scenario = file_input.row_to_scenario(row, 0)
    assert (scenario.expected_floor_min_pct, scenario.expected_floor_max_pct) == (20.0, 30.0)


def test_03_bad_row_reports_specific_attributable_errors():
    row = dict(file_input.EXAMPLE_DAY_ROWS[0])
    row["battery_1_soc_pct"] = 150.0
    results = file_input.validate_rows([row])
    assert results[0].status == "error"
    assert "battery_1_soc_pct" in results[0].errors[0]
    assert "150" in results[0].errors[0]


def test_04_bad_row_never_enters_the_run_store():
    good = dict(file_input.EXAMPLE_DAY_ROWS[0])
    bad = dict(file_input.EXAMPLE_DAY_ROWS[1])
    bad["wind_output_mw"] = "not-a-number"
    results = file_input.validate_rows([good, bad])
    run_id = "test_run_bad_row_store"
    file_input.store_run(run_id, results)
    assert file_input.get_validated_scenario(run_id, 0) is not None
    assert file_input.get_validated_scenario(run_id, 1) is None


def test_05_unknown_row_index_and_unknown_run_id_both_return_none():
    results = file_input.validate_rows([dict(file_input.EXAMPLE_DAY_ROWS[0])])
    run_id = "test_run_unknown_lookup"
    file_input.store_run(run_id, results)
    assert file_input.get_validated_scenario(run_id, 99) is None
    assert file_input.get_validated_scenario("never_previewed", 0) is None


def test_06_identical_content_different_tick_gets_distinct_cache_key_via_sample_index():
    # scenario_hash deliberately excludes tick, so two rows with identical content but
    # different ticks would collide in the recording cache without the sample_index fix.
    row = dict(file_input.EXAMPLE_DAY_ROWS[0])
    s_row0 = file_input.row_to_scenario(dict(row, tick=1), 0)
    s_row1 = file_input.row_to_scenario(dict(row, tick=2), 1)
    assert scenario_hash(s_row0) == scenario_hash(s_row1)  # confirms the collision risk is real
    key0 = cache_key(scenario_hash(s_row0), "pv", "model", 1.0, sample_index=0)
    key1 = cache_key(scenario_hash(s_row1), "pv", "model", 1.0, sample_index=1)
    assert key0 != key1


def test_07_csv_and_xlsx_round_trip_to_the_same_validation_result():
    csv_bytes = _example_csv_bytes()
    xlsx_bytes = file_input.make_example_file()
    csv_rows = file_input.validate_rows(file_input.parse_rows(csv_bytes, "day.csv"))
    xlsx_rows = file_input.validate_rows(file_input.parse_rows(xlsx_bytes, "day.xlsx"))
    assert len(csv_rows) == len(xlsx_rows) == 12
    assert all(r.status == "ok" for r in csv_rows)
    assert all(r.status == "ok" for r in xlsx_rows)


def test_08_file_too_large_is_rejected_before_parsing():
    huge = b"tick,seed\n" + b"1,1\n" * 2_000_000  # well over MAX_FILE_BYTES
    try:
        file_input.parse_rows(huge, "huge.csv")
        assert False, "expected FileInputError"
    except file_input.FileInputError as e:
        assert "MB" in str(e)


def test_09_too_many_rows_is_rejected():
    headers = [c.name for c in file_input.TEMPLATE_COLUMNS]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    for i in range(file_input.MAX_ROWS + 1):
        w.writerow(dict(file_input.EXAMPLE_DAY_ROWS[0], tick=i))
    try:
        file_input.parse_rows(buf.getvalue().encode("utf-8"), "toomany.csv")
        assert False, "expected FileInputError"
    except file_input.FileInputError as e:
        assert "row" in str(e).lower()


def test_10_run_id_is_deterministic_for_identical_content():
    # Content-based (not raw-file-bytes-based): .xlsx serialization isn't byte-stable across
    # separate save calls even with identical data, so run_id must be computed from the
    # validated scenario content, not the uploaded bytes -- confirmed here across CSV vs
    # .xlsx of the exact same rows, which must agree.
    results_csv = file_input.validate_rows(file_input.parse_rows(_example_csv_bytes(), "day.csv"))
    results_xlsx = file_input.validate_rows(file_input.parse_rows(file_input.make_example_file(), "day.xlsx"))
    assert file_input.run_id_for(results_csv) == file_input.run_id_for(results_xlsx)
