"""Stop sweep on the 10:30 rank-tie books. The entry stays; only the stop changes."""

import pandas as pd
import pytest

from strat.morning import realized_lod_r, session_low_through, window_end
from strat.morning_store import replace_stop_sweeps, revision, stop_sweep_days, stop_sweeps_between
from strat.stop_sweep import (
    CANDIDATES,
    build_sweep_stats,
    daily_atr_prior,
    evaluate_stop,
    intraday_atr_at,
    rank_first_candidates,
    rma_value_at,
    slip_r,
    stop_levels,
    sweeps_for_day,
    wilder_atr,
)


def _frame(index, closes, lows=None, highs=None, opens=None) -> pd.DataFrame:
    closes = [float(v) for v in closes]
    lows = closes if lows is None else [float(v) for v in lows]
    highs = closes if highs is None else [float(v) for v in highs]
    opens = closes if opens is None else [float(v) for v in opens]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1e5},
        index=pd.to_datetime(index),
    ).astype(float)


def _five(day: str, start: str, n: int, close: float, low: float | None = None) -> pd.DataFrame:
    stamps = pd.date_range(f"{day} {start}", periods=n, freq="5min")
    closes = [close] * n
    lows = [close if low is None else low] * n
    return _frame(stamps, closes, lows=lows, highs=[close + 0.2] * n, opens=[close] * n)


def test_wilder_atr_seeds_on_the_length_bar_and_then_smooths():
    high = [10, 12, 11, 13, 12]
    low = [8, 9, 9, 10, 10]
    close = [9, 11, 10, 12, 11]
    values = wilder_atr(high, low, close, length=3)
    assert values[3] == pytest.approx(8 / 3)
    assert values[4] == pytest.approx((2 + 2 * (8 / 3)) / 3)
    assert values[0] != values[0]


