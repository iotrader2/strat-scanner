"""5-minute Strat pullback after a 20 RMA close, stopped at the low of day."""

from datetime import time

import pandas as pd
import pytest

from strat import config
from strat.morning import realized_lod_r
from strat.morning_store import (
    delete_day,
    replace_strat_pullbacks,
    revision,
    strat_pullback_days,
    strat_pullback_tape_days,
    strat_pullbacks_between,
)
from strat.strat_pullback import (
    build_pullback_stats,
    first_pullback,
    prepare_pullbacks,
    pullback_kind,
    pullbacks_for_day,
)


def _ohlc(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "volume": 1e5,
        },
        index=pd.to_datetime([row[0] for row in rows]),
    )
    return frame.astype(float)


def _prior(day: str = "2026-10-15", close: float = 10) -> list[tuple]:
    return [
        (f"{day} 15:50", close, close, close, close),
        (f"{day} 15:55", close, close, close, close),
        (f"{day} 16:00", close, close, close, close),
    ]


def _hit(
    rows: list[tuple],
    cutoff: str = "11:00",
    day: str = "2026-10-16",
    symbol: str = "AAA",
    earliest: time = time(9, 45),
    book: str | None = None,
):
    bars = _ohlc(rows)
    prepared = prepare_pullbacks({symbol: bars}, [symbol], length=3)
    return first_pullback(prepared.get(symbol), day, cutoff, bars, length=3, earliest=earliest, book=book)


def _fill(**overrides) -> dict:
    row = {
        "date": "2026-10-01",
        "symbol": "AAA",
        "cutoff": "11:00",
        "entry_time": "09:55",
        "entry_price": 100.0,
        "stop_price": 99.0,
        "stop_pct": 1.0,
        "rank": 1,
        "pattern": "2d-2u",
        "stopped": 0,
        "stop_day": None,
        "gapped": 0,
        "exit_pct": None,
        "eod_pct": 2.0,
        "d1_pct": 2.0,
        "d2_pct": 2.0,
        "d3_pct": 2.0,
        "d4_pct": 2.0,
        "d5_pct": 2.0,
        "mfe_pct": 3.0,
    }
    row.update(overrides)
    return row


def test_crwd_shaped_tape_fills_the_0955_break_of_the_prior_high():
    """2026-10-09 CRWD: qualify at 9:35, two-down pullback, through-trade at the 9:50 high."""
    rows = _prior("2026-10-08", 260) + [
        ("2026-10-09 09:35", 267.99, 268.00, 265.69, 267.64),
        ("2026-10-09 09:40", 267.78, 267.85, 263.04, 263.45),
        ("2026-10-09 09:45", 263.49, 264.58, 262.45, 263.00),
        ("2026-10-09 09:50", 262.93, 263.78, 262.44, 263.58),
        ("2026-10-09 09:55", 263.65, 265.96, 263.32, 264.79),
    ]
    early = _hit(rows, "10:30", day="2026-10-09", symbol="CRWD")
    late = _hit(rows, "11:00", day="2026-10-09", symbol="CRWD")
    assert early["entry_price"] == late["entry_price"]
    assert early["entry_time"] == late["entry_time"]
    assert early["stop_price"] == late["stop_price"]
    assert late["entry_time"] == "09:55"
    assert late["entry_price"] == pytest.approx(263.78)
    assert late["stop_price"] == pytest.approx(262.44)
    assert late["pattern"] == "2d-2u"
    assert late["entry_price"] - late["stop_price"] == pytest.approx(1.34)
    # 9:55 is before the 10:00–10:30 window, and this tape has no later trigger.
    assert _hit(rows, "10:30", day="2026-10-09", symbol="CRWD", earliest=time(10, 0), book="win") is None


def test_a_pullback_before_the_rma_cross_does_not_arm_the_entry():
    rows = _prior() + [
        ("2026-10-16 09:35", 9, 11, 8, 8),
        ("2026-10-16 09:40", 8, 9, 7, 8),
        ("2026-10-16 09:45", 8, 12, 7.5, 8),
        ("2026-10-16 09:50", 8, 9, 7.5, 8),
        ("2026-10-16 09:55", 12, 14, 11, 13),
        ("2026-10-16 10:00", 12, 12.5, 10, 11),
        ("2026-10-16 10:05", 11, 13, 10.5, 12.5),
    ]
    hit = _hit(rows)
    assert hit["entry_time"] == "10:05"
    assert hit["entry_price"] == pytest.approx(12.5)
    assert hit["pattern"] == "2d-2u"


