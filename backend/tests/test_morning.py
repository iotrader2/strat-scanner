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
    build_single_stats,
    build_stats,
    cross_through,
    ema,
    entry_at,
    first_close_above_ema,
    pick_typical_rma_first,
    rma_at,
    lod_outcome,
    outcome_for_entry,
    realized_lod_r,
    realized_pct,
    realized_return,
    session_low_through,
    single_entries_for_day,
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
    def test_a_one_percent_stop_books_minus_one_r_and_ignores_the_entry_bar(self):
        # Entry 100 at 09:45. The entry bar wicks to 98, which is not a fill.
        # 10:00 reaches 103 and stays above the stop. 10:15 trades at 99. Its 106 high does not count.
        bars = _day(
            [
                (100, 102, 98, 100),
                (100, 103, 99.5, 102),
                (102, 106, 99, 100),
            ]
        )
        daily = _daily([101, 110, 110, 110, 110, 110], start="2026-10-16")
        out = outcome_for_entry(
            entry=100,
            with_stop=True,
            day_bars=bars,
            entry_end=window_end("2026-10-16", "09:45"),
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert out["candle_low"] == pytest.approx(99)
        assert out["stopped"] == 1 and out["stop_day"] == 0 and out["gapped"] == 0
        assert out["stop_ret"] == pytest.approx(-1)
        assert out["mfe"] == pytest.approx(3)  # 103, not the 106 after the stop
        assert realized_return(out, "eod") == pytest.approx(-1)
        assert realized_return(out, "d3") == pytest.approx(-1)
        # The close is stored beside the stop. +1% on the day would have been +1R.
        assert out["eod_ret"] == pytest.approx(1)

    def test_a_bar_that_opens_through_the_stop_is_a_gap_and_still_minus_one_r(self):
        bars = _day(
            [
                (100, 101, 99.5, 100),
                (98, 98.5, 96, 97),  # opens below 99
            ]
        )
        daily = _daily([97, 110, 110, 110, 110, 110], start="2026-10-16")
        out = outcome_for_entry(
            entry=100,
            with_stop=True,
            day_bars=bars,
            entry_end=window_end("2026-10-16", "09:45"),
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert out["gapped"] == 1
        assert out["stop_ret"] == pytest.approx(-1)
        assert out["mae"] == pytest.approx(-4)  # the 96 print, not the booked R
        assert out["mfe"] == pytest.approx(0)

    def test_a_later_five_minute_bar_stops_the_hold(self):
        entry_day = _five("2026-10-16 09:30", [100.0, 100.4], low=99.5)
        # Next session opens through the stop. The daily low stays above it, so only the 5-minute bar can stop this.
        nxt = _five("2026-10-19 09:30", [98.0], low=97.0)
        bars = pd.concat([entry_day, nxt])
        idx = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])
        daily = pd.DataFrame(
            {"open": [100, 100, 100], "high": [101, 104, 101], "low": [99.5, 99.2, 99], "close": [100.4, 103, 101], "volume": 1e6},
            index=idx,
        )
        out = outcome_for_entry(
            entry=100,
            with_stop=True,
            day_bars=bars,
            entry_end=window_end("2026-10-16", "09:35"),
            daily=daily,
            entry_day=idx[0],
            forward_days=list(idx[1:]),
        )
        assert out["stop_day"] == 1 and out["gapped"] == 1
        assert out["d1_ret"] == pytest.approx(3)  # +3% close is +3R, stored beside the stop
        assert realized_return(out, "eod") == pytest.approx(out["eod_ret"])
        assert realized_return(out, "d1") == pytest.approx(-1)
        assert out["mfe"] == pytest.approx(0.8)  # the 100.8 high before the gap; the gap day's high is ignored

    def test_a_close_three_percent_higher_is_plus_three_r(self):
        bars = _five("2026-10-16 09:30", [100.0, 101.0], low=99.5)
        daily = _daily([103, 103, 103, 103, 103, 103], start="2026-10-16")
        out = outcome_for_entry(
            entry=100,
            with_stop=True,
            day_bars=bars,
            entry_end=pd.Timestamp("2026-10-16 09:35"),
            daily=daily,
            entry_day=pd.Timestamp("2026-10-16"),
            forward_days=list(daily.index[1:]),
        )
        assert out["stopped"] == 0
        assert out["eod_ret"] == pytest.approx(3)
        assert realized_return(out, "d5") == pytest.approx(3)


