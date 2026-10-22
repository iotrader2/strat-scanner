from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import api, config, data, earnings
from strat.earnings import parse_calendar, timing_for, timing_from_time, upcoming

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 15)


@pytest.mark.parametrize(
    "hhmm, expected",
    [((7, 0), "BMO"), ((6, 0), "BMO"), ((9, 29), "BMO"), ((16, 0), "AMC"), ((16, 30), "AMC"), ((20, 0), "AMC"),
     ((15, 0), None), ((9, 30), None), ((12, 0), None), ((0, 0), None)],
)
def test_timing_from_scheduled_time(hhmm, expected):
    assert timing_from_time(datetime(2026, 10, 21, *hhmm, tzinfo=ET)) == expected


def test_timing_converts_other_timezones_to_eastern():
    assert timing_from_time(datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)) == "AMC"  # 16:30 ET
    assert timing_from_time(datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc)) == "BMO"  # 07:00 ET


def test_parse_calendar_single_date_range_and_missing():
    assert parse_calendar({"Earnings Date": [date(2026, 10, 21)]}) == (date(2026, 10, 21), date(2026, 10, 21))
    assert parse_calendar({"Earnings Date": [date(2026, 11, 2), date(2026, 10, 28)]}) == (date(2026, 10, 28), date(2026, 11, 2))
    assert parse_calendar({"Earnings Date": None}) == (None, None)
    assert parse_calendar({"Earnings Date": []}) == (None, None)
    assert parse_calendar({}) == (None, None)
    assert parse_calendar(None) == (None, None)


def _earnings_dates(*stamps):
    idx = pd.DatetimeIndex([pd.Timestamp(s, tz=ET) for s in stamps], name="Earnings Date")
    return pd.DataFrame({"EPS Estimate": [1.0] * len(stamps)}, index=idx)


def test_timing_for_matches_the_calendar_date_only():
    df = _earnings_dates("2026-10-21 16:00", "2026-07-22 07:00")
    assert timing_for(df, date(2026, 10, 21)) == "AMC"
    assert timing_for(df, date(2026, 10, 22)) is None
    assert timing_for(None, date(2026, 10, 21)) is None
    assert timing_for(pd.DataFrame(), date(2026, 10, 21)) is None


def entry(d, end=None, timing=None):
    return {"date": d, "date_end": end, "timing": timing}


def test_upcoming_window_is_the_next_ten_calendar_days_including_today():
    assert upcoming(entry("2026-10-15", timing="BMO"), TODAY) == {
        "date": "2026-10-15", "date_end": None, "timing": "BMO", "days_until": 0}
    assert upcoming(entry("2026-10-25"), TODAY)["days_until"] == 10
    assert upcoming(entry("2026-10-26"), TODAY) is None
    assert upcoming(entry("2026-10-14"), TODAY) is None


def test_upcoming_never_guesses_without_a_date():
    assert upcoming(entry(None), TODAY) is None
    assert upcoming(None, TODAY) is None


def test_upcoming_keeps_estimated_ranges_visible():
    got = upcoming(entry("2026-10-12", "2026-10-16"), TODAY)
    assert got == {"date": "2026-10-12", "date_end": "2026-10-16", "timing": None, "days_until": 0}


def test_refresh_caches_results_and_skips_fresh_entries(tmp_path):
    db = tmp_path / "cache.sqlite3"
    calls = []

    def fetch(s):
        calls.append(s)
        if s == "BAD":
            raise RuntimeError("boom")
        return {"symbol": s, "date": "2026-10-21", "date_end": None, "timing": "AMC"}

    assert earnings.refresh_earnings(["TSLA", "BAD"], fetch=fetch, db_path=db) == 2
    cached = data.load_earnings(db)
    assert cached["TSLA"]["date"] == "2026-10-21" and cached["TSLA"]["timing"] == "AMC"
    assert "BAD" not in cached

    calls.clear()
    earnings.refresh_earnings(["TSLA", "BAD"], fetch=fetch, db_path=db)
    assert calls == ["BAD"]
    earnings.refresh_earnings(["TSLA"], max_age_hours=0, fetch=fetch, db_path=db)
    assert calls == ["BAD", "TSLA"]


def test_refresh_stores_no_date_when_the_source_has_none(tmp_path):
    db = tmp_path / "cache.sqlite3"
    earnings.refresh_earnings(["XYZ"], fetch=lambda s: {"symbol": s, "date": None, "date_end": None, "timing": None}, db_path=db)
    assert data.load_earnings(db)["XYZ"]["date"] is None


def test_fetch_earnings_uses_calendar_date_and_scheduled_time(monkeypatch):
    soon = date.today() + timedelta(days=3)

    class FakeTicker:
        def __init__(self, symbol):
            self.calendar = {"Earnings Date": [soon]}

        def get_earnings_dates(self, limit):
            return _earnings_dates(f"{soon} 07:00")

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    assert earnings.fetch_earnings("MRNA") == {"symbol": "MRNA", "date": soon.isoformat(), "date_end": None, "timing": "BMO"}


def test_fetch_earnings_without_calendar_returns_no_date(monkeypatch):
    class NoFundamentals:
        def __init__(self, symbol):
            pass

        @property
        def calendar(self):
            raise RuntimeError("404 No fundamentals data found")

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", NoFundamentals)
    assert earnings.fetch_earnings("XLE")["date"] is None


def test_api_rows_carry_the_warning_only_for_stocks_reporting_soon(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(earnings, "today_et", lambda: TODAY)
    base = {"has_setup": True, "price": 100.0, "avg_dollar_volume": 1e9, "score": 80.0, "rs": 0.95, "leadership": {"breakdown": "none"}}
    monkeypatch.setattr(api.State, "scan", [
        {**base, "symbol": "TSLA", "kind": "stock"},
        {**base, "symbol": "JPM", "kind": "stock"},
        {**base, "symbol": "NODATE", "kind": "stock"},
        {**base, "symbol": "XLE", "kind": "etf"},
    ])
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: api.State.scan)
    data.save_earnings([
        {"symbol": "TSLA", "date": "2026-10-21", "timing": "AMC"},
        {"symbol": "JPM", "date": "2027-01-14", "timing": "BMO"},
        {"symbol": "NODATE", "date": None},
        {"symbol": "XLE", "date": "2026-10-16"},
    ])
    rows = {r["symbol"]: r["earnings"] for r in TestClient(api.app).get("/api/scan").json()["rows"]}
    assert rows == {
        "TSLA": {"date": "2026-10-21", "date_end": None, "timing": "AMC", "days_until": 6},
        "JPM": None,
        "NODATE": None,
        "XLE": None,
    }
