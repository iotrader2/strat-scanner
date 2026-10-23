"""Nasdaq advancers vs decliners from the WSJ markets diary: parsed strictly, fetched by the job, hidden when unknown."""

import json

import pytest

from strat import api, breadth, config

# Trimmed from the live diary of 2026-10-22 (StockCharts $NAAD closed at -728 = 2,105 - 2,833 that day).
DIARY = {
    "id": "x",
    "type": "mdc_marketsdiary",
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
                "headerFields": [{"value": "name", "label": "Share Volume"}],
                "instruments": [
                    {"name": "Advancing", "NASDAQ": "4,014,749,151", "NYSE": "3,153,502,407"},
                    {"name": "Declining", "NASDAQ": "5,280,114,704", "NYSE": "2,786,814,439"},
                    {"name": "Unchanged", "NASDAQ": "62,706,662", "NYSE": "128,448,125"},
                ],
            },
        ],
        "timestamp": "4:15 PM EDT 10/22/26",
    },
}


@pytest.fixture(autouse=True)
def fresh_cache():
    breadth.clear_cache()
    yield
    breadth.clear_cache()


def test_parses_the_issues_table_not_share_volume():
    got = breadth.parse_nasdaq_issues(DIARY)
    assert got == {
        "advancing": 2105,
        "declining": 2833,
        "unchanged": 154,
        "as_of": "4:15 PM EDT 10/22/26",
        "session": "2026-10-22",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["data"]["instrumentSets"].pop(0),  # no Issues table
        lambda d: d["data"]["instrumentSets"][0]["instruments"][1].update(NASDAQ="n/a"),  # bad number
        lambda d: d["data"]["instrumentSets"][0]["instruments"].pop(2),  # missing Unchanged
        lambda d: d["data"].update(timestamp="4:15 PM EDT"),  # no date
        lambda d: d.update(data=None),
    ],
)
def test_anything_incomplete_is_rejected_rather_than_guessed(mutate):
    payload = json.loads(json.dumps(DIARY))
    mutate(payload)
    assert breadth.parse_nasdaq_issues(payload) is None


def test_diary_session_dates():
    assert breadth.diary_session("4:15 PM EDT 10/22/26") == "2026-10-22"
    assert breadth.diary_session("9:31 AM EST 1/5/2027") == "2027-01-05"
    assert breadth.diary_session("13/45/26") is None
    assert breadth.diary_session(None) is None


def test_a_failed_fetch_keeps_the_last_real_reading_and_never_invents_one():
    assert breadth.refresh_nasdaq_issues(lambda: (_ for _ in ()).throw(OSError("blocked"))) is None
    assert breadth.nasdaq_issues("2026-10-22") is None
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    kept = breadth.refresh_nasdaq_issues(lambda: "<html>blocked</html>")
    assert kept["advancing"] == 2105


def test_shown_only_for_the_universe_session_or_later():
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    assert breadth.nasdaq_issues("2026-10-22")["declining"] == 2833
    assert breadth.nasdaq_issues("2026-10-21") is not None
    assert breadth.nasdaq_issues("2026-10-23") is None  # yesterday's diary next to today's universe: hide
    assert breadth.nasdaq_issues(None) is None


def test_breadth_route_adds_nasdaq_issues_for_the_scan_session(monkeypatch):
    monkeypatch.setattr(api, "fetch_breadth", lambda: {"nasi": None, "fear_greed": None})
    monkeypatch.setattr(api.State, "scan", [{"symbol": "AAA", "change_pct": 1.0, "as_of": "2026-10-22"}])
    monkeypatch.setattr(api.State, "daily", {})
    assert api.breadth()["nasdaq_issues"] is None
    breadth.refresh_nasdaq_issues(lambda: json.dumps(DIARY))
    body = api.breadth()
    assert body["issues"]["advancing"] == 1
    assert body["nasdaq_issues"]["advancing"] == 2105


def test_the_refresh_job_fetches_the_diary_inside_its_slot(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "scheduler_enabled", lambda: True)
    monkeypatch.setattr(api.data, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: [])
    monkeypatch.setattr(api, "_publish_status", lambda: None)
    monkeypatch.setattr(api, "backfill_industries", lambda m: None)
    monkeypatch.setattr(api, "_refresh_earnings", lambda *a, **k: None)
    monkeypatch.delenv("STRAT_FETCH_SUBPROCESS", raising=False)
    monkeypatch.setattr(breadth, "_diary_text", lambda: seen.append(api.State.job) or json.dumps(DIARY))
    api.State.job = "refresh"  # as start_refresh sets it
    try:
        api._run_refresh(full=False, period="5d", with_earnings=False)
    finally:
        api.State.job = None
    assert seen == ["refresh"]
    assert breadth.nasdaq_issues("2026-10-22")["unchanged"] == 154


def test_page_requests_never_fetch_the_diary(monkeypatch):
    monkeypatch.setattr(breadth, "_diary_text", lambda: (_ for _ in ()).throw(AssertionError("fetched on request")))
    monkeypatch.setattr(api, "fetch_breadth", lambda: {"nasi": None, "fear_greed": None})
    monkeypatch.setattr(api.State, "scan", [{"symbol": "AAA", "change_pct": 1.0, "as_of": "2026-10-22"}])
    assert api.breadth()["nasdaq_issues"] is None