def test_expectancy_is_r_per_trade_and_the_average_gives_each_morning_one_vote():
    trades = [
        {"date": "2026-10-01", "window": "09:45", "stopped": 1, "stop_day": 0, "stop_ret": -1.0, "gapped": 1, "eod_ret": 5.0, "d3_ret": 9.0, "mfe": 1.5},
        {"date": "2026-10-01", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "gapped": 0, "eod_ret": 1.0, "d3_ret": 3.0, "mfe": 4.0},
        {"date": "2026-10-02", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "gapped": 0, "eod_ret": 2.0, "d3_ret": 1.0, "mfe": 2.5},
    ]
    qqq = [
        {"date": "2026-10-01", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 0.5, "d3_ret": 0.5},
        {"date": "2026-10-02", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 0.5, "d3_ret": 0.5},
    ]
    ranks = [
        {"date": "2026-10-01", "window": "09:45", "qualified": 1},
        {"date": "2026-10-01", "window": "09:45", "qualified": 1},
        {"date": "2026-10-02", "window": "09:45", "qualified": 0},
        {"date": "2026-10-02", "window": "09:45", "qualified": 0},
    ]
    stats = build_stats(trades, qqq, ranks)
    eod = stats["windows"]["09:45"]["horizons"]["eod"]
    # Day 1 is mean(−1, +1) = 0. Day 2 is +2. The morning average is 1R.
    # The three fills are −1, +1 and +2, so expectancy is +2/3 R and total R is +2.
    assert eod["avg"] == pytest.approx(1.0)
    assert eod["expectancy"] == pytest.approx(2 / 3)
    assert eod["total_r"] == pytest.approx(2)
    assert eod["n_days"] == 2
    assert eod["n_trades"] == 3
    assert eod["win_rate"] == pytest.approx(2 / 3)
    assert eod["stop_hit_rate"] == pytest.approx(1 / 3)
    assert eod["gap_count"] == 1
    assert eod["avg_mfe"] == pytest.approx((1.5 + 4.0 + 2.5) / 3)
    assert stats["best"]["window"] == "09:45"
    assert stats["best"]["gap_count"] == 1
    # Two names on the first morning and none on the second. The zero morning counts.
    assert stats["windows"]["09:45"]["avg_qualified"] == pytest.approx(1.0)
    assert stats["best"]["avg_qualified"] == pytest.approx(1.0)


