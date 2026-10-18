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
    build_stats,
    cross_through,
    entry_at,
    outcome_for_entry,
    realized_return,
    session_low_through,
    wilder_rma,
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


def _five(start: str, closes: list[float], low: float | None = None) -> pd.DataFrame:
    """5-minute bars indexed by bar end. ``start`` is the first bar's open."""
    idx = pd.date_range(start, periods=len(closes), freq="5min") + pd.Timedelta(minutes=5)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.4 for c in closes],
            "low": [low if low is not None else c - 0.4 for c in closes],
            "close": closes,
            "volume": 1e5,
        },
        index=idx,
    )


class TestRmaQualification:
    def test_wilder_rma_seeds_with_the_sma_then_smooths(self):
        out = wilder_rma([1, 2, 3, 4, 5], 3)
        assert out[0] != out[0] and out[1] != out[1]
        assert out[2] == pytest.approx(2)
        assert out[3] == pytest.approx((4 + 2 * 2) / 3)
        assert out[4] == pytest.approx((5 + 2 * out[3]) / 3)
        assert all(value != value for value in wilder_rma([1, 2], 20))

    def test_a_prior_close_above_the_average_is_not_todays_cross(self):
        prior = _five("2026-10-15 09:30", [100.0] * 20 + [110.0])
        today = _five("2026-10-16 09:30", [100.0, 100.0, 101.0])
        bars = pd.concat([prior, today])
        # Yesterday's 110 is above the average. Today's first two closes are not, so 9:40 has no cross.
        assert cross_through(bars, window_end("2026-10-16", "09:40")) is None
        assert cross_through(bars, window_end("2026-10-16", "09:45")) == window_end("2026-10-16", "09:45")

    def test_close_must_be_strictly_above_and_a_later_cross_is_invisible_early(self):
        prior = _five("2026-10-15 09:30", [100.0] * 20)
        flat = _five("2026-10-16 09:30", [100.0, 100.0, 100.0])
        bars = pd.concat([prior, flat])
        assert cross_through(bars, window_end("2026-10-16", "09:45")) is None
        popped = flat.copy()
        popped.iloc[-1, popped.columns.get_loc("close")] = 100.01
        later = pd.concat([prior, popped])
        assert cross_through(later, window_end("2026-10-16", "09:40")) is None
        assert cross_through(later, window_end("2026-10-16", "09:45")) == pd.Timestamp("2026-10-16 09:45")

    def test_entry_is_the_check_in_close_and_the_stop_is_todays_low(self):
        prior = _five("2026-10-15 09:30", [100.0] * 20, low=50.0)
        today = _five("2026-10-16 09:30", [101.0, 101.5, 103.0, 104.0], low=97.0)
        today.iloc[0, today.columns.get_loc("low")] = 98.0
        bars = pd.concat([prior, today])
        end = window_end("2026-10-16", "09:45")
        assert cross_through(bars, end) == pd.Timestamp("2026-10-16 09:35")
        assert entry_at(bars, end) == pytest.approx(103.0)
        assert session_low_through(bars, end) == pytest.approx(97.0)
        assert entry_at(bars, window_end("2026-10-16", "10:15")) is None


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

    def test_the_stop_is_the_low_of_day_through_the_entry_candle(self):
        # 9:45 prints 97. The 10:00 candle's own low is 99. The stop is 97, not 99.
        bars = _day(
            [
                (100, 101, 97, 100.5),
                (100.5, 103, 99, 102),
                (102, 104, 98, 103),  # below the entry candle, still above the low of day
                (103, 105, 96.5, 104),  # trades below 97. High 105 does not count.
            ]
        )
        end = window_end("2026-10-16", "10:00")
        assert float(bars.loc[end].low) == pytest.approx(99)
        assert session_low_through(bars, end) == pytest.approx(97)
        daily = _daily([104, 110, 110, 110, 110, 110], start="2026-10-16")
        held = outcome_for_entry(
            entry=102,
            stop=97,
            day_bars=bars.iloc[:3],
            entry_end=end,
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert held["stopped"] == 0
        # Touching 97 again is not below the low of day.
        touched = bars.iloc[:3].copy()
        touched.iloc[-1, touched.columns.get_loc("low")] = 97
        still = outcome_for_entry(
            entry=102,
            stop=97,
            day_bars=touched,
            entry_end=end,
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert still["stopped"] == 0
        broken = outcome_for_entry(
            entry=102,
            stop=97,
            day_bars=bars,
            entry_end=end,
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert broken["stopped"] == 1 and broken["stop_day"] == 0
        assert broken["stop_ret"] == pytest.approx((97 / 102 - 1) * 100)
        assert broken["mfe"] == pytest.approx((104 / 102 - 1) * 100)
        assert broken["eod_ret"] == pytest.approx((104 / 102 - 1) * 100)


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
    ranks = [
        {"date": "2026-10-01", "window": "09:45", "qualified": 1},
        {"date": "2026-10-01", "window": "09:45", "qualified": 1},
        {"date": "2026-10-02", "window": "09:45", "qualified": 0},
        {"date": "2026-10-02", "window": "09:45", "qualified": 0},
    ]
    stats = build_stats(trades, qqq, ranks)
    eod = stats["windows"]["09:45"]["horizons"]["eod"]
    # Day 1 basket is mean(-2, +1) = -0.5. Day 2 is +2. Mean expectancy -0.5 and +2 → 0.75.
    assert eod["expectancy"] == pytest.approx(0.75)
    assert eod["avg"] == pytest.approx(2.5)  # close-to-close, the stop does not replace it
    assert eod["n_days"] == 2
    assert eod["win_rate"] == pytest.approx(1.0)
    assert eod["stop_hit_rate"] == pytest.approx(1 / 3)  # one of the three resolved fills
    assert stats["best"]["window"] == "09:45"
    # Two names on the first morning and none on the second. The zero morning counts.
    assert stats["windows"]["09:45"]["avg_qualified"] == pytest.approx(1.0)
    assert stats["best"]["avg_qualified"] == pytest.approx(1.0)


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


def test_a_one_symbol_yahoo_frame_still_has_price_columns():
    from strat.intraday import _symbol_frame

    columns = pd.MultiIndex.from_tuples([("QQQ", "Open"), ("QQQ", "High"), ("QQQ", "Low"), ("QQQ", "Close"), ("QQQ", "Volume")])
    frame = pd.DataFrame([[1, 2, 0.5, 1.5, 10]], columns=columns)
    unpacked = _symbol_frame(frame, "QQQ", True)
    assert list(unpacked.columns) == ["Open", "High", "Low", "Close", "Volume"]


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
    five = pd.date_range("2026-10-16 09:25", periods=4, freq="5min")
    five_frame = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}, index=five)
    assert list(to_session_ends(five_frame, 5).index.strftime("%H:%M")) == ["09:35", "09:40", "09:45"]
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
        [
            {
                "window": "10:15",
                "rank": 1,
                "symbol": "NVDA",
                "score": 0,
                "day_move": None,
                "vs_qqq": None,
                "or_position": None,
                "qualified": 1,
                "cross_time": "09:40",
            },
            {
                "window": "09:45",
                "rank": 100,
                "symbol": "NVDA",
                "score": 0,
                "day_move": None,
                "vs_qqq": None,
                "or_position": None,
                "qualified": 0,
                "cross_time": None,
            },
        ],
        db,
    )
    body = week_payload("2026-10-16")
    assert body["week_of"] == "2026-10-12"
    assert body["title"] == "Week of Oct 12, 2026"
    friday = body["days"][4]
    assert friday["weekday"] == "FRI" and friday["rows"][0]["symbol"] == "NVDA"
    assert friday["rows"][0]["windows"]["10:15"]["d3_ret"] == pytest.approx(2.5)
    assert friday["rows"][0]["windows"]["10:15"]["rank"] == 1
    assert friday["rows"][0]["windows"]["10:15"]["cross_time"] == "09:40"
    assert friday["rows"][0]["windows"]["09:45"]["qualified"] == 0
    assert friday["rows"][0]["windows"]["09:45"]["rank"] is None
    client = TestClient(__import__("strat.api", fromlist=["app"]).app)
    res = client.get("/api/morning", params={"week": "2026-10-12"})
    assert res.status_code == 200
    assert res.json()["days"][4]["rows"][0]["symbol"] == "NVDA"
    assert "localhost" not in res.text.lower()