def test_a_close_equal_to_the_rma_does_not_qualify():
    rows = _prior() + [
        ("2026-10-16 09:35", 10, 12, 9, 10),
        ("2026-10-16 09:40", 10, 11, 8, 10),
        ("2026-10-16 09:45", 10, 13, 9, 10),
    ]
    assert _hit(rows) is None


def test_yesterdays_close_above_the_rma_does_not_qualify_today():
    rows = [
        ("2026-10-15 15:50", 10, 10, 10, 10),
        ("2026-10-15 15:55", 10, 10, 10, 10),
        ("2026-10-15 16:00", 20, 21, 19, 20),
        ("2026-10-16 09:35", 12, 14, 11, 12),
        ("2026-10-16 09:40", 12, 13, 10, 12),
        ("2026-10-16 09:45", 12, 15, 11, 12),
    ]
    assert _hit(rows) is None


def test_inside_after_a_2u_is_a_1_2u_and_a_3_then_2u_is_not():
    inside = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 15, 12, 14),
        ("2026-10-16 09:45", 14, 14.5, 12.5, 13.5),
        ("2026-10-16 09:50", 13.8, 15.2, 13, 14.5),
    ])
    assert inside["pattern"] == "1-2u"
    assert inside["entry_time"] == "09:50"
    assert inside["entry_price"] == pytest.approx(14.5)

    outside = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 16, 10, 14),
        ("2026-10-16 09:45", 14, 17, 12, 15),
    ])
    assert outside is None


def test_the_more_specific_inside_prefixes_win():
    two_down_inside = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 13.5, 10, 12),
        ("2026-10-16 09:45", 12, 13, 11, 12.5),
        ("2026-10-16 09:50", 12.4, 14, 12, 13),
    ])
    assert two_down_inside["pattern"] == "2d-1-2u"
    assert two_down_inside["entry_price"] == pytest.approx(13)

    inside_two_down = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 13.5, 12, 13),
        ("2026-10-16 09:45", 13, 13.2, 11, 12),
        ("2026-10-16 09:50", 12, 14, 11.5, 13),
    ])
    assert inside_two_down["pattern"] == "1-2d-2u"


def test_a_gap_through_the_prior_high_fills_at_the_open():
    hit = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 10, 11, 8, 9),
        ("2026-10-16 09:50", 12, 13, 11, 12),
    ])
    assert hit["entry_time"] == "09:45"
    assert hit["entry_price"] == pytest.approx(12)
    assert hit["pattern"] == "2d-2u"


def test_a_gap_whose_clock_is_before_945_is_skipped():
    hit = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 13, 15, 12, 14),
    ])
    assert hit is None


def test_an_equal_high_does_not_trigger():
    hit = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 10, 12, 9.5, 11),
    ])
    assert hit is None


def test_1035_is_inside_the_1100_book_and_outside_the_1030_book():
    rows = _prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 10:35", 11, 13, 10, 12),
    ]
    assert _hit(rows, "10:30") is None
    late = _hit(rows, "11:00")
    assert late["entry_time"] == "10:35"
    assert late["entry_price"] == pytest.approx(12)


def test_a_gap_at_the_1100_cutoff_fills_and_a_through_trade_does_not():
    gap = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 11:05", 13, 14, 12, 13),
    ])
    assert gap["entry_time"] == "11:00"
    assert gap["entry_price"] == pytest.approx(13)
    through = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 11:05", 11, 13, 10.5, 12),
    ])
    assert through is None


def test_a_stop_that_is_not_under_the_entry_waits_for_a_later_trigger():
    hit = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 13.5, 13, 13.5),
        ("2026-10-16 09:40", 13, 13, 13, 13),
        ("2026-10-16 09:45", 12.5, 13.5, 13, 13.2),
        ("2026-10-16 09:50", 12, 12.2, 11, 11.5),
        ("2026-10-16 09:55", 11.8, 13, 11.2, 12.5),
    ])
    assert hit["entry_time"] == "09:55"
    assert hit["entry_price"] == pytest.approx(12.2)
    assert hit["stop_price"] == pytest.approx(11)
    assert hit["pattern"] == "2d-2u"