def test_an_unfinished_morning_does_not_count_only_the_names_already_stopped():
    trades = [
        {"date": "2026-10-16", "window": "09:45", "stopped": 1, "stop_day": 0, "stop_ret": -1.0, "eod_ret": 0.2, "d3_ret": None, "mfe": 0.4},
        {"date": "2026-10-16", "window": "09:45", "stopped": 0, "stop_day": None, "stop_ret": None, "eod_ret": 0.5, "d3_ret": None, "mfe": 0.6},
    ]
    stats = build_stats(trades, [], [])
    assert stats["windows"]["09:45"]["horizons"]["eod"]["n_trades"] == 2
    assert stats["windows"]["09:45"]["horizons"]["d3"]["n_days"] == 0
    done = [
        {"date": "2026-10-15", "window": "09:45", "stopped": 1, "stop_day": 0, "stop_ret": -1.0, "eod_ret": -1.0, "d3_ret": None, "mfe": 0.2},
        {"date": "2026-10-15", "window": "09:45", "stopped": 1, "stop_day": 1, "stop_ret": -1.0, "eod_ret": 0.4, "d3_ret": None, "mfe": 0.5},
    ]
    both = build_stats(done, [], [])
    assert both["windows"]["09:45"]["horizons"]["d3"]["n_days"] == 1
    assert both["windows"]["09:45"]["horizons"]["d3"]["avg"] == pytest.approx(-1)


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
        with_stop=True,
        day_bars=adjusted_bars,
        entry_end=window_end("2026-10-16", "09:45"),
        daily=adjusted_daily,
        entry_day=pd.Timestamp("2026-10-16"),
        forward_days=[pd.Timestamp("2026-10-19")],
    )
    # 100 pre-split vs 25 post 4-for-1 is flat, not a 75% crash. The forward low is inside 1R.
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
    aaa = session([101.0, 101.5, 103.0, 104.0], [102.5, 102.5, 102.5, 102.5])
    bbb = session([100.0, 100.0, 102.0, 102.5], [101.5, 101.5, 101.5, 101.5])
    ccc = session([100.0, 100.0, 100.0, 100.0], [99.0, 99.0, 99.0, 99.0])
    qqq = session([100.0, 100.1, 100.2, 100.3], [99.5, 99.5, 99.5, 99.5])
    # The next session opens through AAA's 1% stop. That is day +1, and it books −1R.
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
    assert aaa_fill["candle_low"] == pytest.approx(103 * 0.99)
    assert aaa_fill["stopped"] == 1 and aaa_fill["stop_day"] == 1 and aaa_fill["gapped"] == 1
    assert aaa_fill["stop_ret"] == pytest.approx(-1)
    assert realized_return(aaa_fill, "d1") == pytest.approx(-1)
    ten = next(r for r in ranks if r["window"] == "10:00" and r["symbol"] == "CCC")
    assert ten["qualified"] == 0
    assert len(HORIZONS) == 6


def test_ema_seeds_with_the_sma_and_ignores_bars_before_945():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[0] != out[0] and out[1] != out[1]
    assert out[2] == pytest.approx(2)
    alpha = 2 / 4
    assert out[3] == pytest.approx(alpha * 4 + (1 - alpha) * 2)
    prior = _five("2026-10-15 09:30", [100.0] * 20)
    # 9:35 closes above the EMA, which is too early. 9:45 is back under it. 9:50 closes above.
    today = _five("2026-10-16 09:30", [110.0, 100.0, 100.0, 110.0])
    bars = pd.concat([prior, today])
    assert first_close_above_ema(bars, "2026-10-16") == pd.Timestamp("2026-10-16 09:50")
    already = _five("2026-10-16 09:30", [110.0, 110.0, 110.0])
    assert first_close_above_ema(pd.concat([prior, already]), "2026-10-16") == pd.Timestamp("2026-10-16 09:45")


def test_low_of_day_touch_exits_at_the_stop_and_a_gap_exits_at_the_open():
    idx = pd.to_datetime(["2026-10-16 10:30", "2026-10-16 10:35", "2026-10-16 10:40"])
    bars = pd.DataFrame(
        {"open": [100.0, 100.0, 99.5], "high": [101.0, 103.0, 110.0], "low": [98.0, 99.0, 97.0], "close": [100.0, 101.0, 99.0], "volume": 1e5},
        index=idx,
    )
    daily = _daily([101, 110, 111, 112, 113, 114], start="2026-10-16")
    out = lod_outcome(
        entry=100,
        stop=98,
        day_bars=bars,
        entry_end=pd.Timestamp("2026-10-16 10:30"),
        daily=daily,
        entry_day=pd.Timestamp("2026-10-16"),
        forward_days=list(daily.index[1:]),
    )
    assert out["stopped"] == 1 and out["stop_day"] == 0 and out["gapped"] == 0
    assert out["stop_pct"] == pytest.approx(2)
    assert out["exit_pct"] == pytest.approx(-2)
    assert out["mfe_pct"] == pytest.approx(3)
    assert out["eod_pct"] == pytest.approx(1)  # the close is stored beside the exit
    assert realized_pct(out, "d3") == pytest.approx(-2)
    assert realized_lod_r(out, "eod") == pytest.approx(-1)

    # The entry bar's low is the stop, and with no later bar it is not a fill.
    alone = bars.iloc[:1]
    held = lod_outcome(
        entry=100,
        stop=98,
        day_bars=alone,
        entry_end=pd.Timestamp("2026-10-16 10:30"),
        daily=daily,
        entry_day=pd.Timestamp("2026-10-16"),
        forward_days=[],
    )
    assert held["stopped"] == 0
    assert realized_pct(held, "eod") == pytest.approx(1)

    gap_day = pd.DataFrame(
        {"open": [95.0], "high": [110.0], "low": [90.0], "close": [96.0], "volume": 1e5},
        index=pd.to_datetime(["2026-10-17 09:35"]),
    )
    gapped = lod_outcome(
        entry=100,
        stop=98,
        day_bars=pd.concat([alone, gap_day]),
        entry_end=pd.Timestamp("2026-10-16 10:30"),
        daily=daily,
        entry_day=pd.Timestamp("2026-10-16"),
        forward_days=[pd.Timestamp("2026-10-17")],
    )
    assert gapped["gapped"] == 1 and gapped["stop_day"] == 1
    assert gapped["exit_pct"] == pytest.approx(-5)  # filled at the open, not at 90 and not at the stop
    assert realized_lod_r(gapped, "d1") == pytest.approx(-2.5)
    assert gapped["mfe_pct"] == pytest.approx(0)  # the gap bar's high is ignored


