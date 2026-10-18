"""15- and 30-minute Strat reversals: aggregation, the four patterns, the intrabar stop."""

from datetime import time

import pandas as pd
import pytest

from strat import config, data
from strat.candles import INSIDE, OUTSIDE, TWO_DOWN, TWO_UP
from strat.morning import realized_lod_r
from strat.morning_store import delete_day, replace_strat_reversals, revision, strat_reversals_between
from strat.strat_reversal import (
    aggregate_bars,
    build_reversal_stats,
    first_reversal,
    reversal_kind,
    strat_reversals_for_day,
)


def _session(day: str, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(f"{day} 09:30", periods=78, freq="5min") + pd.Timedelta(minutes=5)
    frame = pd.DataFrame(
        {"open": price, "high": price + 1.0, "low": price - 1.0, "close": price, "volume": 1.0},
        index=idx,
    )
    return frame.astype(float)


def _at(frame: pd.DataFrame, ts: str, **cols) -> None:
    frame.loc[pd.Timestamp(ts), list(cols)] = list(cols.values())


def _daily(day: str = "2026-10-16") -> dict[str, pd.DataFrame]:
    idx = pd.bdate_range(day, periods=6)
    close = pd.Series([101.0, 102.0, 103.0, 104.0, 105.0, 106.0], index=idx)
    frame = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e6},
        index=idx,
    )
    return {"AAA": frame, "BBB": frame, "QQQ": frame}


def test_five_minute_bars_aggregate_onto_the_930_grid():
    bars = _session("2026-10-16", 100)
    _at(bars, "2026-10-16 09:35", open=10, high=12, low=9, close=11)
    _at(bars, "2026-10-16 09:40", open=11, high=13, low=8, close=10)
    _at(bars, "2026-10-16 09:45", open=10, high=11, low=9.5, close=10.5)
    fifteen = aggregate_bars(bars, 15)
    thirty = aggregate_bars(bars, 30)
    assert len(fifteen) == 26 and len(thirty) == 13
    first = fifteen[0]
    assert first.end == pd.Timestamp("2026-10-16 09:45")
    assert first.start == pd.Timestamp("2026-10-16 09:30")
    assert (first.open, first.high, first.low, first.close) == (10, 13, 8, 10.5)
    assert thirty[0].end == pd.Timestamp("2026-10-16 10:00")
    assert thirty[0].start == pd.Timestamp("2026-10-16 09:30")
    assert thirty[1].start == pd.Timestamp("2026-10-16 10:00")
    # A short group is not a candle. Drop the 10:10 bar and that 15-minute candle disappears.
    broken = bars.drop(pd.Timestamp("2026-10-16 10:10"))
    ends = [candle.end for candle in aggregate_bars(broken, 15)]
    assert pd.Timestamp("2026-10-16 10:15") not in ends


def test_reversal_prefixes_match_the_scanner_and_3_2u_is_not_one():
    # The entry candle is the last index. Its own type is ignored. A 2D with a 3 before it is 2d-2u.
    assert reversal_kind([None, TWO_UP, TWO_DOWN, TWO_UP], 3) == "2d-2u"
    assert reversal_kind([None, OUTSIDE, TWO_DOWN, TWO_UP], 3) == "2d-2u"
    assert reversal_kind([None, TWO_DOWN, INSIDE, TWO_UP], 3) == "2d-1-2u"
    assert reversal_kind([None, OUTSIDE, INSIDE, TWO_UP], 3) == "3-1-2u"
    assert reversal_kind([None, INSIDE, TWO_DOWN, TWO_UP], 3) == "1-2d-2u"
    assert reversal_kind([None, TWO_UP, INSIDE, TWO_UP], 3) is None  # continuation, not a reversal
    assert reversal_kind([None, OUTSIDE, TWO_UP], 2) is None  # 3-2u
    assert reversal_kind([None, INSIDE, OUTSIDE, TWO_UP], 3) is None


def _two_down_then_break(day: str = "2026-10-16") -> pd.DataFrame:
    """9:30–9:45 is a 2U, 9:45–10:00 is a 2D, so the next candle is a 2d-2u and not a 1-2d-2u."""
    bars = pd.concat([_session("2026-10-15"), _session(day)])
    # Yesterday's last candle sits inside today's open range, so 9:30–9:45 takes out only its high.
    for ts in ("2026-10-15 15:50", "2026-10-15 15:55", "2026-10-15 16:00"):
        _at(bars, ts, high=100, low=98)
    _at(bars, f"{day} 09:50", low=96)
    return bars


