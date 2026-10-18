"""Morning check-ins: no lookahead in the rank, stop and excursion math, idempotent storage."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import config, data
from strat.backtest import _as_of_frames
from strat.intraday import clamp_start, to_session_ends
from strat.morning import (
    HORIZONS,
    IntervalWeights,
    bars_through,
    build_stats,
    interval_features,
    interval_score,
    outcome_for_entry,
    rank_at_window,
    realized_return,
    window_end,
)
from strat.morning_api import monday_of, week_payload
from strat.morning_collect import (
    compute_day,
    dates_in_window,
    leaders_on,
    session_is_complete,
    top_leaders,
    upcoming_session,
)
from strat.morning_store import replace_leaders, replace_results, save_bars
from strat.scanner import scan_all
from strat.universe import Member

ET = ZoneInfo("America/New_York")


def _day(start_prices, end="2026-10-16"):
    """15-minute bars for one session. start_prices is (open, high, low, close) per bar from 09:30."""
    idx = pd.date_range(f"{end} 09:30", periods=len(start_prices), freq="15min")
    # Stored bars are indexed by their END, which is what the ranker reads.
    idx = idx + pd.Timedelta(minutes=15)
    rows = [{"open": o, "high": h, "low": l, "close": c, "volume": 1e5} for o, h, l, c in start_prices]
    return pd.DataFrame(rows, index=idx)


def _daily(closes, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close - 0.2, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 2_000_000.0}
    )


class TestCheckInScore:
    def test_a_later_bar_cannot_change_the_945_rank(self):
        # At 9:45 A is the stronger open. By 10:00 B has run past it. The 9:45 rank must not see that.
        a = _day([(100, 101, 99.5, 100.8), (100.8, 101, 100.4, 100.6)])
        b = _day([(100, 100.4, 99.8, 100.1), (100.1, 104, 100, 103.5)])
        qqq = _day([(100, 100.2, 99.9, 100.1), (100.1, 100.3, 100, 100.2)])
        end = window_end("2026-10-16", "09:45")
        assert bars_through(b, end).index.max() == end
        early = rank_at_window(
            {"A": interval_features(a, qqq, end), "B": interval_features(b, qqq, end)}
        )
        later = rank_at_window(
            {
                "A": interval_features(a, qqq, window_end("2026-10-16", "10:00")),
                "B": interval_features(b, qqq, window_end("2026-10-16", "10:00")),
            }
        )
        assert [r["symbol"] for r in early] == ["A", "B"]
        assert [r["symbol"] for r in later] == ["B", "A"]
        # The 9:45 features are exactly the first candle, not the second.
        feat = interval_features(a, qqq, end)
        assert feat["entry_price"] == pytest.approx(100.8)
        assert feat["candle_low"] == pytest.approx(99.5)

    def test_weights_are_applied_and_a_missing_qqq_adds_nothing(self):
        features = {"day_move": 2.0, "vs_qqq": 1.0, "or_position": 1.0}
        assert interval_score(features, IntervalWeights(1, 1, 1)) == pytest.approx(2 + 1 + 1)
        assert interval_score(features, IntervalWeights(0, 0, 2)) == pytest.approx(2)
        bare = dict(features, vs_qqq=None)
        assert interval_score(bare, IntervalWeights()) == pytest.approx(2 + 0 + 1)

    def test_ties_break_by_symbol(self):
        feat = {"day_move": 1.0, "vs_qqq": 0.0, "or_position": 0.5, "entry_price": 1, "candle_low": 1, "candle_high": 1}
        ranked = rank_at_window({"ZZ": feat, "AA": dict(feat)})
        assert [r["symbol"] for r in ranked] == ["AA", "ZZ"]
        assert [r["rank"] for r in ranked] == [1, 2]


class TestOutcomes:
    def test_the_entry_candle_is_not_a_stop_and_a_later_bar_is(self):
        bars = _day(
            [
                (100, 102, 99, 101),  # ends 09:45, entry 101, stop 99. Its own low is not a fill.
                (101, 103, 100, 102),  # 10:00, still alive; high 103 counts.
                (102, 106, 98, 99),  # 10:15, trades through the stop. High 106 does not count.
            ]
        )
        daily = _daily([101, 110, 110, 110, 110, 110], start="2026-10-16")
        out = outcome_for_entry(
            entry=101,
            stop=99,
            day_bars=bars,
            entry_end=window_end("2026-10-16", "09:45"),
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert out["stopped"] == 1 and out["stop_day"] == 0
        assert out["stop_ret"] == pytest.approx((99 / 101 - 1) * 100)
        assert out["mfe"] == pytest.approx((103 / 101 - 1) * 100)
        assert out["mae"] == pytest.approx((99 / 101 - 1) * 100)
        # The close return is stored beside the stop, not replaced by it.
        assert out["eod_ret"] == pytest.approx(0, abs=1e-9)
        assert realized_return(out, "eod") == pytest.approx(out["stop_ret"])

    def test_a_later_day_stops_on_the_daily_low_and_ignores_that_days_high(self):
        bars = _day([(100, 101, 99.5, 100.5)])
        # entry day close 100.5, next day low 98 (through the 99.5 stop) but high 120.
        idx = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])
        daily = pd.DataFrame(
            {"open": [100, 100, 100], "high": [101, 120, 101], "low": [99.5, 98, 99], "close": [100.5, 110, 101], "volume": 1e6},
            index=idx,
        )
        out = outcome_for_entry(
            entry=100.5,
            stop=99.5,
            day_bars=bars,
            entry_end=window_end("2026-10-16", "09:45"),
            daily=daily,
            entry_day=idx[0],
            forward_days=list(idx[1:]),
        )
        assert out["stop_day"] == 1
        assert out["mfe"] == pytest.approx(0, abs=1e-9)  # nothing after entry made a new high before the stop
        assert out["d1_ret"] == pytest.approx((110 / 100.5 - 1) * 100)
        assert realized_return(out, "d1") == pytest.approx(out["stop_ret"])
        assert realized_return(out, "eod") == pytest.approx(out["eod_ret"])

    def test_open_benchmark_has_no_stop_and_uses_the_first_open(self):
        bars = _day([(50, 52, 49, 51), (51, 53, 50, 52)])
        daily = _daily([51, 55], start="2026-10-16")
        from strat.morning import open_entry

        assert open_entry(bars, daily, pd.Timestamp("2026-10-16")) == pytest.approx(50)
        out = outcome_for_entry(
            entry=50,
            stop=None,
            day_bars=bars,
            entry_end=None,
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=[pd.Timestamp("2026-10-19")],
        )
        assert out["stopped"] == 0 and out["stop_ret"] is None
        # The next session's high is part of the excursion. close 55, high is one point above it.
        assert out["mfe"] == pytest.approx((56 / 50 - 1) * 100)
        assert out["d1_ret"] == pytest.approx((55 / 50 - 1) * 100)


def test_expectancy_uses_the_stop_and_each_morning_weighs_the_same():
    trades = [
        {"date": "2026-10-01", "window": "09:45", "stopped": 1, "stop_day": 0, "stop_ret": -2.0, "eod_ret": 5.0, "d3_ret": 9.0},
        {"date": "2026-10-01", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 1.0, "d3_ret": 3.0},
        {"date": "2026-10-02", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 2.0, "d3_ret": 1.0},
    ]
    qqq = [
        {"date": "2026-10-01", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 0.5, "d3_ret": 0.5},
        {"date": "2026-10-02", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 0.5, "d3_ret": 0.5},
    ]
    # Pad the other windows so build_stats has the keys. Empty windows are fine.
    stats = build_stats(trades, qqq, IntervalWeights())
    eod = stats["windows"]["09:45"]["horizons"]["eod"]
    # Day 1 basket is mean(-2, +1) = -0.5. Day 2 is +2. Mean expectancy -0.5 and +2 → 0.75.
    assert eod["expectancy"] == pytest.approx(0.75)
    assert eod["avg"] == pytest.approx(2.5)  # close-to-close, the stop does not replace it
    assert eod["n_days"] == 2
    assert eod["win_rate"] == pytest.approx(1.0)
    assert eod["stop_hit_rate"] == pytest.approx(1 / 3)  # one of the three resolved fills
    assert stats["best"]["window"] == "09:45"


def _trend(drift, n=280, jump=0.0):
    idx = pd.bdate_range(end="2026-10-15", periods=n)
    close = pd.Series([100 * (1 + drift) ** i for i in range(n)], index=idx, dtype=float)
    if jump:
        close.iloc[-1] = close.iloc[-2] * (1 + jump)
    return pd.DataFrame(
        {"open": close * 0.99, "high": close * 1.01, "low": close * 0.98, "close": close, "volume": 2_000_000.0}
    )


def test_leaders_for_a_session_use_only_the_prior_close(monkeypatch):
    monkeypatch.setattr(config, "MIN_PRICE", 1)
    monkeypatch.setattr(config, "MIN_DOLLAR_VOLUME", 1)
    symbols = [f"S{i:02d}" for i in range(11)] + ["POP"]
    frames = {sym: _trend(0.001 + i * 0.00015) for i, sym in enumerate(symbols) if sym != "POP"}
    frames["POP"] = _trend(0.0012, jump=0.45)
    frames["QQQ"] = _trend(0.0004)
    members = [Member(s, s, "Information Technology", "stock", "SP500") for s in symbols] + [
        Member("QQQ", "Invesco QQQ", "Index", "etf", "MARKET")
    ]
    calendar = [ts.strftime("%Y-%m-%d") for ts in frames["QQQ"].index]
    last = calendar[-1]
    prior = calendar[-2]
    rows = leaders_on(last, members, frames, {}, None, calendar)
    assert rows and all(r["as_of"] == prior for r in rows)
    direct = top_leaders(scan_all(members, _as_of_frames(frames, pd.Timestamp(prior), {}), None, changes=False).rows)
    leaked = top_leaders(scan_all(members, _as_of_frames(frames, pd.Timestamp(last), {}), None, changes=False).rows)
    assert [r["symbol"] for r in rows] == [r["symbol"] for r in direct]
    assert [r["symbol"] for r in direct] != [r["symbol"] for r in leaked]
    nxt = "2026-10-16"
    after = leaders_on(nxt, members, frames, {}, None, calendar)
    assert after[0]["as_of"] == last
    assert after[0]["symbol"] == "POP"


def test_storage_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    replace_leaders("2026-10-16", [{"rank": 1, "symbol": "AAA", "score": 80, "rs": 0.95, "name": "Aaa", "as_of": "2026-10-15"}], db)
    replace_leaders("2026-10-16", [{"rank": 1, "symbol": "BBB", "score": 70, "rs": 0.91, "name": "Bbb", "as_of": "2026-10-15"}], db)
    with data.connect(db) as conn:
        rows = conn.execute("SELECT symbol FROM leader_snapshots WHERE date = '2026-10-16'").fetchall()
    assert rows == [("BBB",)]
    bars = _day([(10, 11, 9, 10.5)])
    assert save_bars("BBB", bars, "15m", "yahoo", db) == 1
    assert save_bars("BBB", bars, "15m", "yahoo", db) == 1
    with data.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM intraday_bars").fetchone()[0] == 1


def test_yahoo_requests_stay_inside_the_60_day_window():
    today = date(2026, 10, 18)
    assert clamp_start(date(2026, 1, 1), today, 59, today) == date(2026, 8, 20)
    assert clamp_start(date(2026, 10, 1), today, 59, today) == date(2026, 10, 1)
    assert clamp_start(date(2026, 10, 19), date(2026, 10, 18), 59, today) is None


def test_bar_ends_are_the_regular_session_in_new_york():
    start = pd.date_range("2026-10-16 09:30", periods=3, freq="15min")
    start = start.append(pd.DatetimeIndex([pd.Timestamp("2026-10-16 08:00")]))
    frame = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}, index=start)
    ends = to_session_ends(frame)
    assert list(ends.index.strftime("%H:%M")) == ["09:45", "10:00", "10:15"]
    utc = pd.DataFrame(
        {"open": [100], "high": [101], "low": [99], "close": [100.5], "volume": [5]},
        index=pd.to_datetime(["2026-10-16T13:30:00Z"]),
    )
    assert to_session_ends(utc).index[0].strftime("%Y-%m-%d %H:%M") == "2026-10-16 09:45"


def test_a_split_inside_the_hold_is_not_a_crash():
    from strat.adjust import apply_splits

    idx = pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"])
    raw = pd.DataFrame(
        {"open": [100, 100, 25], "high": [101, 102, 26], "low": [99, 99, 24.9], "close": [100, 100, 25], "volume": [1e6, 1e6, 4e6]},
        index=idx,
    )
    bars = _day([(100, 102, 99.5, 100)], end="2026-10-16")
    adjusted_daily = apply_splits(raw, [("2026-10-19", 4.0)], "2026-10-19")
    adjusted_bars = apply_splits(bars, [("2026-10-19", 4.0)], "2026-10-19")
    out = outcome_for_entry(
        entry=float(adjusted_bars.iloc[0].close),
        stop=float(adjusted_bars.iloc[0].low),
        day_bars=adjusted_bars,
        entry_end=window_end("2026-10-16", "09:45"),
        daily=adjusted_daily,
        entry_day=pd.Timestamp("2026-10-16"),
        forward_days=[pd.Timestamp("2026-10-19")],
    )
    # 101 pre-split vs 25 post 4-for-1 is flat, not a 75% crash. No later bar trades the stop.
    assert out["d1_ret"] == pytest.approx(0, abs=0.05)
    assert out["stopped"] == 0


def test_window_helpers_and_the_week_route(tmp_path, monkeypatch):
    # The first session in the calendar has no prior close. A later window keeps its first day.
    assert dates_in_window(["2026-10-14", "2026-10-15", "2026-10-16"], 12, date(2026, 10, 18)) == [
        "2026-10-15",
        "2026-10-16",
    ]
    assert dates_in_window(["2025-01-02", "2026-10-15", "2026-10-16"], 12, date(2026, 10, 18)) == [
        "2026-10-15",
        "2026-10-16",
    ]
    assert upcoming_session(["2026-10-16"], date(2026, 10, 18)) == "2026-10-19"
    assert upcoming_session(["2026-10-16"], date(2026, 10, 20)) is None
    assert session_is_complete("2026-10-16", date(2026, 10, 18))
    assert not session_is_complete("2026-10-19", date(2026, 10, 19), datetime(2026, 10, 19, 10, 0, tzinfo=ET))
    assert monday_of(date(2026, 10, 18)) == date(2026, 10, 12)

    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    replace_leaders(
        "2026-10-16",
        [{"rank": 1, "symbol": "NVDA", "score": 88.2, "rs": 0.97, "name": "NVIDIA", "as_of": "2026-10-15"}],
        db,
    )
    replace_results(
        "2026-10-16",
        [
            {
                "symbol": "NVDA",
                "window": "10:15",
                "entry_price": 190,
                "candle_low": 188,
                "eod_ret": 1.2,
                "d1_ret": 0.4,
                "d2_ret": None,
                "d3_ret": 2.5,
                "d4_ret": None,
                "d5_ret": None,
                "stopped": 0,
                "stop_day": None,
                "stop_ret": None,
                "mfe": 3.0,
                "mae": -0.5,
            }
        ],
        role="leader",
        db_path=db,
    )
    from strat.morning_store import replace_ranks

    replace_ranks(
        "2026-10-16",
        [{"window": "10:15", "rank": 1, "symbol": "NVDA", "score": 2.4, "day_move": 1.5, "vs_qqq": 0.8, "or_position": 0.9}],
        db,
    )
    body = week_payload("2026-10-16")
    assert body["week_of"] == "2026-10-12"
    assert body["title"] == "Week of Oct 12, 2026"
    friday = body["days"][4]
    assert friday["weekday"] == "FRI" and friday["rows"][0]["symbol"] == "NVDA"
    assert friday["rows"][0]["windows"]["10:15"]["d3_ret"] == pytest.approx(2.5)
    client = TestClient(__import__("strat.api", fromlist=["app"]).app)
    res = client.get("/api/morning", params={"week": "2026-10-12"})
    assert res.status_code == 200
    assert res.json()["days"][4]["rows"][0]["symbol"] == "NVDA"
    assert "localhost" not in res.text.lower()


def test_compute_day_ranks_only_names_with_a_candle():
    a = _day([(100, 102, 99, 101), (101, 103, 100, 102)])
    qqq = _day([(100, 100.5, 99.8, 100.2), (100.2, 100.6, 100, 100.4)])
    daily = {
        "AAA": _daily([101, 104, 106, 103, 108, 110], start="2026-10-16"),
        "QQQ": _daily([100, 101, 102, 103, 104, 105], start="2026-10-16"),
    }
    ranks, leaders, benchmarks = compute_day(
        "2026-10-16",
        ["AAA", "MISSING"],
        {"AAA": a, "QQQ": qqq},
        daily,
        ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"],
        IntervalWeights(),
    )
    assert {r["symbol"] for r in ranks} == {"AAA"}
    assert any(r["window"] == "09:45" and r["symbol"] == "AAA" for r in leaders)
    assert any(r["symbol"] == "QQQ" and r["window"] == "open" for r in benchmarks)
    assert len(HORIZONS) == 6
