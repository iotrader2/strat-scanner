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


def test_upcoming_window_is_calendar_days_including_today_defaulting_to_three():
    """Weekends count. The default is 3 calendar days; a caller can still pass another window."""
    assert earnings.DEFAULT_WARNING_WINDOW_DAYS == 3
    assert upcoming(entry("2026-10-15", timing="BMO"), TODAY) == {
        "date": "2026-10-15", "date_end": None, "timing": "BMO", "days_until": 0}
    assert upcoming(entry("2026-10-18"), TODAY)["days_until"] == 3
    assert upcoming(entry("2026-10-19"), TODAY) is None  # 4 calendar days out
    assert upcoming(entry("2026-10-16"), TODAY, window=0) is None  # 0 is today only
    assert upcoming(entry("2026-10-15"), TODAY, window=0)["days_until"] == 0
    assert upcoming(entry("2026-10-25"), TODAY, window=10)["days_until"] == 10
    assert upcoming(entry("2026-10-26"), TODAY, window=10) is None
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


def test_fetch_earnings_timing_lookahead_stays_fifteen_calendar_days(monkeypatch):
    """Shortening the warning window must not change how far ahead timing is fetched."""
    assert earnings.TIMING_LOOKAHEAD_DAYS == 15
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            self.calendar = {"Earnings Date": [date.today() + timedelta(days=int(symbol))]}

        def get_earnings_dates(self, limit):
            calls.append(int(self.calendar["Earnings Date"][0].toordinal() - date.today().toordinal()))
            return _earnings_dates(f"{self.calendar['Earnings Date'][0]} 16:00")

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    assert earnings.fetch_earnings("15")["timing"] == "AMC"
    assert earnings.fetch_earnings("16")["timing"] is None
    assert calls == [15]


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


def test_api_rows_carry_the_warning_only_inside_the_saved_window(tmp_path, monkeypatch):
    """Scanner, watchlist and positions share one window: 3 calendar days unless the user saved another."""
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(earnings, "today_et", lambda: TODAY)
    base = {"has_setup": True, "price": 100.0, "avg_dollar_volume": 1e9, "score": 80.0, "rs": 0.95, "leadership": {"breakdown": "none"}}
    monkeypatch.setattr(api.State, "scan", [
        {**base, "symbol": "SOON", "kind": "stock"},
        {**base, "symbol": "TSLA", "kind": "stock"},
        {**base, "symbol": "JPM", "kind": "stock"},
        {**base, "symbol": "NODATE", "kind": "stock"},
        {**base, "symbol": "XLE", "kind": "etf"},
    ])
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: api.State.scan)
    data.save_earnings([
        {"symbol": "SOON", "date": "2026-10-18", "timing": "BMO"},  # 3 calendar days
        {"symbol": "TSLA", "date": "2026-10-21", "timing": "AMC"},  # 6 calendar days
        {"symbol": "JPM", "date": "2027-01-14", "timing": "BMO"},
        {"symbol": "NODATE", "date": None},
        {"symbol": "XLE", "date": "2026-10-16"},
    ])
    data.add_to_watchlist("SOON")
    data.add_to_watchlist("TSLA")
    data.save_position("XLE", 90.0, None, "2026-10-01")
    client = TestClient(api.app)
    expected = {
        "SOON": {"date": "2026-10-18", "date_end": None, "timing": "BMO", "days_until": 3},
        "TSLA": None,
        "JPM": None,
        "NODATE": None,
        "XLE": None,
    }
    rows = {r["symbol"]: r["earnings"] for r in client.get("/api/scan").json()["rows"]}
    assert rows == expected
    watched = {r["symbol"]: r["earnings"] for r in client.get("/api/watchlist").json()["rows"]}
    assert watched == {"SOON": expected["SOON"], "TSLA": None}
    held = {p["symbol"]: p["row"]["earnings"] for p in client.get("/api/positions").json()["positions"]}
    assert held == {"XLE": None}

    saved = client.put("/api/alerts/settings", json={"earnings_window_days": 10}).json()
    assert saved["settings"]["earnings_window_days"] == 10
    assert saved["defaults"]["earnings_window_days"] == 3
    widened = {r["symbol"]: r["earnings"] for r in client.get("/api/scan").json()["rows"]}
    assert widened["TSLA"] == {"date": "2026-10-21", "date_end": None, "timing": "AMC", "days_until": 6}
    assert widened["SOON"]["days_until"] == 3
    assert client.put("/api/alerts/settings", json={"earnings_window_days": 31}).status_code == 422
    assert client.put("/api/alerts/settings", json={"earnings_window_days": -1}).status_code == 422


def test_alert_rows_use_the_same_earnings_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(earnings, "today_et", lambda: TODAY)
    monkeypatch.setattr(api.State, "scan", [
        {"symbol": "SOON", "kind": "stock"},
        {"symbol": "TSLA", "kind": "stock"},
        {"symbol": "XLE", "kind": "etf"},
    ])
    data.save_earnings([
        {"symbol": "SOON", "date": "2026-10-18", "timing": "BMO"},
        {"symbol": "TSLA", "date": "2026-10-21", "timing": "AMC"},
        {"symbol": "AAPL", "date": "2026-10-17", "timing": "AMC"},  # in the universe, not in this scan
        {"symbol": "XLE", "date": "2026-10-16"},
    ])
    monkeypatch.setattr(
        api.alerts_store,
        "list_alerts",
        lambda **_k: [{"symbol": s, "id": i} for i, s in enumerate(["SOON", "TSLA", "XLE", "AAPL", "ZZZNOTASTOCK"])],
    )
    monkeypatch.setattr(api.alerts_store, "sessions", lambda: [])
    monkeypatch.setattr(api.alerts_store, "unread_count", lambda: 0)
    monkeypatch.setattr(api.alerts_live, "last_run", lambda: {})
    flags = {
        a["symbol"]: a["earnings"]
        for a in TestClient(api.app).get("/api/alerts", params={"session": "2026-10-15"}).json()["alerts"]
    }
    assert flags["SOON"]["days_until"] == 3
    assert flags["AAPL"]["days_until"] == 2
    assert flags["TSLA"] is None
    assert flags["XLE"] is None
    assert flags["ZZZNOTASTOCK"] is None


def test_chart_page_uses_the_same_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(earnings, "today_et", lambda: TODAY)
    monkeypatch.setattr(api, "chart_payload", lambda *a, **k: [])
    saved = (api.State.scan, api.State.daily, api.State.result)
    try:
        api.State.daily = {"AAPL": pd.DataFrame({"close": [1.0]})}
        api.State.result = object()
        api.State.scan = [{"symbol": "AAPL", "kind": "stock"}]
        data.save_earnings([{"symbol": "AAPL", "date": "2026-10-19", "timing": "BMO"}])
        client = TestClient(api.app)
        assert client.get("/api/symbol/AAPL").json()["row"]["earnings"] is None  # 4 calendar days
        data.save_earnings([{"symbol": "AAPL", "date": "2026-10-18", "timing": "BMO"}])
        got = client.get("/api/symbol/AAPL").json()["row"]["earnings"]
        assert got == {"date": "2026-10-18", "date_end": None, "timing": "BMO", "days_until": 3}
    finally:
        api.State.scan, api.State.daily, api.State.result = saved


def test_warning_setting_is_the_shared_default():
    from strat.alerts import SETTING_LIMITS, Settings

    assert Settings().earnings_window_days == earnings.DEFAULT_WARNING_WINDOW_DAYS == 3
    assert SETTING_LIMITS["earnings_window_days"] == (0, 30)