def test_a_2d_2u_through_trade_uses_the_prior_high_and_not_the_trigger_low():
    bars = _two_down_then_break()
    # Trigger bar low is 94, under the prior low of 96. The next bar trades the stop at 96 and no lower.
    _at(bars, "2026-10-16 10:05", open=100, high=104, low=94, close=100)
    _at(bars, "2026-10-16 10:10", open=100, high=102, low=96, close=100)
    signal = first_reversal(bars, "2026-10-16", 15)
    assert signal is not None
    assert signal["pattern"] == "2d-2u"
    assert signal["entry_price"] == pytest.approx(101)
    assert signal["entry_time"] == "10:05"
    assert signal["stop_price"] == pytest.approx(96)
    assert signal["finished_2u"] == 0  # the trigger bar took out 96, so the candle finishes as a 3
    candle = next(c for c in aggregate_bars(bars, 15) if c.end == pd.Timestamp("2026-10-16 10:15"))
    assert candle.low == pytest.approx(94)

    daily = _daily()
    rows = strat_reversals_for_day("2026-10-16", ["AAA"], {"AAA": bars, "QQQ": _session("2026-10-16")}, daily, list(daily["AAA"].index.strftime("%Y-%m-%d")))
    trade = next(row for row in rows if row["symbol"] == "AAA" and row["timeframe"] == 15)
    assert trade["stopped"] == 1 and trade["stop_day"] == 0 and trade["gapped"] == 0
    assert trade["exit_pct"] == pytest.approx((96 / 101 - 1) * 100)
    assert realized_lod_r(trade, "eod") == pytest.approx(-1)
    # The trigger bar is not itself the stop, and its low is not the stop price.
    assert trade["stop_price"] == pytest.approx(96)