def test_daily_atr_uses_the_prior_close_and_ignores_today():
    days = pd.bdate_range("2026-09-01", periods=20)
    daily = _frame(days, [100 + i for i in range(20)], lows=[99] * 20, highs=[101 + i for i in range(20)])
    today = days[-1].strftime("%Y-%m-%d")
    prior = daily_atr_prior(daily, today, length=3)
    without_today = daily_atr_prior(daily.iloc[:-1], today, length=3)
    assert prior == pytest.approx(without_today)
    assert prior == pytest.approx(daily_atr_prior(daily.iloc[:-1], (days[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), length=3))


def test_fixed_percent_and_candle_lows_and_a_stop_above_the_entry_is_skipped():
    day = "2026-10-16"
    prior = _five("2026-10-15", "09:35", 30, 10.0)
    # 09:35 cross, then a drift up. 10:20 low 11, 10:25 low 12, 10:30 low 13, close 20.
    stamps = list(pd.date_range(f"{day} 09:35", periods=12, freq="5min"))
    closes = [12.0] + [15.0] * 10 + [20.0]
    lows = [11.0] + [14.0] * 8 + [11.0, 12.0, 13.0]
    highs = [c + 1 for c in closes]
    today = _frame(stamps, closes, lows=lows, highs=highs, opens=closes)
    bars = pd.concat([prior, today])
    end = window_end(day, "10:30")
    levels = stop_levels(day, 20.0, bars, None, "09:35")
    assert levels["pct_025"] == pytest.approx(20 * 0.9975)
    assert levels["pct_100"] == pytest.approx(19.8)
    assert levels["pct_150"] == pytest.approx(19.7)
    assert levels["bar"] == pytest.approx(13.0)
    assert levels["bars2"] == pytest.approx(12.0)
    assert levels["bars3"] == pytest.approx(11.0)
    assert levels["m15"] == pytest.approx(levels["bars3"])
    assert levels["m30"] == pytest.approx(11.0)
    assert levels["since"] == pytest.approx(11.0)
    assert levels["lod"] == pytest.approx(session_low_through(bars, end))
    assert levels["rma"] == pytest.approx(rma_value_at(bars, end))
    assert levels["rma"] < 20.0
    # No daily history, so the ATR stops are missing and the trade is skipped.
    skipped = evaluate_stop(
        entry=20.0, stop=levels["datr_010"], bars=bars, entry_end=end,
        daily=None, entry_day=pd.Timestamp(day), forward=[],
    )
    assert skipped["skipped"] == 1
    above = evaluate_stop(
        entry=20.0, stop=21.0, bars=bars, entry_end=end,
        daily=None, entry_day=pd.Timestamp(day), forward=[],
    )
    assert above["skipped"] == 1
    assert above["stop_price"] == pytest.approx(21.0)


def test_five_minute_atr_includes_the_1030_bar_and_not_the_one_after():
    day = "2026-10-16"
    stamps = list(pd.date_range("2026-10-15 09:35", periods=40, freq="5min"))
    bars = _frame(stamps, [10.0] * 40, lows=[9.0] * 40, highs=[11.0] * 40)
    # Replace the last two bars with the 10:30 and 10:35 clocks by rebuilding a known end.
    end = window_end(day, "10:30")
    later = end + pd.Timedelta(minutes=5)
    head = _frame(pd.date_range("2026-10-15 09:35", periods=20, freq="5min"), [10.0] * 20, lows=[9.0] * 20, highs=[11.0] * 20)
    mid = _frame(pd.date_range(f"{day} 09:35", periods=11, freq="5min"), [10.0] * 11, lows=[9.0] * 11, highs=[11.0] * 11)
    last = _frame([end, later], [10.0, 30.0], lows=[9.0, 1.0], highs=[11.0, 40.0])
    bars = pd.concat([head, mid, last])
    at_close = intraday_atr_at(bars, end, length=3)
    after = intraday_atr_at(bars.loc[bars.index <= later], later, length=3)
    assert at_close is not None and after is not None
    assert after != pytest.approx(at_close)


def test_a_touch_is_minus_one_r_a_gap_is_worse_and_slippage_hurts_a_tight_stop():
    day = "2026-10-16"
    end = window_end(day, "10:30")
    entry = 100.0
    stop = 99.75  # 0.25%
    touch_bar = end + pd.Timedelta(minutes=10)  # 10:40, inside 30 minutes
    bars = _frame(
        [end, touch_bar],
        [entry, 100.0],
        lows=[99.9, 99.5],
        highs=[100.2, 100.2],
        opens=[100.0, 99.9],
    )
    outcome = evaluate_stop(
        entry=entry, stop=stop, bars=bars, entry_end=end,
        daily=None, entry_day=pd.Timestamp(day), forward=[],
    )
    assert outcome["skipped"] == 0
    assert outcome["stopped"] == 1
    assert outcome["gapped"] == 0
    assert outcome["fast_stop"] == 1
    assert realized_lod_r(outcome, "d3") == pytest.approx(-1.0)
    slipped = slip_r(outcome, "d3")
    assert slipped < -1
    # 0.05% of a 0.25% stop is 0.2R of extra loss, before the stop itself is also scaled.
    assert slipped == pytest.approx((99.75 * (1 - 0.0005) - entry) / (entry - stop))

    late = end + pd.Timedelta(minutes=35)  # 11:05
    quiet = _frame(
        [end, end + pd.Timedelta(minutes=5), late],
        [entry, 100.0, 100.0],
        lows=[99.9, 99.9, 99.0],
        highs=[100.2, 100.2, 100.2],
        opens=[100.0, 100.0, 100.0],
    )
    later = evaluate_stop(
        entry=entry, stop=stop, bars=quiet, entry_end=end,
        daily=None, entry_day=pd.Timestamp(day), forward=[],
    )
    assert later["fast_stop"] == 0

    gap_bars = _frame(
        [end, end + pd.Timedelta(minutes=5)],
        [entry, 99.0],
        lows=[99.9, 98.0],
        highs=[100.2, 99.0],
        opens=[100.0, 98.5],
    )
    gapped = evaluate_stop(
        entry=entry, stop=stop, bars=gap_bars, entry_end=end,
        daily=None, entry_day=pd.Timestamp(day), forward=[],
    )
    assert gapped["gapped"] == 1
    assert realized_lod_r(gapped, "eod") < -1


def test_first_book_is_rank_order_and_a_bad_stop_does_not_backfill():
    day = "2026-10-16"
    # Prior closes at 50 keep the RMA up there. One bar pokes above, then the 10:30 close falls back under it.
    prior = _five("2026-10-15", "09:35", 25, 50.0, low=49.0)

    def today(closes: list[float], low_1030: float) -> pd.DataFrame:
        stamps = list(pd.date_range(f"{day} 09:35", periods=len(closes), freq="5min"))
        lows = [min(c, low_1030) for c in closes]
        lows[-1] = low_1030
        return pd.concat([prior, _frame(stamps, closes, lows=lows, highs=[c + 1 for c in closes], opens=closes)])

    bbb_closes = [51.0] + [40.0] * 11
    aaa_closes = [51.0] + [60.0] * 11
    intraday = {"AAA": today(aaa_closes, 58.0), "BBB": today(bbb_closes, 39.0)}
    leaders = [
        {"symbol": "AAA", "rule": "rma1030", "entry_price": 60.0, "cross_time": "09:35", "rank": 1},
        {"symbol": "BBB", "rule": "rma1030", "entry_price": 40.0, "cross_time": "09:35", "rank": 2},
    ]
    rows = sweeps_for_day(
        day, leaders, intraday, {"AAA": _daily(), "BBB": _daily()}, [day, "2026-10-19"],
        ranks={"BBB": 1, "AAA": 2},
    )
    first = [row for row in rows if row["slot"] == 1]
    assert {row["symbol"] for row in first} == {"BBB"}
    assert {row["symbol"] for row in rows if row["slot"] == 2} == {"AAA"}
    bbb_rma = next(row for row in first if row["stop_id"] == "rma")
    assert bbb_rma["skipped"] == 1
    assert bbb_rma["stop_price"] > 40.0
    stats = build_sweep_stats(rows)
    assert stats["books"]["first"]["stops"]["rma"]["n_fills"] == 0
    assert stats["books"]["first"]["stops"]["rma"]["n_skipped"] == 1
    assert stats["books"]["two"]["stops"]["rma"]["n_fills"] == 1
    lod = next(row for row in first if row["stop_id"] == "lod")
    assert lod["skipped"] == 0
    assert lod["stop_price"] == pytest.approx(39.0)


def _daily() -> pd.DataFrame:
    days = pd.bdate_range("2026-09-01", periods=30)
    return _frame(days, [10.0] * 30, lows=[9.0] * 30, highs=[11.0] * 30, opens=[10.0] * 30)


def test_ranking_picks_the_tightest_stop_near_the_best_r():
    def row(day, sid, slot, r, stop_pct, skipped=0):
        # A held winner: close percent = r * stop distance, never stopped.
        return {
            "date": day, "symbol": "AAA", "stop_id": sid, "slot": slot, "entry_price": 100.0,
            "stop_price": 100 - stop_pct, "stop_pct": stop_pct, "skipped": skipped,
            "eod_pct": r * stop_pct, "d1_pct": r * stop_pct, "d2_pct": r * stop_pct,
            "d3_pct": r * stop_pct, "d4_pct": r * stop_pct, "d5_pct": r * stop_pct,
            "stopped": 0, "stop_day": None, "exit_pct": None, "gapped": 0,
            "mfe_pct": abs(r * stop_pct) + 1, "fast_stop": 0,
        }

    rows = []
    for sid, r, width in (("pct_025", 1.08, 0.25), ("pct_050", 1.10, 0.50), ("lod", 0.85, 2.0)):
        rows.append(row("2026-10-01", sid, 1, r, width))
    # The other candidates have to exist so the book is complete. Give them a worse R.
    present = {sid for sid, _r, _w in (("pct_025", 0, 0), ("pct_050", 0, 0), ("lod", 0, 0))}
    for sid, _family, _label in CANDIDATES:
        if sid in present:
            continue
        rows.append(row("2026-10-01", sid, 1, -1.0, 1.0, skipped=1))
    stats = build_sweep_stats(rows)
    book = stats["books"]["first"]
    assert book["best_r"] == "pct_050"
    assert book["tight"] == "pct_025"
    assert book["order"][0] == "pct_050"
    assert book["stops"]["pct_025"]["horizons"]["d3"]["r_per_trade"] == pytest.approx(1.08)
    assert book["stops"]["pct_050"]["horizons"]["d3"]["slip_r_per_trade"] == pytest.approx(1.10)


def test_the_worked_example_skips_crwd_and_the_best_and_prefers_a_tied_winner():
    def fill(day, symbol, cross, rank, r, stop_pct=2.0):
        return {
            "date": day, "symbol": symbol, "rule": "rma1030", "cross_time": cross, "rank": rank,
            "entry_price": 100.0, "stop_price": 98.0, "stop_pct": stop_pct,
            "eod_pct": r * stop_pct, "d1_pct": r * stop_pct, "d2_pct": r * stop_pct,
            "d3_pct": r * stop_pct, "d4_pct": r * stop_pct, "d5_pct": r * stop_pct,
            "stopped": 0, "stop_day": None, "exit_pct": None, "gapped": 0, "mfe_pct": 1.0,
        }

    rows = [
        fill("2026-07-31", "CRWD", "09:35", 1, 21.0),
        fill("2026-07-31", "AAA", "09:35", 2, 0.2),
        fill("2026-08-03", "BBB", "09:35", 1, 0.9),
        fill("2026-08-03", "CCC", "09:35", 4, -1.0),
        fill("2026-08-04", "DDD", "09:40", 1, 0.84),
        fill("2026-08-05", "EEE", "09:35", 3, -1.0),
        fill("2026-08-05", "FFF", "10:00", 8, 0.1),
    ]
    ranks = {
        "2026-07-31": {"CRWD": 1, "AAA": 2},
        "2026-08-03": {"BBB": 1, "CCC": 4},
        "2026-08-04": {"DDD": 1},
        "2026-08-05": {"EEE": 3, "FFF": 8},
    }
    # Rank-tie first names: CRWD, BBB, DDD, EEE.
    picked = rank_first_candidates(rows, ranks)
    assert picked
    assert picked[0]["row"]["symbol"] == "BBB"
    assert picked[0]["row"]["symbol"] != "CRWD"
    assert picked[0]["best_symbol"] == "CRWD"
    assert all(item["row"]["symbol"] != "CRWD" for item in picked)


def test_stored_sweeps_round_trip_and_change_the_revision(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite3"
    monkeypatch.setattr("strat.config.CACHE_DB", db)
    before = revision(db)
    replace_stop_sweeps(
        "2026-10-16",
        [{
            "symbol": "AAA", "stop_id": "lod", "slot": 1, "entry_price": 10.0,
            "stop_price": 9.5, "stop_pct": 5.0, "eod_pct": 1.0, "d1_pct": None, "d2_pct": None,
            "d3_pct": None, "d4_pct": None, "d5_pct": None, "stopped": 0, "stop_day": None,
            "exit_pct": None, "gapped": 0, "mfe_pct": 1.0, "fast_stop": 0, "skipped": 0,
            "cross_time": "09:35",
        }],
        db,
    )
    stored = stop_sweeps_between("2026-10-01", "2026-10-31", db)
    assert stored[0]["symbol"] == "AAA"
    assert stored[0]["slot"] == 1
    assert "2026-10-16" in stop_sweep_days(db)
    assert revision(db) != before
