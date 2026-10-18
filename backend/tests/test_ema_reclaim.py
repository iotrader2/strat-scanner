"""EMA pullback then reclaim: three stops, every name and the first name."""

import pandas as pd
import pytest

from strat import config
from strat.ema_reclaim import build_reclaim_stats, ema_reclaims_for_day, first_reclaim
from strat.morning import realized_lod_r
from strat.morning_store import (
    delete_day,
    ema_reclaim_days,
    ema_reclaim_tape_days,
    ema_reclaims_between,
    replace_ema_reclaims,
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


def _prior(close: float = 10) -> list[tuple]:
    return [
        ("2026-10-15 15:50", close, close, close, close),
        ("2026-10-15 15:55", close, close, close, close),
        ("2026-10-15 16:00", close, close, close, close),
    ]


def _daily(closes: dict[str, float]) -> pd.DataFrame:
    idx = pd.to_datetime(list(closes))
    close = pd.Series(list(closes.values()), index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )


def test_a_close_below_then_a_945_reclaim_sets_the_three_stops():
    bars = _ohlc(_prior() + [
        ("2026-10-16 09:35", 12, 13, 11, 12),
        ("2026-10-16 09:40", 9, 10, 8, 9),
        ("2026-10-16 09:45", 11, 12, 10, 11),
    ])
    hit = first_reclaim(bars, "2026-10-16", length=3)
    assert hit["entry_time"] == "09:45"
    assert hit["entry_price"] == pytest.approx(11)
    assert hit["reclaim_stop"] == pytest.approx(10)
    assert hit["pullback_stop"] == pytest.approx(8)
    assert hit["lod_stop"] == pytest.approx(8)


def test_a_name_that_stays_above_the_ema_is_not_bought():
    bars = _ohlc(_prior() + [
        ("2026-10-16 09:35", 12, 13, 11, 12),
        ("2026-10-16 09:40", 12, 13, 11, 12),
        ("2026-10-16 09:45", 13, 14, 12, 13),
    ])
    assert first_reclaim(bars, "2026-10-16", length=3) is None


def test_a_reclaim_before_945_does_not_fill_and_needs_a_fresh_pullback():
    stayed = _ohlc(_prior() + [
        ("2026-10-16 09:35", 9, 10, 7, 9),
        ("2026-10-16 09:40", 12, 13, 11, 12),
        ("2026-10-16 09:45", 12, 13, 11, 12),
        ("2026-10-16 09:50", 13, 14, 12, 13),
    ])
    assert first_reclaim(stayed, "2026-10-16", length=3) is None

    again = _ohlc(_prior() + [
        ("2026-10-16 09:35", 9, 10, 7, 9),
        ("2026-10-16 09:40", 12, 13, 11, 12),
        ("2026-10-16 09:45", 12, 13, 11.5, 12),
        ("2026-10-16 09:50", 10, 11, 9.5, 10),
        ("2026-10-16 09:55", 12, 13, 11, 12),
    ])
    hit = first_reclaim(again, "2026-10-16", length=3)
    assert hit["entry_time"] == "09:55"
    assert hit["entry_price"] == pytest.approx(12)
    assert hit["reclaim_stop"] == pytest.approx(11)
    assert hit["pullback_stop"] == pytest.approx(9.5)
    assert hit["lod_stop"] == pytest.approx(7)


def test_a_close_equal_to_the_ema_is_not_a_pullback_or_a_reclaim():
    bars = _ohlc(_prior() + [
        ("2026-10-16 09:35", 10, 11, 9, 10),
        ("2026-10-16 09:40", 8, 9, 7, 8),
        ("2026-10-16 09:45", 9, 10, 8.5, 9),
        ("2026-10-16 09:50", 10, 11, 9, 10),
    ])
    hit = first_reclaim(bars, "2026-10-16", length=3)
    assert hit["entry_time"] == "09:50"
    assert hit["entry_price"] == pytest.approx(10)
    assert hit["pullback_stop"] == pytest.approx(7)


def test_only_the_first_reclaim_is_kept_and_a_flat_reclaim_bar_drops_that_stop():
    bars = _ohlc(_prior() + [
        ("2026-10-16 09:40", 9, 10, 8, 9),
        ("2026-10-16 09:45", 11, 11, 11, 11),
        ("2026-10-16 09:50", 8, 9, 7, 8),
        ("2026-10-16 09:55", 14, 15, 12, 14),
    ])
    hit = first_reclaim(bars, "2026-10-16", length=3)
    assert hit["entry_time"] == "09:45"
    assert hit["reclaim_stop"] is None
    assert hit["pullback_stop"] == pytest.approx(8)
    assert hit["lod_stop"] == pytest.approx(8)


def test_yesterdays_close_below_the_ema_does_not_arm_today():
    bars = _ohlc([
        ("2026-10-15 15:50", 20, 20, 20, 20),
        ("2026-10-15 15:55", 20, 20, 20, 20),
        ("2026-10-15 16:00", 10, 11, 9, 10),
        ("2026-10-16 09:35", 30, 31, 29, 30),
        ("2026-10-16 09:40", 30, 31, 29, 30),
        ("2026-10-16 09:45", 30, 31, 29, 30),
    ])
    assert first_reclaim(bars, "2026-10-16", length=3) is None


def test_the_entry_bar_is_not_a_stop_and_the_three_stops_exit_apart():
    bars = _ohlc(_prior() + [
        ("2026-10-16 09:35", 12, 13, 11, 12),
        ("2026-10-16 09:40", 9, 10, 8, 9),
        ("2026-10-16 09:45", 11, 12, 10, 11),
    ])
    daily = {"AAA": _daily({"2026-10-16": 12}), "QQQ": _daily({"2026-10-16": 400})}
    qqq = _ohlc(_prior(400) + [
        ("2026-10-16 09:35", 400, 401, 399, 400),
        ("2026-10-16 09:40", 400, 401, 399, 400),
        ("2026-10-16 09:45", 400, 401, 399, 400),
    ])
    held = ema_reclaims_for_day("2026-10-16", ["AAA"], {"AAA": bars, "QQQ": qqq}, daily, ["2026-10-16"], length=3)
    by_rule = {row["rule"]: row for row in held if row["symbol"] == "AAA"}
    assert set(by_rule) == {"reclaim", "pullback", "lod"}
    assert all(row["stopped"] == 0 and row["entry_price"] == pytest.approx(11) for row in by_rule.values())
    assert any(row["rule"] == "qqq" and row["entry_time"] == "09:45" for row in held)

    gap = bars.copy()
    gap.loc[pd.Timestamp("2026-10-16 09:50")] = {"open": 9, "high": 10, "low": 9, "close": 9, "volume": 1e5}
    gapped = ema_reclaims_for_day("2026-10-16", ["AAA"], {"AAA": gap, "QQQ": qqq}, daily, ["2026-10-16"], length=3)
    reclaim = next(row for row in gapped if row["rule"] == "reclaim")
    pullback = next(row for row in gapped if row["rule"] == "pullback")
    assert reclaim["gapped"] == 1
    assert realized_lod_r(reclaim, "eod") == pytest.approx((9 - 11) / (11 - 10))
    assert pullback["stopped"] == 0


def test_first_name_is_the_earliest_reclaim_and_a_zero_day_counts():
    def row(day, symbol, rule, clock, r_pct):
        return {
            "date": day, "symbol": symbol, "rule": rule, "entry_time": clock,
            "stop_pct": 1.0, "stopped": 0, "stop_day": None, "gapped": 0,
            "eod_pct": r_pct, "d3_pct": r_pct, "exit_pct": None, "mfe_pct": r_pct,
        }
    rows = [
        row("2026-10-01", "BBB", "reclaim", "10:00", 2.0),
        row("2026-10-01", "AAA", "reclaim", "09:45", 4.0),
        row("2026-10-01", "CCC", "reclaim", "09:45", -1.0),
        row("2026-10-02", "AAA", "reclaim", "09:45", -4.0),
    ]
    rows[-1]["d3_pct"] = None
    for rule in ("pullback", "lod"):
        rows.append(row("2026-10-01", "AAA", rule, "09:45", 1.0))
    rma_first = [{
        "date": "2026-10-01", "symbol": "ZZZ", "entry_time": "10:30", "stop_pct": 1.0,
        "stopped": 0, "stop_day": None, "gapped": 0, "eod_pct": 1.0, "d3_pct": 1.0, "exit_pct": None, "mfe_pct": 1.0,
    }]
    stats = build_reclaim_stats(rows, [], rma_first, tape_days=["2026-10-01", "2026-10-02", "2026-10-03"])
    book = stats["books"]["reclaim_all"]
    assert book["horizons"]["d3"]["n_days"] == 1
    assert book["horizons"]["eod"]["n_days"] == 2
    assert book["trades_per_day"] == pytest.approx(4 / 3)
    assert stats["books"]["pullback_all"]["trades_per_day"] == pytest.approx(1 / 3)
    first = stats["books"]["reclaim_first"]
    assert first["n_fills"] == 2
    assert first["horizons"]["d3"]["avg_r"] == pytest.approx(4)
    assert first["horizons"]["d3"]["vs_rma_first"] == pytest.approx(3)
    assert stats["benchmark"]["avg_r"] == pytest.approx(1)
    assert stats["best"]["id"] == "reclaim_first"


def test_stored_reclaims_round_trip_and_a_quiet_tape_day_stays_in_the_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    db = tmp_path / "cache.sqlite3"
    before = revision(db)
    replace_ema_reclaims(
        "2026-10-16",
        [{
            "symbol": "AAA", "rule": "pullback", "entry_time": "09:45", "entry_price": 11,
            "stop_price": 8, "stop_pct": 3, "eod_pct": 1, "d1_pct": None, "d2_pct": None,
            "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
            "exit_pct": None, "gapped": 0, "mfe_pct": 2,
        }],
        db,
        had_tape=True,
    )
    replace_ema_reclaims("2026-10-15", [], db, had_tape=True)
    replace_ema_reclaims("2026-10-14", [], db, had_tape=False)
    rows = ema_reclaims_between("2026-10-16", "2026-10-16", db)
    assert rows[0]["rule"] == "pullback" and rows[0]["stop_price"] == pytest.approx(8)
    assert ema_reclaim_days(db) == {"2026-10-14", "2026-10-15", "2026-10-16"}
    assert ema_reclaim_tape_days(db) == ["2026-10-15", "2026-10-16"]
    assert revision(db) != before
    delete_day("2026-10-16", db)
    assert ema_reclaims_between("2026-10-16", "2026-10-16", db) == []
    assert "2026-10-16" not in ema_reclaim_days(db)