def test_a_gap_fills_at_the_open_and_a_later_gap_through_the_stop_exits_there():
    bars = _two_down_then_break()
    _at(bars, "2026-10-16 10:05", open=103, high=106, low=100, close=104)
    _at(bars, "2026-10-16 10:10", high=106)
    nxt = _session("2026-10-17")
    _at(nxt, "2026-10-17 09:35", open=89, high=110, low=80, close=90)
    tape = pd.concat([bars, nxt])
    signal = first_reversal(tape, "2026-10-16", 15)
    assert signal["entry_price"] == pytest.approx(103)
    assert signal["entry_time"] == "10:00"
    assert signal["stop_price"] == pytest.approx(96)
    assert signal["finished_2u"] == 1
    daily = _daily()
    rows = strat_reversals_for_day(
        "2026-10-16",
        ["AAA"],
        {"AAA": tape, "QQQ": pd.concat([_session("2026-10-16"), _session("2026-10-17")])},
        daily,
        ["2026-10-16", "2026-10-17", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"],
    )
    trade = next(row for row in rows if row["timeframe"] == 15)
    assert trade["gapped"] == 1 and trade["stop_day"] == 1
    assert trade["exit_pct"] == pytest.approx((89 / 103 - 1) * 100)
    assert realized_lod_r(trade, "d1") == pytest.approx(-2)
    assert trade["mfe_pct"] == pytest.approx((106 / 103 - 1) * 100)


def test_the_opening_candle_and_a_3_2u_are_not_entries():
    bars = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(bars, "2026-10-15 16:00", low=90)
    _at(bars, "2026-10-16 09:35", high=110)
    assert first_reversal(bars, "2026-10-16", 15) is None

    outside = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(outside, "2026-10-16 09:50", low=96, high=104)  # 9:45–10:00 is a 3
    _at(outside, "2026-10-16 10:05", high=106)  # next candle breaks that high: 3-2u
    assert first_reversal(outside, "2026-10-16", 15) is None


def test_each_bullish_prefix_is_recognized_and_only_the_first_reversal_is_kept():
    def tape_for(kind: str) -> pd.DataFrame:
        bars = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
        if kind == "2d-1-2u":
            _at(bars, "2026-10-16 09:50", low=96)  # 9:45–10:00 is 2D
            _at(bars, "2026-10-16 10:05", high=100.5, low=99.2)
            _at(bars, "2026-10-16 10:10", high=100.5, low=99.2)
            _at(bars, "2026-10-16 10:15", high=100.5, low=99.2)  # 10:00–10:15 inside
            _at(bars, "2026-10-16 10:20", high=104)
        elif kind == "3-1-2u":
            _at(bars, "2026-10-16 09:50", low=96, high=104)  # 3
            _at(bars, "2026-10-16 10:05", high=102, low=98)
            _at(bars, "2026-10-16 10:10", high=102, low=98)
            _at(bars, "2026-10-16 10:15", high=102, low=98)  # inside the 3
            _at(bars, "2026-10-16 10:20", high=103)
        elif kind == "1-2d-2u":
            _at(bars, "2026-10-16 10:05", low=96)  # 10:00–10:15 is 2D after an inside
            _at(bars, "2026-10-16 10:20", high=104)
        else:
            raise AssertionError(kind)
        return bars

    expected_time = {"2d-1-2u": "10:20", "3-1-2u": "10:20", "1-2d-2u": "10:20"}
    for kind, when in expected_time.items():
        signal = first_reversal(tape_for(kind), "2026-10-16", 15)
        assert signal is not None, kind
        assert signal["pattern"] == kind
        assert signal["entry_time"] == when

    both = _two_down_then_break()
    _at(both, "2026-10-16 10:05", high=104)
    _at(both, "2026-10-16 11:00", low=90)  # a later 2D
    _at(both, "2026-10-16 11:20", high=110)  # and another reversal after it
    signal = first_reversal(both, "2026-10-16", 15)
    assert signal["entry_time"] == "10:05"
    assert signal["pattern"] == "2d-2u"


def test_a_trigger_with_no_risk_is_skipped_and_nothing_fills_after_1530():
    bars = _two_down_then_break()
    # The 2D candle is a single price under the prior low, so a through-trade at that high has no risk.
    for ts in ("2026-10-16 09:50", "2026-10-16 09:55", "2026-10-16 10:00"):
        _at(bars, ts, open=98, high=98, low=98, close=98)
    _at(bars, "2026-10-16 10:05", open=98, high=99, low=98, close=98)  # through at 98, stop 98
    _at(bars, "2026-10-16 10:10", open=100, high=101, low=99, close=100)  # gap, stop is now under the entry
    signal = first_reversal(bars, "2026-10-16", 15)
    assert signal["entry_price"] == pytest.approx(100)
    assert signal["entry_time"] == "10:05"
    assert signal["stop_price"] == pytest.approx(98)

    late = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(late, "2026-10-16 15:20", low=96)  # 15:15–15:30 candle is 2D
    _at(late, "2026-10-16 15:35", open=100, high=104, low=99, close=100)  # through-trade known at 15:35
    assert first_reversal(late, "2026-10-16", 15) is None
    _at(late, "2026-10-16 15:35", open=104, high=105, low=100, close=104)  # gap, known at 15:30
    gap = first_reversal(late, "2026-10-16", 15)
    assert gap["entry_time"] == "15:30"
    assert gap["entry_price"] == pytest.approx(104)

    allowed = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(allowed, "2026-10-16 15:05", low=96)
    _at(allowed, "2026-10-16 15:30", high=104)
    on_time = first_reversal(allowed, "2026-10-16", 15)
    assert on_time["entry_time"] == "15:30"


def test_the_30_minute_opening_candle_is_context_and_the_next_one_can_trigger():
    bars = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(bars, "2026-10-15 16:00", low=90)
    _at(bars, "2026-10-16 09:40", high=110)
    assert first_reversal(bars, "2026-10-16", 30) is None

    setup = pd.concat([_session("2026-10-15"), _session("2026-10-16")])
    _at(setup, "2026-10-16 09:40", low=96)  # 9:30–10:00 is 2D, and it is not an entry candle
    _at(setup, "2026-10-16 10:05", high=104)
    signal = first_reversal(setup, "2026-10-16", 30)
    assert signal["pattern"] == "1-2d-2u"
    assert signal["entry_time"] == "10:05"
    assert signal["entry_price"] == pytest.approx(101)
    assert signal["stop_price"] == pytest.approx(96)
    assert signal["entry_end"].time() == time(10, 5)


def test_rma_qualification_uses_only_closes_known_at_the_decision():
    prior = _session("2026-10-15")
    today = _session("2026-10-16")
    _at(today, "2026-10-16 09:50", low=96)
    through = pd.concat([prior, today])
    _at(through, "2026-10-16 10:05", open=100, high=104, low=99, close=100)
    assert first_reversal(through, "2026-10-16", 15)["qualified"] == 0
    _at(through, "2026-10-16 10:05", close=105)
    assert first_reversal(through, "2026-10-16", 15)["qualified"] == 1

    gap = pd.concat([prior, _session("2026-10-16")])
    _at(gap, "2026-10-16 09:50", low=96)
    _at(gap, "2026-10-16 10:05", open=102, high=103, low=100, close=110)
    assert first_reversal(gap, "2026-10-16", 15)["qualified"] == 0
    _at(gap, "2026-10-16 10:00", close=100.5)
    assert first_reversal(gap, "2026-10-16", 15)["qualified"] == 1


def test_first_name_is_the_earliest_inside_the_filtered_book_and_an_unfinished_morning_waits():
    def row(symbol, when, qualified, pattern, **extra):
        base = {
            "date": "2026-10-01",
            "symbol": symbol,
            "timeframe": 15,
            "entry_time": when,
            "qualified": qualified,
            "finished_2u": 1,
            "pattern": pattern,
            "stop_pct": 1.0,
            "stopped": 0,
            "stop_day": None,
            "gapped": 0,
            "eod_pct": 1.0,
            "d3_pct": 2.0,
            "exit_pct": None,
            "mfe_pct": 2.0,
        }
        base.update(extra)
        return base

    trades = [
        row("BBB", "10:05", 0, "2d-2u", stop_pct=1.0, d3_pct=-2.0),
        row("AAA", "10:20", 1, "3-1-2u", stop_pct=2.0, d3_pct=4.0, finished_2u=0),
        row("BBB", "11:00", 1, "2d-2u", date="2026-10-02", d3_pct=None, eod_pct=1.0),
        row(
            "AAA",
            "10:30",
            1,
            "1-2d-2u",
            date="2026-10-05",
            stopped=1,
            stop_day=0,
            gapped=0,
            exit_pct=-1.0,
            d3_pct=None,
            eod_pct=3.0,
            mfe_pct=0.5,
        ),
        row(
            "BBB",
            "10:40",
            1,
            "2d-1-2u",
            date="2026-10-05",
            stopped=1,
            stop_day=0,
            exit_pct=-4.0,
            stop_pct=2.0,
            d3_pct=None,
            eod_pct=1.0,
            mfe_pct=0.4,
        ),
    ]
    qqq = [
        {"date": "2026-10-01", "entry_time": "10:05", "timeframe": 0, "stopped": 0, "stop_day": None, "eod_pct": 0.0, "d3_pct": 0.0},
        {"date": "2026-10-01", "entry_time": "10:20", "timeframe": 0, "stopped": 0, "stop_day": None, "eod_pct": 0.0, "d3_pct": 1.0},
    ]
    rma = [
        {
            "date": "2026-10-01",
            "symbol": "ZZZ",
            "entry_time": "10:30",
            "stop_pct": 1.0,
            "stopped": 0,
            "stop_day": None,
            "gapped": 0,
            "eod_pct": 1.0,
            "d3_pct": 1.0,
            "exit_pct": None,
            "mfe_pct": 1.0,
        }
    ]
    stats = build_reversal_stats(trades, qqq, rma)
    assert stats["books"]["15_first"]["n_fills"] == 3
    assert stats["books"]["15_first"]["horizons"]["d3"]["n_trades"] == 2  # 10-02 is unfinished; 10-05 is fully stopped
    first_patterns = stats["books"]["15_first"]["pattern_counts"]
    assert first_patterns["2d-2u"] == 2  # BBB on the 1st and the unfinished 2nd; AAA is later that morning
    assert stats["books"]["15_rma_all"]["n_fills"] == 4  # BBB on the 1st is not qualified
    assert stats["books"]["15_rma_first"]["pattern_counts"]["3-1-2u"] == 1
    assert stats["books"]["15_all"]["finished_2u_rate"] == pytest.approx(4 / 5)
    assert stats["books"]["15_rma_first"]["horizons"]["d3"]["avg_r"] == pytest.approx(0.5)
    assert stats["books"]["15_rma_first"]["horizons"]["d3"]["vs_rma_first"] == pytest.approx(1)
    assert stats["books"]["30_all"]["n_fills"] == 0
    assert stats["benchmark"]["avg_r"] == pytest.approx(1)
    assert stats["best"]["id"] == "15_rma_first"


def test_stored_reversals_round_trip_and_leave_the_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    before = revision(db)
    replace_strat_reversals(
        "2026-10-16",
        [
            {
                "symbol": "AAA",
                "timeframe": 15,
                "entry_time": "10:05",
                "entry_price": 101,
                "stop_price": 96,
                "stop_pct": 5,
                "eod_pct": 1,
                "d1_pct": None,
                "d2_pct": None,
                "d3_pct": None,
                "d4_pct": None,
                "d5_pct": None,
                "stopped": 0,
                "stop_day": None,
                "exit_pct": None,
                "gapped": 0,
                "mfe_pct": 2,
                "pattern": "2d-2u",
                "qualified": 1,
                "finished_2u": 0,
            }
        ],
        db,
    )
    rows = strat_reversals_between("2026-10-16", "2026-10-16", db)
    assert rows[0]["pattern"] == "2d-2u" and rows[0]["qualified"] == 1 and rows[0]["finished_2u"] == 0
    assert revision(db) != before
    delete_day("2026-10-16", db)
    assert strat_reversals_between("2026-10-16", "2026-10-16", db) == []