def test_the_entry_bar_is_not_a_stop_and_a_later_gap_exits_at_the_open():
    held = _ohlc(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 10, 11, 8, 9),
        ("2026-10-16 09:50", 12, 13, 11, 12),
        ("2026-10-16 09:55", 12, 13, 11.5, 12.5),
    ])
    prepared = prepare_pullbacks({"AAA": held}, ["AAA"], length=3)
    rows = pullbacks_for_day("2026-10-16", ["AAA"], {"AAA": held}, {}, ["2026-10-16"], ranks={"AAA": 4}, prepared=prepared, length=3)
    trade = next(row for row in rows if row["cutoff"] == "11:00")
    assert trade["stopped"] == 0
    assert trade["rank"] == 4
    assert trade["entry_price"] == pytest.approx(12)

    gapped = _ohlc(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 10, 11, 8, 9),
        ("2026-10-16 09:50", 12, 13, 11, 12),
        ("2026-10-16 10:00", 7, 8, 6, 7),
    ])
    prepared = prepare_pullbacks({"AAA": gapped}, ["AAA"], length=3)
    rows = pullbacks_for_day("2026-10-16", ["AAA"], {"AAA": gapped}, {}, ["2026-10-16"], prepared=prepared, length=3)
    trade = next(row for row in rows if row["cutoff"] == "11:00")
    assert trade["stopped"] == 1
    assert trade["gapped"] == 1
    assert trade["stop_day"] == 0
    assert trade["exit_pct"] == pytest.approx((7 - 12) / 12 * 100)
    assert realized_lod_r(trade, "eod") < -1


def test_first_by_rank_beats_an_earlier_trigger_and_pairs_the_1030_risk():
    def row(symbol, rank, r_pct, entry, cutoff="11:00"):
        return _fill(symbol=symbol, rank=rank, cutoff=cutoff, entry_price=entry, stop_price=entry - 1, d3_pct=r_pct, eod_pct=r_pct)

    pulls = [
        row("BBB", 1, 4.0, 100),
        row("AAA", 3, -1.0, 90),
        row("CCC", 2, 1.0, 80),
        row("BBB", 1, 4.0, 100, cutoff="10:30"),
    ]
    rma = [
        {
            "date": "2026-10-01", "symbol": "BBB", "rule": "rma1030", "entry_time": "10:30",
            "entry_price": 110.0, "stop_price": 100.0, "stop_pct": 1.0, "cross_time": "09:35",
            "rank": 2, "stopped": 0, "stop_day": None, "gapped": 0, "exit_pct": None,
            "eod_pct": 1.0, "d3_pct": 1.0, "mfe_pct": 1.0,
        },
        {
            "date": "2026-10-01", "symbol": "AAA", "rule": "rma1030", "entry_time": "10:30",
            "entry_price": 100.0, "stop_price": 90.0, "stop_pct": 1.0, "cross_time": "09:35",
            "rank": 1, "stopped": 0, "stop_day": None, "gapped": 0, "exit_pct": None,
            "eod_pct": 1.0, "d3_pct": 1.0, "mfe_pct": 1.0,
        },
    ]
    ranks = {"2026-10-01": {"AAA": 1, "BBB": 2, "CCC": 3}}
    # The pullback book orders by the rank stored on the fill, not by cross time.
    stats = build_pullback_stats(pulls, rma, ranks, tape_days=["2026-10-01", "2026-10-02"])
    first = stats["books"]["pb1100_first"]
    assert first["n_fills"] == 1
    assert first["horizons"]["d3"]["avg_r"] == pytest.approx(4)
    assert stats["books"]["pb1100_two"]["n_fills"] == 2
    assert stats["books"]["pb1100_two"]["horizons"]["d3"]["avg_r"] == pytest.approx(2.5)
    assert stats["books"]["pb1100_all"]["n_fills"] == 3
    assert stats["books"]["pb1030_first"]["n_fills"] == 1
    assert first["avg_risk_dollars"] == pytest.approx(1)
    assert first["avg_rma_risk_dollars"] == pytest.approx(10)
    assert first["avg_entry_saved_pct"] == pytest.approx((110 - 100) / 110 * 100)
    assert first["n_paired"] == 1
    assert first["trades_per_day"] == pytest.approx(0.5)
    # Rank-tie 10:30 first is AAA (leader rank 1) at +1R. BBB's +4R is +3R against that morning.
    assert first["horizons"]["d3"]["vs_rank_first"] == pytest.approx(3)
    assert stats["benchmark"]["first"]["avg_r"] == pytest.approx(1)
    assert stats["best"]["id"] == "pb1100_first"