def test_single_entry_books_keep_the_first_name_and_skip_an_unfinished_morning():
    trades = [
        {"date": "2026-10-01", "rule": "rma1030", "rank": 1, "symbol": "AAA", "entry_time": "10:30", "stop_pct": 2.0, "stopped": 0, "stop_day": None, "gapped": 0, "eod_pct": 2.0, "d3_pct": 4.0, "exit_pct": None, "mfe_pct": 6.0},
        {"date": "2026-10-01", "rule": "rma1030", "rank": 2, "symbol": "BBB", "entry_time": "10:30", "stop_pct": 1.0, "stopped": 1, "stop_day": 0, "gapped": 1, "eod_pct": 9.0, "d3_pct": 9.0, "exit_pct": -3.0, "mfe_pct": 1.0},
        {"date": "2026-10-02", "rule": "rma1030", "rank": 1, "symbol": "AAA", "entry_time": "10:30", "stop_pct": 2.0, "stopped": 0, "stop_day": None, "gapped": 0, "eod_pct": 2.0, "d3_pct": None, "exit_pct": None, "mfe_pct": 2.0},
        {"date": "2026-10-02", "rule": "ema", "rank": 1, "symbol": "AAA", "entry_time": "09:50", "stop_pct": 1.0, "stopped": 0, "stop_day": None, "gapped": 0, "eod_pct": 1.0, "d3_pct": 1.0, "exit_pct": None, "mfe_pct": 2.0},
    ]
    qqq = [
        {"date": "2026-10-01", "entry_time": "10:30", "stopped": 0, "stop_day": None, "eod_pct": 0.5, "d3_pct": 0.5},
        {"date": "2026-10-02", "entry_time": "09:50", "stopped": 0, "stop_day": None, "eod_pct": 0.2, "d3_pct": 0.2},
    ]
    stats = build_single_stats(trades, qqq)
    book = stats["books"]["rma_all"]["horizons"]["d3"]
    # Day 1 is mean(+4%, −3%) and mean(+2R, −3R). Day 2 has no day-3 close and is not stopped.
    assert book["n_days"] == 1 and book["n_trades"] == 2
    assert book["avg_pct"] == pytest.approx(0.5)
    assert book["avg_r"] == pytest.approx(-0.5)
    assert book["total_r"] == pytest.approx(-1)
    assert book["expectancy"] == pytest.approx(-0.5)
    assert book["win_rate"] == pytest.approx(0.5)
    assert book["stop_hit_rate"] == pytest.approx(0.5)
    assert book["gap_count"] == 1
    assert book["best_r"] == pytest.approx(2) and book["worst_r"] == pytest.approx(-3)
    assert book["median_r"] == pytest.approx(-0.5)
    assert book["avg_mfe"] == pytest.approx(2)
    assert book["vs_qqq"] == pytest.approx(0)
    assert stats["books"]["rma_first"]["horizons"]["d3"]["n_trades"] == 1
    assert stats["books"]["rma_first"]["horizons"]["d3"]["avg_r"] == pytest.approx(2)
    assert stats["books"]["rma_all"]["avg_entry"] == "10:30"
    assert stats["books"]["rma_all"]["avg_stop_pct"] == pytest.approx(5 / 3)
    assert stats["books"]["ema_all"]["avg_entry"] == "9:50"
    assert stats["books"]["ema_all"]["median_entry"] == "9:50"
    assert stats["books"]["ema_first"]["horizons"]["d3"]["vs_qqq"] == pytest.approx(0.8)
    done = [
        {"date": "2026-10-15", "rule": "rma1030", "rank": 1, "symbol": "AAA", "entry_time": "10:30", "stop_pct": 1.0, "stopped": 1, "stop_day": 0, "gapped": 0, "eod_pct": 5.0, "d3_pct": None, "exit_pct": -1.0, "mfe_pct": 0.2},
        {"date": "2026-10-15", "rule": "rma1030", "rank": 2, "symbol": "BBB", "entry_time": "10:30", "stop_pct": 2.0, "stopped": 1, "stop_day": 1, "gapped": 0, "eod_pct": 0.4, "d3_pct": None, "exit_pct": -2.0, "mfe_pct": 0.4},
    ]
    both = build_single_stats(done, [])
    assert both["books"]["rma_all"]["horizons"]["d3"]["n_days"] == 1
    assert both["books"]["rma_all"]["horizons"]["d3"]["avg_r"] == pytest.approx(-1)


