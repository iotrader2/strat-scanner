"""First 5-minute close above the 20 RMA, with the same rule on the SMA and the EMA."""

import math

import pandas as pd
import pytest

from strat import config
from strat.cross_trigger import (
    build_cross_stats,
    cross_triggers_for_day,
    first_cross,
    sma,
)
from strat.morning import realized_lod_r
from strat.morning_store import (
    cross_trigger_days,
    cross_trigger_tape_days,
    cross_triggers_between,
    delete_day,
    replace_cross_triggers,
    revision,
)


def _ohlc(rows: list[tuple]) -> pd.DataFrame:
    """Rows are (bar end, open, high, low, close)."""
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


def _flat(day: str, start: str, n: int, price: float) -> list[tuple]:
    idx = pd.date_range(f"{day} {start}", periods=n, freq="5min") + pd.Timedelta(minutes=5)
    return [(stamp.strftime("%Y-%m-%d %H:%M"), price, price, price, price) for stamp in idx]


def _daily(closes: dict[str, float]) -> pd.DataFrame:
    idx = pd.to_datetime(list(closes))
    close = pd.Series(list(closes.values()), index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )


def test_sma_is_the_mean_of_the_last_length_closes():
    out = sma([1, 2, 3, 4], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx(2)
    assert out[3] == pytest.approx(3)


def test_a_close_before_945_is_not_the_entry_and_945_is():
    prior = _flat("2026-10-15", "15:45", 3, 10)
    early = _ohlc(prior + [
        ("2026-10-16 09:35", 10, 21, 9, 20),
        ("2026-10-16 09:40", 10, 11, 9, 10),
        ("2026-10-16 09:45", 10, 11, 9, 10),
    ])
    assert first_cross(early, "2026-10-16", "sma", length=3) is None

    later = _ohlc(prior + [
        ("2026-10-16 09:35", 10, 21, 9, 20),
        ("2026-10-16 09:40", 10, 11, 9, 10),
        ("2026-10-16 09:45", 12, 21, 18, 20),
    ])
    hit = first_cross(later, "2026-10-16", "rma", length=3)
    assert hit["entry_time"] == "09:45"
    assert hit["entry_price"] == pytest.approx(20)
    assert hit["stop_price"] == pytest.approx(18)
    assert hit["opened_above"] == 0


def test_a_name_already_above_at_the_open_still_enters_at_or_after_945():
    prior = _flat("2026-10-15", "15:45", 3, 10)
    bars = _ohlc(prior + [
        ("2026-10-16 09:35", 15, 16, 10, 11),
        ("2026-10-16 09:40", 11, 12, 10, 11),
        ("2026-10-16 09:45", 11, 13, 10, 12),
    ])
    hit = first_cross(bars, "2026-10-16", "sma", length=3)
    assert hit["entry_time"] == "09:45"
    assert hit["entry_price"] == pytest.approx(12)
    assert hit["opened_above"] == 1

    under = bars.copy()
    under.iloc[-3, under.columns.get_loc("open")] = 9
    assert first_cross(under, "2026-10-16", "sma", length=3)["opened_above"] == 0


def test_a_name_that_never_closes_above_the_average_is_not_bought():
    bars = _ohlc(_flat("2026-10-15", "15:45", 3, 10) + _flat("2026-10-16", "09:30", 6, 9))
    assert first_cross(bars, "2026-10-16", "ema", length=3) is None


def test_a_close_equal_to_the_average_does_not_trigger():
    prior = _flat("2026-10-15", "15:45", 3, 10)
    bars = _ohlc(prior + [
        ("2026-10-16 09:35", 10, 13, 9, 12),
        ("2026-10-16 09:40", 10, 11, 9, 10),
        ("2026-10-16 09:45", 11, 12, 10, 11),  # SMA is exactly 11
        ("2026-10-16 09:50", 12, 13, 11, 12),
    ])
    hit = first_cross(bars, "2026-10-16", "sma", length=3)
    assert hit["entry_time"] == "09:50"
    assert hit["entry_price"] == pytest.approx(12)


def test_a_bar_with_no_risk_is_skipped_for_a_later_bar():
    bars = _ohlc(_flat("2026-10-15", "15:45", 3, 10) + [
        ("2026-10-16 09:35", 10, 11, 9, 10),
        ("2026-10-16 09:40", 10, 11, 9, 10),
        ("2026-10-16 09:45", 20, 20, 20, 20),
        ("2026-10-16 09:50", 21, 22, 19, 21),
    ])
    hit = first_cross(bars, "2026-10-16", "sma", length=3)
    assert hit["entry_time"] == "09:50"
    assert hit["stop_price"] == pytest.approx(19)


def test_sma_ema_and_rma_can_trigger_at_different_times():
    # Length 3 makes the three averages disagree inside a short series. Production uses 20.
    bars = _ohlc([
        ("2026-10-15 15:50", 1, 1, 1, 1),
        ("2026-10-15 15:55", 1, 1, 1, 1),
        ("2026-10-15 16:00", 100, 100, 100, 100),
        ("2026-10-16 09:35", 40, 41, 9, 10),
        ("2026-10-16 09:40", 10, 11, 9, 10),
        ("2026-10-16 09:45", 20, 21, 19, 20),
        ("2026-10-16 09:50", 20, 21, 19, 20),
        ("2026-10-16 09:55", 21, 22, 20, 21),
    ])
    sma_hit = first_cross(bars, "2026-10-16", "sma", length=3)
    ema_hit = first_cross(bars, "2026-10-16", "ema", length=3)
    rma_hit = first_cross(bars, "2026-10-16", "rma", length=3)
    assert sma_hit["entry_time"] == "09:45"
    assert ema_hit["entry_time"] == "09:45"
    assert rma_hit["entry_time"] == "09:55"
    assert rma_hit["entry_price"] == pytest.approx(21)
    assert rma_hit["opened_above"] == 1


def test_the_entry_bar_is_not_a_stop_and_a_later_touch_or_gap_is():
    prior = _flat("2026-10-15", "14:20", 20, 100)
    held = _ohlc(prior + [
        ("2026-10-16 09:35", 110, 111, 99, 100),
        ("2026-10-16 09:40", 100, 101, 99, 100),
        ("2026-10-16 09:45", 106, 112, 104, 108),
        ("2026-10-16 09:50", 109, 115, 107, 110),
    ])
    quiet = _ohlc(prior + _flat("2026-10-16", "09:30", 4, 90))
    daily = {"AAA": _daily({"2026-10-16": 120}), "BBB": _daily({"2026-10-16": 90}), "QQQ": _daily({"2026-10-16": 400})}
    qqq = _ohlc(prior + [
        ("2026-10-16 09:35", 400, 401, 399, 400),
        ("2026-10-16 09:40", 400, 401, 399, 400),
        ("2026-10-16 09:45", 400, 401, 399, 400),
    ])
    rows = cross_triggers_for_day(
        "2026-10-16",
        ["AAA", "BBB"],
        {"AAA": held, "BBB": quiet, "QQQ": qqq},
        daily,
        ["2026-10-15", "2026-10-16"],
    )
    leaders = [row for row in rows if row["symbol"] == "AAA"]
    assert {row["rule"] for row in leaders} == {"rma", "sma", "ema"}
    assert all(row["entry_time"] == "09:45" and row["entry_price"] == pytest.approx(108) for row in leaders)
    assert all(row["stop_price"] == pytest.approx(104) and row["opened_above"] == 1 for row in leaders)
    assert all(row["stopped"] == 0 for row in leaders)
    assert [row for row in rows if row["symbol"] == "BBB"] == []
    assert any(row["rule"] == "qqq" and row["entry_time"] == "09:45" for row in rows)

    touch = held.copy()
    touch.loc[pd.Timestamp("2026-10-16 09:55")] = {"open": 106, "high": 107, "low": 104, "close": 105, "volume": 1e5}
    touched = cross_triggers_for_day("2026-10-16", ["AAA"], {"AAA": touch, "QQQ": qqq}, daily, ["2026-10-16"])
    rma = next(row for row in touched if row["rule"] == "rma")
    assert rma["stopped"] == 1 and rma["gapped"] == 0 and rma["stop_day"] == 0
    assert realized_lod_r(rma, "eod") == pytest.approx(-1)

    gap = held.copy()
    gap.loc[pd.Timestamp("2026-10-16 09:55")] = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1e5}
    gapped = cross_triggers_for_day("2026-10-16", ["AAA"], {"AAA": gap, "QQQ": qqq}, daily, ["2026-10-16"])
    rma = next(row for row in gapped if row["rule"] == "rma")
    assert rma["gapped"] == 1
    assert realized_lod_r(rma, "eod") == pytest.approx((100 - 108) / (108 - 104))