def test_pullback_kind_labels_only_the_five_prefixes():
    assert pullback_kind(["2U", "2D", "2U"], 2) == "2d-2u"
    assert pullback_kind(["2D", "1", "2U"], 2) == "2d-1-2u"
    assert pullback_kind(["3", "1", "3"], 2) == "3-1-2u"
    assert pullback_kind(["1", "2D", "2U"], 2) == "1-2d-2u"
    assert pullback_kind(["2U", "1", "2U"], 2) == "1-2u"
    assert pullback_kind(["1", "3", "2U"], 2) is None


def test_a_trigger_before_1000_is_skipped_and_the_window_takes_the_next_one():
    rows = _prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 12, 12, 9, 10),
        ("2026-10-16 09:45", 11, 13, 10, 12),
        ("2026-10-16 09:50", 11, 11.5, 8, 9),
        ("2026-10-16 10:05", 10, 12, 9.5, 11),
    ]
    early = _hit(rows, "10:30")
    assert early["entry_time"] == "09:45"
    assert early["entry_price"] == pytest.approx(12)
    window = _hit(rows, "10:30", earliest=time(10, 0), book="win")
    assert window["cutoff"] == "win"
    assert window["entry_time"] == "10:05"
    assert window["entry_price"] == pytest.approx(11.5)
    assert window["pattern"] == "2d-2u"


def test_the_window_keeps_1000_and_1030_and_drops_a_1035_through_trade():
    # Pullback bar is 9:55, so it forms before 10:00. The fill is the 10:00 break.
    at_open = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 15, 12, 14),
        ("2026-10-16 09:55", 13, 13.5, 10, 11),
        ("2026-10-16 10:00", 11, 14, 10.5, 13),
    ], "10:30", earliest=time(10, 0))
    assert at_open["entry_time"] == "10:00"
    assert at_open["entry_price"] == pytest.approx(13.5)

    at_close = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 15, 12, 14),
        ("2026-10-16 10:25", 13, 13.5, 10, 11),
        ("2026-10-16 10:30", 11, 14, 10.5, 13),
    ], "10:30", earliest=time(10, 0))
    assert at_close["entry_time"] == "10:30"
    assert at_close["entry_price"] == pytest.approx(13.5)

    # A gap whose bar starts at 10:30 fills. A through-trade known at 10:35 does not.
    gap = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 15, 12, 14),
        ("2026-10-16 10:30", 13, 13.5, 10, 11),
        ("2026-10-16 10:35", 14, 15, 13, 14),
    ], "10:30", earliest=time(10, 0))
    assert gap["entry_time"] == "10:30"
    assert gap["entry_price"] == pytest.approx(14)
    through = _hit(_prior() + [
        ("2026-10-16 09:35", 12, 14, 11, 13),
        ("2026-10-16 09:40", 13, 15, 12, 14),
        ("2026-10-16 10:30", 13, 13.5, 10, 11),
        ("2026-10-16 10:35", 12, 15, 11, 14),
    ], "10:30", earliest=time(10, 0))
    assert through is None