def test_the_ema_entry_is_not_the_1030_close_and_the_first_name_is_the_earliest():
    prior = _five("2026-10-15 09:30", [100.0] * 25, low=90.0)
    # 12 bars: 9:35 through 10:30. AAA is above the average at 9:45. BBB waits until 10:15.
    # A lower low at 10:05 widens the 10:30 stop and is invisible to an entry at 9:45.
    aaa_today = _five("2026-10-16 09:30", [100.0, 100.0, 102.0, 102.0, 102.0, 102.0, 102.0, 102.0, 102.0, 102.0, 102.0, 104.0])
    aaa_today["low"] = 99.0
    aaa_today.iloc[6, aaa_today.columns.get_loc("low")] = 96.0
    bbb_today = _five("2026-10-16 09:30", [100.0] * 8 + [103.0, 103.0, 103.0, 105.0])
    bbb_today["low"] = 100.0
    calendar = ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
    daily = {sym: _daily([100, 101, 102, 103, 104, 105], start="2026-10-16") for sym in ("AAA", "BBB", "QQQ")}
    leaders, qqq = single_entries_for_day(
        "2026-10-16",
        ["AAA", "BBB"],
        {"AAA": pd.concat([prior, aaa_today]), "BBB": pd.concat([prior, bbb_today]), "QQQ": pd.concat([prior, _five("2026-10-16 09:30", [100.0] * 12)])},
        daily,
        calendar,
    )
    rma = [row for row in leaders if row["rule"] == "rma1030"]
    ema_rows = [row for row in leaders if row["rule"] == "ema"]
    assert [row["symbol"] for row in rma] == ["AAA", "BBB"]
    assert all(row["entry_time"] == "10:30" for row in rma)
    assert rma[0]["entry_price"] == pytest.approx(104)
    assert rma[0]["stop_price"] == pytest.approx(96)
    assert [row["symbol"] for row in ema_rows] == ["AAA", "BBB"]
    assert ema_rows[0]["entry_time"] == "09:45"
    assert ema_rows[0]["entry_price"] == pytest.approx(102)
    assert ema_rows[0]["stop_price"] == pytest.approx(99)
    assert ema_rows[1]["entry_time"] == "10:15"
    assert {row["entry_time"] for row in qqq} >= {"10:30", "09:45", "10:15"}