def test_compute_day_buys_the_earliest_cross_and_skips_the_rest():
    prior = _five("2026-10-15 09:30", [100.0] * 25, low=50.0)

    def session(closes: list[float], lows: list[float]) -> pd.DataFrame:
        frame = _five("2026-10-16 09:30", closes)
        frame["low"] = lows
        return pd.concat([prior, frame])

    # AAA closes above the average at 09:35. BBB waits until 09:45. CCC never does.
    aaa = session([101.0, 101.5, 103.0, 104.0], [98.0, 97.5, 97.0, 99.0])
    bbb = session([100.0, 100.0, 102.0, 102.5], [99.0, 99.0, 99.0, 99.0])
    ccc = session([100.0, 100.0, 100.0, 100.0], [99.0, 99.0, 99.0, 99.0])
    qqq = session([100.0, 100.1, 100.2, 100.3], [99.5, 99.5, 99.5, 99.5])
    # A later session's 5-minute low must not be walked as if it were today.
    spike = _five("2026-10-19 09:30", [90.0], low=40.0)
    aaa = pd.concat([aaa, spike])
    calendar = ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
    daily = {
        "AAA": _daily([103, 110, 111, 112, 113, 114], start="2026-10-16"),
        "BBB": _daily([102, 108, 109, 110, 111, 112], start="2026-10-16"),
        "CCC": _daily([100, 100, 100, 100, 100, 100], start="2026-10-16"),
        "QQQ": _daily([100, 101, 102, 103, 104, 105], start="2026-10-16"),
    }
    ranks, leaders, benchmarks = compute_day(
        "2026-10-16",
        ["AAA", "BBB", "CCC", "MISSING"],
        {"AAA": aaa, "BBB": bbb, "CCC": ccc, "QQQ": qqq},
        daily,
        calendar,
    )
    assert all(r["window"] != "open" for r in (*ranks, *leaders, *benchmarks))
    nine = [r for r in ranks if r["window"] == "09:45"]
    bought = [r for r in nine if r["qualified"]]
    skipped = [r for r in nine if not r["qualified"]]
    assert [r["symbol"] for r in bought] == ["AAA", "BBB"]
    assert bought[0]["cross_time"] == "09:35"
    assert bought[1]["cross_time"] == "09:45"
    assert {r["symbol"] for r in skipped} == {"CCC", "MISSING"}
    assert all(r["rank"] >= 100 for r in skipped)
    assert {r["symbol"] for r in leaders if r["window"] == "09:45"} == {"AAA", "BBB"}
    aaa_fill = next(r for r in leaders if r["window"] == "09:45" and r["symbol"] == "AAA")
    assert aaa_fill["entry_price"] == pytest.approx(103.0)
    assert aaa_fill["candle_low"] == pytest.approx(97.0)
    assert aaa_fill["stopped"] == 0
    ten = next(r for r in ranks if r["window"] == "10:00" and r["symbol"] == "CCC")
    assert ten["qualified"] == 0
    assert len(HORIZONS) == 6
