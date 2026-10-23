"""Nasdaq 52-week new highs vs new lows from the same WSJ diary request: strict, independent, hidden when unknown."""

import json

import pytest

from strat import api, breadth, config

# Trimmed from the live diary of 2026-10-22 (StockCharts that day: $NAHGH 115, $NALOW 458, $NAHL -343).
DIARY = {
    "data": {
        "instrumentSets": [
            {
                "headerFields": [{"value": "name", "label": "Issues"}],
                "instruments": [
                    {"name": "Advancing", "NASDAQ": "2,105", "NYSE": "1,555"},
                    {"name": "Declining", "NASDAQ": "2,833", "NYSE": "1,152"},
                    {"name": "Unchanged", "NASDAQ": "154", "NYSE": "80"},
                    {"name": "Total", "NASDAQ": "5,092", "NYSE": "2,787"},
                ],
            },
            {
                "headerFields": [{"value": "name", "label": "Issues At"}],
                "instruments": [
                    {"name": "New Highs", "NASDAQ": "110", "NYSE": "105"},
                    {"name": "New Lows", "NASDAQ": "455", "NYSE": "136"},
                ],
            },
            {
                "headerFields": [{"value": "name", "label": "Share Volume"}],
                "instruments": [{"name": "Total", "NASDAQ": "9,357,570,517", "NYSE": "6,068,764,971"}],
            },
        ],
        "timestamp": "4:15 PM EDT 10/22/26",
    },
}


def diary(mutate=None) -> dict:
    payload = json.loads(json.dumps(DIARY))
    if mutate:
        mutate(payload)
    return payload


@pytest.fixture(autouse=True)
def fresh_cache():
    breadth.clear_cache()
    yield
    breadth.clear_cache()


def test_parses_nasdaq_column_of_the_issues_at_table():
    assert breadth.parse_nasdaq_highs_lows(DIARY) == {
        "highs": 110,
        "lows": 455,
        "as_of": "4:15 PM EDT 10/22/26",
        "session": "2026-10-22",
    }


def test_zero_is_a_real_count():
    payload = diary(lambda d: d["data"]["instrumentSets"][1]["instruments"][0].update(NASDAQ="0"))
    assert breadth.parse_nasdaq_highs_lows(payload)["highs"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["data"]["instrumentSets"].pop(1),  # no Issues At table
        lambda d: d["data"]["instrumentSets"][1]["instruments"].pop(1),  # missing New Lows
        lambda d: d["data"]["instrumentSets"][1]["instruments"][0].update(NASDAQ="-"),  # not a number
        lambda d: d["data"]["instrumentSets"][1]["instruments"][0].pop("NASDAQ"),  # NYSE only
        lambda d: d["data"].update(timestamp="4:15 PM EDT"),  # no date
    ],
)
def test_anything_incomplete_is_rejected_rather_than_guessed(mutate):
    assert breadth.parse_nasdaq_highs_lows(diary(mutate)) is None


def test_one_request_feeds_both_readings_and_each_stands_alone():
    calls = []
    no_extremes = diary(lambda d: d["data"]["instrumentSets"].pop(1))
    breadth.refresh_nasdaq_issues(lambda: calls.append(1) or json.dumps(no_extremes))
    assert breadth.nasdaq_issues("2026-10-22")["advancing"] == 2105
    assert breadth.nasdaq_highs_lows("2026-10-22") is None
    breadth.refresh_nasdaq_issues(lambda: calls.append(1) or json.dumps(DIARY))
    assert breadth.nasdaq_highs_lows("2026-10-22")["lows"] == 455
    assert len(calls) == 2  # one request per refresh, not one per reading


def test_a_failed_fetch_keeps_the_last_real_reading():
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    breadth.refresh_nasdaq_issues(lambda: (_ for _ in ()).throw(OSError("blocked")))
    breadth.refresh_nasdaq_issues(lambda: json.dumps(diary(lambda d: d["data"]["instrumentSets"].pop(1))))
    assert breadth.nasdaq_highs_lows("2026-10-22")["highs"] == 110


def test_hidden_when_stale_or_never_read():
    assert breadth.nasdaq_highs_lows("2026-10-22") is None
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    assert breadth.nasdaq_highs_lows("2026-10-23") is None
    assert breadth.nasdaq_highs_lows(None) is None


def test_breadth_route_reports_it_for_the_scan_session_without_fetching(monkeypatch):
    monkeypatch.setattr(api, "fetch_breadth", lambda: {"nasi": None, "fear_greed": None})
    monkeypatch.setattr(api.State, "scan", [{"symbol": "AAA", "change_pct": 1.0, "as_of": "2026-10-22"}])
    monkeypatch.setattr(api.State, "daily", {})
    monkeypatch.setattr(breadth, "_diary_text", lambda: (_ for _ in ()).throw(AssertionError("fetched on request")))
    assert api.breadth()["nasdaq_highs_lows"] is None
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    assert api.breadth()["nasdaq_highs_lows"] == {
        "highs": 110,
        "lows": 455,
        "as_of": "4:15 PM EDT 10/22/26",
        "session": "2026-10-22",
    }


def test_the_refresh_job_reads_it_inside_its_slot(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "scheduler_enabled", lambda: True)
    monkeypatch.setattr(api.data, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: [])
    monkeypatch.setattr(api, "_publish_status", lambda: None)
    monkeypatch.setattr(api, "backfill_industries", lambda m: None)
    monkeypatch.setattr(api, "_refresh_earnings", lambda *a, **k: None)
    monkeypatch.delenv("STRAT_FETCH_SUBPROCESS", raising=False)
    monkeypatch.setattr(breadth, "_diary_text", lambda: seen.append(api.State.job) or json.dumps(DIARY))
    api.State.job = "refresh"
    try:
        api._run_refresh(full=False, period="5d", with_earnings=False)
    finally:
        api.State.job = None
    assert seen == ["refresh"]
    assert breadth.nasdaq_highs_lows("2026-10-22")["highs"] == 110