def _rma_fill(symbol, rank, cross, pct, stop_pct=1.0, stopped=0, stop_day=None, exit_pct=None):
    return {
        "date": "2026-10-01",
        "rule": "rma1030",
        "rank": rank,
        "symbol": symbol,
        "entry_time": "10:30",
        "cross_time": cross,
        "stop_pct": stop_pct,
        "stopped": stopped,
        "stop_day": stop_day,
        "gapped": 0,
        "eod_pct": pct,
        "d3_pct": pct,
        "d5_pct": pct,
        "exit_pct": exit_pct,
        "mfe_pct": 1.0,
    }


def test_rma_caps_use_leader_rank_and_keep_the_symbol_first_when_it_differs():
    trades = [
        _rma_fill("AAA", 1, "09:35", 2.0),
        _rma_fill("BBB", 2, "09:35", -1.0, stopped=1, stop_day=0, exit_pct=-1.0),
        _rma_fill("CCC", 3, "10:00", 3.0),
    ]
    stats = build_single_stats(trades, [], {"2026-10-01": {"AAA": 8, "BBB": 1, "CCC": 4}})
    assert stats["rank_tie_mornings"] == 1
    assert stats["caps"] == ["rma_first", "rma_first_rank", "rma_two", "rma_three", "rma_all"]
    assert stats["books"]["rma_first"]["horizons"]["d3"]["avg_r"] == pytest.approx(2)
    assert stats["books"]["rma_first_rank"]["horizons"]["d3"]["avg_r"] == pytest.approx(-1)
    # Same minute: BBB (leader rank 1) then AAA (leader rank 8). CCC crossed later.
    two = stats["books"]["rma_two"]["horizons"]["d3"]
    assert two["n_trades"] == 2 and two["avg_r"] == pytest.approx(0.5) and two["expectancy"] == pytest.approx(0.5)
    three = stats["books"]["rma_three"]["horizons"]["d3"]
    assert three["n_trades"] == 3 and three["avg_r"] == pytest.approx((2 - 1 + 3) / 3)
    assert "different first name" in stats["caps_note"]


def test_rank_tie_is_omitted_when_the_first_name_does_not_change():
    trades = [
        _rma_fill("BBB", 1, "09:35", 2.0),
        _rma_fill("AAA", 2, "09:40", 1.0),
    ]
    stats = build_single_stats(trades, [], {"2026-10-01": {"BBB": 5, "AAA": 1}})
    assert stats["rank_tie_mornings"] == 0
    assert "rma_first_rank" not in stats["books"]
    assert stats["caps"] == ["rma_first", "rma_two", "rma_three", "rma_all"]
    assert stats["books"]["rma_two"]["horizons"]["d3"]["n_trades"] == 2
    assert "same first name" in stats["caps_note"]


def test_typical_first_morning_is_recent_and_not_the_best_fill():
    def row(day, pct):
        return {
            "date": day, "rule": "rma1030", "rank": 1, "symbol": "AAA", "stop_pct": 1.0,
            "stopped": 0, "stop_day": None, "d3_pct": pct, "d5_pct": pct, "exit_pct": None,
        }

    picked = pick_typical_rma_first([
        row("2026-07-31", 20.0),
        row("2026-10-01", -1.0),
        row("2026-10-02", 4.0),
        row("2026-10-09", -1.0),
    ])
    assert picked["row"]["date"] == "2026-10-09"
    assert picked["best_date"] == "2026-07-31"
    assert picked["best_r"] == pytest.approx(20)
    assert picked["median_r"] == pytest.approx(-1)


def test_rma_at_reports_the_average_on_the_crossing_bar():
    prior = _five("2026-10-15 09:30", [10.0] * 3)
    today = _five("2026-10-16 09:30", [13.0, 13.0])
    found = rma_at(pd.concat([prior, today]), pd.Timestamp("2026-10-16 10:30"), length=3)
    assert found is not None
    ts, close, value = found
    assert ts == pd.Timestamp("2026-10-16 09:35")
    assert close == pytest.approx(13)
    # The seed is the SMA of the three prior closes. This bar updates it before the comparison.
    assert value == pytest.approx((13 + 20) / 3)