def test_window_first_two_orders_by_time_or_by_rank_and_counts_quiet_mornings():
    def row(symbol, rank, clock, r_pct, day="2026-10-01"):
        return _fill(
            date=day, symbol=symbol, rank=rank, cutoff="win", entry_time=clock,
            d3_pct=r_pct, eod_pct=r_pct, entry_price=100, stop_price=99,
        )

    # Same minute: rank 2 before rank 3. The 10:20 name has the best rank and is later.
    pulls = [
        row("AAA", 3, "10:00", 1.0),
        row("CCC", 2, "10:00", -1.0),
        row("BBB", 1, "10:20", 4.0),
        row("DDD", 4, "10:05", 9.0, day="2026-10-02"),
    ]
    rma = [{
        "date": "2026-10-01", "symbol": "BBB", "rule": "rma1030", "entry_time": "10:30",
        "entry_price": 110.0, "stop_price": 100.0, "stop_pct": 1.0, "cross_time": "09:35",
        "rank": 1, "stopped": 0, "stop_day": None, "gapped": 0, "exit_pct": None,
        "eod_pct": 1.0, "d3_pct": 1.0, "mfe_pct": 1.0,
    }]
    ranks = {"2026-10-01": {"BBB": 1, "CCC": 2, "AAA": 3}}
    stats = build_pullback_stats(pulls, rma, ranks, tape_days=["2026-10-01", "2026-10-02", "2026-10-03"])
    window = stats["window"]
    time_first = window["books"]["win_time_first"]
    time_two = window["books"]["win_time_two"]
    rank_first = window["books"]["win_rank_first"]
    rank_two = window["books"]["win_rank_two"]
    # Day 1 time order is CCC, AAA, BBB. Day 2 is DDD alone. The quiet day is a zero.
    assert time_first["horizons"]["d3"]["avg_r"] == pytest.approx((-1 + 9) / 2)
    assert time_two["horizons"]["d3"]["n_trades"] == 3
    assert time_two["horizons"]["d3"]["avg_r"] == pytest.approx(4.5)
    assert rank_first["horizons"]["d3"]["avg_r"] == pytest.approx((4 + 9) / 2)
    assert rank_two["n_fills"] == 3
    assert time_two["mornings"] == {"0": 1, "1": 1, "2": 1, "more": 0}
    assert rank_first["mornings"]["2"] == 0
    assert window["triggers"] == {"0": 1, "1": 1, "2": 0, "more": 1}
    assert time_first["avg_entry_saved_pct"] is None or time_two["n_paired"] >= 0
    # BBB is the rank-first name on day 1 and the only paired 10:30 fill. Saved (110-100)/110.
    assert rank_first["n_paired"] == 1
    assert rank_first["avg_entry_saved_pct"] == pytest.approx((110 - 100) / 110 * 100)
    assert rank_first["avg_risk_dollars"] == pytest.approx(1)
    assert rank_first["horizons"]["d3"]["vs_rank_first"] == pytest.approx(4 - 1)


def test_stored_pullbacks_round_trip_and_a_quiet_tape_day_stays_in_the_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    before = revision(db)
    replace_strat_pullbacks(
        "2026-10-16",
        [
            {
                "symbol": "AAA", "cutoff": "11:00", "entry_time": "09:55", "entry_price": 263.78,
                "stop_price": 262.44, "stop_pct": 0.51, "eod_pct": 4.0, "d1_pct": None, "d2_pct": None,
                "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
                "exit_pct": None, "gapped": 0, "mfe_pct": 5, "rank": 7, "pattern": "2d-2u",
            },
            {
                "symbol": "QQQ", "cutoff": "qqq", "entry_time": "09:55", "entry_price": 400,
                "stop_price": None, "stop_pct": None, "eod_pct": 0.2, "d1_pct": None, "d2_pct": None,
                "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
                "exit_pct": None, "gapped": 0, "mfe_pct": 0.3, "rank": None, "pattern": None,
            },
            {
                "symbol": "QQQ", "cutoff": "qqq", "entry_time": "10:15", "entry_price": 401,
                "stop_price": None, "stop_pct": None, "eod_pct": 0.1, "d1_pct": None, "d2_pct": None,
                "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
                "exit_pct": None, "gapped": 0, "mfe_pct": 0.2, "rank": None, "pattern": None,
            },
        ],
        db,
        had_tape=True,
    )
    replace_strat_pullbacks("2026-10-15", [], db, had_tape=True)
    replace_strat_pullbacks("2026-10-14", [], db, had_tape=False)
    rows = strat_pullbacks_between("2026-10-16", "2026-10-16", db)
    aaa = next(row for row in rows if row["symbol"] == "AAA")
    assert aaa["pattern"] == "2d-2u" and aaa["entry_price"] == pytest.approx(263.78)
    assert aaa["rank"] == 7
    assert len([row for row in rows if row["cutoff"] == "qqq"]) == 2
    assert strat_pullback_days(db) == {"2026-10-14", "2026-10-15", "2026-10-16"}
    assert strat_pullback_tape_days(db) == ["2026-10-15", "2026-10-16"]
    assert revision(db) != before
    delete_day("2026-10-16", db)
    assert strat_pullbacks_between("2026-10-16", "2026-10-16", db) == []
    assert "2026-10-16" not in strat_pullback_days(db)