def test_unfinished_mornings_drop_out_and_a_zero_day_counts_in_trades_per_day():
    rows = [
        {
            "date": "2026-10-01", "symbol": "AAA", "rule": "rma", "entry_time": "09:45",
            "stop_pct": 1.0, "stopped": 0, "stop_day": None, "gapped": 0,
            "eod_pct": 2.0, "d3_pct": 2.0, "exit_pct": None, "mfe_pct": 3.0, "opened_above": 1,
        },
        {
            "date": "2026-10-02", "symbol": "AAA", "rule": "rma", "entry_time": "10:00",
            "stop_pct": 1.0, "stopped": 0, "stop_day": None, "gapped": 0,
            "eod_pct": -4.0, "d3_pct": None, "exit_pct": None, "mfe_pct": 0.0, "opened_above": 0,
        },
        {
            "date": "2026-10-01", "symbol": "BBB", "rule": "sma", "entry_time": "09:45",
            "stop_pct": 1.0, "stopped": 0, "stop_day": None, "gapped": 0,
            "eod_pct": 2.0, "d3_pct": 2.0, "exit_pct": None, "mfe_pct": 2.0, "opened_above": 0,
        },
    ]
    qqq = [{"date": "2026-10-01", "entry_time": "09:45", "rule": "qqq", "stopped": 0, "stop_day": None, "eod_pct": 0.5, "d3_pct": 0.5}]
    rma_first = [{
        "date": "2026-10-01", "symbol": "ZZZ", "entry_time": "10:30", "stop_pct": 1.0,
        "stopped": 0, "stop_day": None, "gapped": 0, "eod_pct": 1.0, "d3_pct": 1.0, "exit_pct": None, "mfe_pct": 1.0,
    }]
    stats = build_cross_stats(rows, qqq, rma_first, tape_days=["2026-10-01", "2026-10-02", "2026-10-03"])
    book = stats["books"]["rma"]
    assert book["horizons"]["d3"]["n_days"] == 1
    assert book["horizons"]["eod"]["n_days"] == 2
    assert book["horizons"]["d3"]["avg_r"] == pytest.approx(2)
    assert book["horizons"]["d3"]["vs_rma_first"] == pytest.approx(1)
    assert book["opened_above"] == 1
    assert book["trades_per_day"] == pytest.approx(2 / 3)
    assert stats["books"]["ema"]["trades_per_day"] == pytest.approx(0)
    assert stats["benchmark"]["avg_r"] == pytest.approx(1)
    assert stats["best"]["id"] == "rma"


def test_stored_crosses_round_trip_and_a_quiet_tape_day_stays_in_the_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    before = revision(db)
    replace_cross_triggers(
        "2026-10-16",
        [{
            "symbol": "AAA", "rule": "rma", "entry_time": "09:45", "entry_price": 108,
            "stop_price": 104, "stop_pct": 4, "eod_pct": 1, "d1_pct": None, "d2_pct": None,
            "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
            "exit_pct": None, "gapped": 0, "mfe_pct": 2, "opened_above": 1,
        }],
        db,
        had_tape=True,
    )
    replace_cross_triggers("2026-10-15", [], db, had_tape=True)
    replace_cross_triggers("2026-10-14", [], db, had_tape=False)
    rows = cross_triggers_between("2026-10-16", "2026-10-16", db)
    assert rows[0]["opened_above"] == 1 and rows[0]["rule"] == "rma" and rows[0]["entry_price"] == pytest.approx(108)
    assert cross_trigger_days(db) == {"2026-10-14", "2026-10-15", "2026-10-16"}
    assert cross_trigger_tape_days(db) == ["2026-10-15", "2026-10-16"]
    assert revision(db) != before
    delete_day("2026-10-16", db)
    assert cross_triggers_between("2026-10-16", "2026-10-16", db) == []
    assert "2026-10-16" not in cross_trigger_days(db)
