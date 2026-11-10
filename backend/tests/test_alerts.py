"""Pullback-to-rising-EMA alerts (120 / 240 / 480 on 15-minute bars): watch, trigger, outcome."""

from datetime import datetime, timedelta, timezone

import pytest

from strat.alerts import (
    MA_PERIODS,
    SETUP_NAMES,
    SETUPS,
    Context,
    Settings,
    advance_stored,
    context_from_closes,
    ema_series,
    metrics,
    simulate,
)

OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)  # 09:30 EDT


def rising(last: float, step: float = 0.01, n: int = 10) -> list[float]:
    return [round(last - step * (n - 1 - k), 4) for k in range(n)]


# The 120 EMA ends the prior session at 99.09 and rising; the prior close (101) is well above it.
CTX = Context(ma_tail={120: rising(99.09)}, prev_close=101.0)
TOUCH = (100.5, 100.8, 99.1, 100.2)  # dips to the 120 and closes back up


def bars(rows, start=OPEN):
    return [
        {"t": start + timedelta(minutes=15 * i), "o": o, "h": h, "l": l, "c": c, "v": 1000.0}
        for i, (o, h, l, c) in enumerate(rows)
    ]


def run(rows, ctx=CTX, settings=None, **kw):
    return simulate("AAA", "2026-10-23", bars(rows), ctx, settings or Settings(), **kw)


def test_setups_are_the_three_emas():
    assert MA_PERIODS == (120, 240, 480)
    assert SETUPS == ("120", "240", "480", "s120", "s240", "s480")
    assert SETUP_NAMES["240"] == "Pullback to rising 240 EMA"
    assert SETUP_NAMES["s240"] == "Short: rally to falling 240 EMA"


def test_touch_of_a_rising_120_is_a_watch_with_the_candle_high_as_trigger():
    [a] = run([TOUCH])
    assert a.setup == "120" and a.status == "pending" and not a.filled
    assert a.trigger == 100.81  # touch candle high + 1c
    assert a.stop == 99.80  # default stop: 1% under the buy
    assert a.fired_at == OPEN + timedelta(minutes=15)
    assert a.details["ma"] == pytest.approx(99.09 + 2 / 121 * (100.2 - 99.09), abs=1e-4)
    assert a.details["touched"] == [120]
    assert a.key == "AAA|2026-10-23|120|2026-10-23T13:30:00Z"


def test_next_candle_over_the_high_triggers():
    [a] = run([TOUCH, (100.2, 101.0, 100.1, 100.9)])
    assert a.status == "triggered" and a.filled
    assert a.fill_price == 100.81 and a.fill_at == OPEN + timedelta(minutes=15)


def test_a_gap_over_the_trigger_still_fills_at_the_candle_high_plus_a_cent():
    [a] = run([TOUCH, (101.3, 101.6, 101.2, 101.5)])
    assert a.status == "triggered" and a.fill_price == 100.81 == a.trigger


def test_a_short_gap_under_the_trigger_still_fills_at_the_candle_low_minus_a_cent():
    ctx = Context(ma_tail={120: list(reversed(rising(100.91)))}, prev_close=99.0)  # falling, price under it
    [a] = run([(99.5, 100.9, 99.2, 99.8), (98.7, 98.8, 98.5, 98.6)], ctx, side="short")
    assert a.status == "triggered" and a.trigger == 99.19 and a.fill_price == 99.19


def test_a_falling_ema_is_not_alerted():
    ctx = Context(ma_tail={120: list(reversed(rising(99.18)))}, prev_close=101.0)
    assert run([TOUCH], ctx) == []


def test_price_already_on_the_line_is_not_a_pullback():
    ctx = Context(ma_tail={120: rising(99.09)}, prev_close=99.1)
    assert run([TOUCH], ctx) == []


def test_a_close_through_the_ema_is_not_a_hold():
    assert run([(100.5, 100.8, 98.0, 98.5)]) == []
    # Inside the hold tolerance (0.3%) it still counts.
    assert len(run([(100.5, 100.8, 98.9, 98.9)])) == 1


def test_a_low_that_stays_above_the_ema_is_not_a_touch():
    assert run([(100.5, 100.8, 99.5, 100.2)]) == []


def test_the_lowest_ema_held_is_the_alert():
    ctx = Context(ma_tail={120: rising(100.0), 240: rising(99.0)}, prev_close=101.0)
    [a] = run([(100.6, 100.7, 98.95, 100.3)], ctx, settings=Settings(ma_240=1, ma_480=1))
    assert a.setup == "240" and a.details["touched"] == [120, 240]


def test_a_turned_off_ema_is_skipped():
    s = Settings(ma_120=0)
    assert run([TOUCH], settings=s) == []
    assert Settings().periods() == [120]


def test_trigger_follows_the_previous_candle_while_waiting():
    rows = [TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)]
    [a] = run(rows, settings=Settings(stop_mode=0))
    assert a.status == "triggered"
    # Bar 1 did not take out 100.81; its own high (100.60) + 1c became the buy stop, filled on bar 2.
    assert a.fill_price == 100.61 and a.fill_at == OPEN + timedelta(minutes=30)
    assert a.stop == 99.04  # the lower pullback low on bar 1
    assert a.setup_bar == OPEN + timedelta(minutes=15) and a.setup_high == 100.6
    assert a.fired_at == OPEN + timedelta(minutes=15)  # the watch time never moves


def test_the_fixed_stop_walks_with_the_buy_and_stays_one_percent():
    rows = [TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)]
    [a] = run(rows)
    assert a.fill_price == 100.61
    assert a.stop == round(100.61 * 0.99, 2)


def test_the_one_candle_stop_is_that_candle_only():
    rows = [TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)]
    [wide] = run(rows, settings=Settings(stop_mode=0))
    [candle] = run(rows, settings=Settings(stop_mode=1))
    assert wide.stop == 99.04  # touch low 99.10 and bar-1 low 99.05
    assert candle.stop == 99.04  # the signal candle's own low is the lower one here
    # A later candle with a higher low tightens the one-candle stop and leaves the widening stop down at the touch.
    higher = [TOUCH, (100.2, 100.4, 99.8, 100.3), (100.3, 100.5, 100.0, 100.45)]
    [wide2] = run(higher, settings=Settings(stop_mode=0))
    [candle2] = run(higher, settings=Settings(stop_mode=1))
    assert wide2.fill_price == candle2.fill_price == 100.41
    assert wide2.stop == 99.09
    assert candle2.stop == 99.79


def test_a_stop_wider_than_the_max_is_not_armed():
    skipped = []
    # The touch candle is about 1.7% wide, so a 1% cap skips it. A later tight pullback can still alert.
    assert run([TOUCH], settings=Settings(stop_mode=1, max_stop_pct=1), skipped=skipped) == []
    assert skipped[0]["reason"] == "stop wider than the max"


def test_a_close_under_the_ema_cancels_the_watch():
    [a] = run([TOUCH, (100.2, 100.3, 98.0, 98.2)])
    assert a.status == "cancelled" and a.exit_reason == "close_under_ma"


def test_the_watch_expires_without_a_trigger():
    quiet = (100.2, 100.5, 100.0, 100.3)
    [a] = run([TOUCH] + [quiet] * 4, settings=Settings(watch_bars=4))
    assert a.status == "expired" and a.exit_reason == "not_triggered"
    [b] = run([TOUCH] + [quiet] * 3, settings=Settings(watch_bars=4))
    assert b.status == "pending" and b.trigger == 100.51


def test_the_forming_bar_can_trigger_early():
    forming = {"t": OPEN + timedelta(minutes=15), "o": 100.3, "h": 100.9, "l": 100.2, "c": 100.85, "v": 10.0}
    [a] = run([TOUCH], forming=forming)
    assert a.status == "triggered" and a.fill_price == 100.81 and a.details["fill_on_forming_bar"]
    # Under the buy stop: still watching.
    [b] = run([TOUCH], forming=dict(forming, h=100.7))
    assert b.status == "pending"


def test_stop_and_break_even_after_the_fill():
    rows = [TOUCH, (100.2, 101.0, 100.1, 100.9), (100.9, 101.2, 100.8, 101.1), (101.1, 101.4, 101.0, 101.3),
            (101.3, 101.5, 101.2, 101.4), (101.4, 101.45, 100.7, 100.8)]
    [a] = run(rows, settings=Settings(breakeven_after_new_highs=3))
    assert a.breakeven_at is not None
    assert a.status == "breakeven" and a.exit_price == 100.81 and a.r_multiple == 0


def test_a_close_under_the_ema_exits_an_open_trade():
    ctx = Context(ma_tail={120: rising(98.5)}, prev_close=101.0)
    rows = [(100.5, 100.8, 98.5, 100.2), (100.2, 101.0, 100.1, 100.9), (100.9, 100.95, 98.55, 98.55)]
    # The last bar's low stays over the stop (98.49) but it closes under the EMA (~98.57).
    [a] = run(rows, ctx, settings=Settings(hold_pct=0, stop_mode=0, max_stop_pct=5))
    assert a.status == "exited" and a.exit_reason == "close_under_ma" and a.exit_price == 98.55
    [b] = run(rows, ctx, settings=Settings(hold_pct=0, exit_close_under_ma=0, stop_mode=0, max_stop_pct=5))
    assert b.status == "triggered"


def test_one_live_alert_per_name_and_a_cap_on_attempts():
    skipped = []
    alerts = run([TOUCH, TOUCH], skipped=skipped)
    assert len(alerts) == 1
    assert skipped and skipped[0]["reason"] == "an alert on this name is still live"
    # Cancelled, then a fresh pullback can alert again.
    rows = [TOUCH, (100.2, 100.3, 98.0, 98.2), (98.2, 101.2, 98.2, 101.1), (101.1, 101.2, 99.2, 100.4)]
    alerts = run(rows)
    assert [a.status for a in alerts] == ["cancelled", "pending"]


def test_nothing_on_the_last_bar_and_the_session_end_closes_out():
    ctx = Context(ma_tail=CTX.ma_tail, prev_close=101.0, session_bars=1)
    skipped = []
    assert run([TOUCH], ctx, skipped=skipped) == []
    assert skipped[0]["reason"] == "last bar of the session"
    ctx = Context(ma_tail=CTX.ma_tail, prev_close=101.0, session_bars=3)
    [a] = run([TOUCH, (100.2, 101.0, 100.1, 100.9), (100.9, 101.1, 100.8, 101.0)], ctx)
    assert a.status == "exited" and a.exit_reason == "session_end" and a.exit_price == 101.0


def test_context_from_closes_keeps_the_ema_tail_and_prior_close():
    closes = [100 + 0.01 * k for k in range(600)]
    ctx = context_from_closes(closes)
    assert ctx.prev_close == closes[-1]
    for p in MA_PERIODS:
        full = ema_series(closes, p)
        assert ctx.ma_tail[p][-1] == pytest.approx(full[-1])
        assert len(ctx.ma_tail[p]) == 30
    assert 480 not in context_from_closes(closes[:300]).ma_tail


def test_advance_stored_rewalks_from_the_stored_levels():
    b = bars([TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)])
    a = advance_stored(
        symbol="AAA", session="2026-10-23", setup="120", origin_bar=b[0]["t"], setup_bar=b[1]["t"],
        trigger=100.61, stop=99.04, setup_low=99.05, setup_high=100.6, ref_price=100.2, bars=b, ctx=CTX,
    )
    assert a.status == "triggered" and a.fill_price == 100.61 and a.bars_waited == 2


def test_old_setting_keys_are_ignored():
    s = Settings.from_mapping({"bunched_pct": 0.7, "min_score": 80, "max_symbols": 80, "watch_bars": 6})
    assert s.max_symbols == 80 and s.watch_bars == 6 and not hasattr(s, "bunched_pct") and not hasattr(s, "min_score")


def test_metrics_group_by_daily_setup_and_count_an_alert_under_each():
    both = {
        "filled": True,
        "r_multiple": 1.5,
        "details": {"daily_setups": [
            {"kind": "episodic-pivot", "label": "Episodic Pivot", "side": "long"},
            {"kind": "flat-base-breakout", "label": "Flat Base Breakout", "side": "long"},
        ]},
    }
    lost = {
        "filled": True,
        "r_multiple": -1.0,
        "details": {"daily_setups": [{"kind": "flat-base-breakout", "label": "Flat Base Breakout", "side": "long"}]},
    }
    waiting = {"filled": False, "r_multiple": None, "details": {"daily_setups": ["Delayed High Volume Close"]}}
    short10 = {
        "filled": True,
        "r_multiple": 2.0,
        "details": {"daily_setups": [{"kind": "ma-overcut-fail", "label": "MA Overcut and Fail (10-day)", "side": "short", "period": 10}]},
    }
    short20 = {
        "filled": True,
        "r_multiple": -1.0,
        "details": {"daily_setups": [{"kind": "ma-overcut-fail", "label": "MA Overcut and Fail (20-day)", "side": "short", "period": 20}]},
    }
    old = {"filled": False, "r_multiple": None, "details": {}}
    by = {m["setup"]: m for m in metrics([both, lost, waiting, short10, short20, old])}
    assert by["episodic-pivot"]["count"] == 1 and by["episodic-pivot"]["name"] == "Episodic Pivot"
    assert by["episodic-pivot"]["side"] == "long"
    # The alert that also has an episodic pivot is counted here too, and once in All.
    assert by["flat-base-breakout"]["count"] == 2 and by["flat-base-breakout"]["total_r"] == 0.5
    assert by["flat-base-breakout"]["win_rate"] == 50.0
    assert by["delayed-hvc"]["count"] == 1 and by["delayed-hvc"]["fill_rate"] == 0.0
    assert by["ma-overcut-fail:10"]["name"] == "MA Overcut and Fail (10-day)" and by["ma-overcut-fail:10"]["side"] == "short"
    assert by["ma-overcut-fail:20"]["total_r"] == -1.0
    assert "ma-overcut-fail" not in by
    assert by["unknown"]["count"] == 1 and by["unknown"]["name"] == "Unknown"
    assert by["All"]["count"] == 6 and by["All"]["side"] is None
    assert by["All"]["total_r"] == 1.5
    assert [m["setup"] for m in metrics([])] == ["All"]


def test_a_watchlist_tag_is_its_own_metrics_row():
    row = {"filled": True, "r_multiple": 1.0, "details": {"daily_setups": [
        {"kind": "watchlist", "label": "Watchlist", "side": "long"},
    ]}}
    by = {m["setup"]: m for m in metrics([row])}
    assert by["watchlist"]["name"] == "Watchlist" and by["watchlist"]["side"] == "long"
    assert by["watchlist"]["count"] == 1 and by["All"]["count"] == 1



# --- short side: the exact mirror -----------------------------------------------------------------------------------
#
# Reflect every price around $200 (p -> 200 - p; high and low swap). EMAs are linear, so the reflected chart's EMAs
# are the reflected EMAs: a pullback to a rising EMA becomes a rally into a falling one, and the short engine must
# give the same outcome with mirrored levels.

C = 200.0


def _reflect_rows(rows):
    return [(C - o, C - l, C - h, C - c) for o, h, l, c in rows]


def _reflect_ctx(ctx):
    return Context(
        ma_tail={p: [C - v for v in tail] for p, tail in ctx.ma_tail.items()},
        prev_close=None if ctx.prev_close is None else C - ctx.prev_close,
        session_bars=ctx.session_bars,
    )


_STEP = (100.2, 101.0, 100.1, 100.9)
_SCENARIOS = {
    "watch": ([TOUCH], CTX, Settings(stop_mode=0)),
    "trigger": ([TOUCH, _STEP], CTX, Settings(stop_mode=0)),
    "trigger follows the candle": ([TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)], CTX, Settings(stop_mode=0)),
    "cancel": ([TOUCH, (100.2, 100.3, 98.0, 98.2)], CTX, Settings(stop_mode=0)),
    "expire": ([TOUCH] + [(100.2, 100.5, 100.0, 100.3)] * 4, CTX, Settings(stop_mode=0, watch_bars=4)),
    "break-even stop": (
        [TOUCH, _STEP, (100.9, 101.2, 100.8, 101.1), (101.1, 101.4, 101.0, 101.3), (101.3, 101.5, 101.2, 101.4),
         (101.4, 101.45, 100.7, 100.8)],
        CTX, Settings(stop_mode=0, breakeven_after_new_highs=3),
    ),
    "exit on a close through the EMA": (
        [(100.5, 100.8, 98.5, 100.2), _STEP, (100.9, 100.95, 98.55, 98.55)],
        Context(ma_tail={120: rising(98.5)}, prev_close=101.0), Settings(stop_mode=0, hold_pct=0, max_stop_pct=5),
    ),
    "stop": ([TOUCH, _STEP, (100.9, 100.95, 98.9, 99.0)], CTX, Settings(stop_mode=0)),
}


@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_short_alerts_mirror_long_alerts(name):
    rows, ctx, settings = _SCENARIOS[name]
    longs = simulate("AAA", "2026-10-23", bars(rows), ctx, settings)
    shorts = simulate("AAA", "2026-10-23", bars(_reflect_rows(rows)), _reflect_ctx(ctx), settings, side="short")
    assert longs, "the long scenario must alert"
    assert len(shorts) == len(longs)
    exits = {"close_under_ma": "close_over_ma"}
    for lo, sh in zip(longs, shorts):
        assert sh.setup == "s" + lo.setup and sh.side == "short"
        assert (sh.status, sh.filled) == (lo.status, lo.filled)
        assert sh.exit_reason == exits.get(lo.exit_reason, lo.exit_reason)
        assert sh.trigger == pytest.approx(C - lo.trigger)
        assert sh.stop == pytest.approx(C - lo.stop)
        if lo.filled:
            assert sh.fill_price == pytest.approx(C - lo.fill_price)
        if lo.r_multiple is not None:
            assert sh.r_multiple == pytest.approx(lo.r_multiple)


def test_a_short_rally_into_a_rising_ema_is_not_alerted():
    assert simulate("AAA", "2026-10-23", bars(_reflect_rows([TOUCH])), CTX, Settings(), side="short") == []


def test_short_alert_names_have_a_short_daily_setup_weakest_first():
    from strat.api import alert_short_symbols

    short_d = {"tf": "D", "kind": "ma-overcut-fail", "label": "MA Overcut and Fail (20-day)", "side": "short"}
    long_d = {"tf": "D", "kind": "flat-base-breakout", "label": "Flat Base Breakout", "side": "long"}
    off = {"tf": "D", "kind": "ema-crossback-short", "label": "EMA Crossback Short", "side": "short"}
    open_gate = Settings(theme_gate=0)

    def r(sym, rs, setups, kind="stock"):
        return {"symbol": sym, "rs": rs, "kind": kind, "in_universe": True, "setups": setups, "avg_dollar_volume": 50_000_000, "atr_pct": 5.0}

    rows = [
        r("AAA", 0.08, [short_d]), r("BBB", 0.02, [short_d]), r("CCC", 0.90, [short_d]),  # any RS
        r("DDD", 0.05, [long_d]), r("EEE", 0.01, [short_d], kind="etf"), r("FFF", 0.01, [short_d], kind="theme"),
        r("GGG", 0.01, [off]),
    ]
    assert alert_short_symbols(rows, open_gate) == ["EEE", "BBB", "AAA", "CCC"]
    assert alert_short_symbols(rows, Settings(theme_gate=0, max_short_symbols=2)) == ["EEE", "BBB"]
    assert alert_short_symbols(rows, Settings(theme_gate=0, shorts=0)) == []
    assert alert_short_symbols(rows, Settings(theme_gate=0, short_ma20=0)) == []


def test_the_theme_gate_keeps_the_outer_band_and_pending_is_optional():
    from strat.api import alert_short_symbols, alert_symbols

    long_d = {"tf": "D", "kind": "ema-crossback", "label": "EMA Crossback", "side": "long", "triggered": False}
    short_d = {"tf": "D", "kind": "ma-overcut-fail", "label": "MA Overcut and Fail (10-day)", "side": "short"}

    def r(sym, rank, setups, score=80, rs=0.5):
        return {
            "symbol": sym, "kind": "stock", "score": score, "rs": rs, "setups": setups,
            "avg_dollar_volume": 50_000_000, "atr_pct": 5.0, "atr_pct": 5.0,
            "theme_strength": {"rank": rank, "total": 4},
        }

    rows = [
        r("TOP", 1, [long_d], score=10), r("MID", 2, [long_d], score=99),
        r("BOT", 4, [short_d], rs=0.2), r("NO", 3, [short_d], rs=0.01),
    ]
    # 25% of 4 themes is 1 slot. Longs: rank 1. Shorts: rank 4.
    assert alert_symbols(rows, Settings()) == ["TOP"]
    assert alert_short_symbols(rows, Settings()) == ["BOT"]
    assert alert_symbols(rows, Settings(theme_top_pct=50)) == ["MID", "TOP"]
    triggered = {**long_d, "triggered": True}
    assert alert_symbols([r("TOP", 1, [triggered])], Settings(long_pending_only=1)) == []
    assert alert_symbols([r("TOP", 1, [triggered])], Settings()) == ["TOP"]


def test_dollar_volume_and_atr_screen_names_before_the_cap():
    from strat.alerts import passes_name_screen
    from strat.api import alert_short_symbols, alert_symbols

    setup = {"tf": "D", "kind": "ema-crossback", "label": "EMA Crossback", "side": "long", "triggered": False}
    short = {"tf": "D", "kind": "flat-base-breakdown", "label": "Flat Base Breakdown", "side": "short"}

    def row(sym, score, volume, atr=None, setups=None, rs=0.2):
        return {
            "symbol": sym, "kind": "stock", "score": score, "rs": rs, "setups": setups if setups is not None else [setup],
            "avg_dollar_volume": volume, "atr_pct": atr,
            "theme_strength": {"rank": 1, "total": 4},
        }

    thin = row("THIN", 99, 5_000_000, 4)
    liquid = row("LIQ", 40, 20_000_000, 4)
    quiet = row("QUIET", 80, 20_000_000, 0.5)
    wild = row("WILD", 70, 20_000_000, 15)
    missing = row("MISS", 60, 20_000_000, None)
    at_floor = row("FLOOR", 95, 20_000_000, 3.0)
    just_over = row("OVER", 30, 20_000_000, 3.01)
    # Default: $10M minimum, ATR slider Any, hard ATR floor > 3%. The thin name is dropped before the cap of 1.
    assert alert_symbols([thin, liquid], Settings(max_symbols=1)) == ["LIQ"]
    assert passes_name_screen(liquid, Settings())
    assert not passes_name_screen(thin, Settings())
    assert passes_name_screen(wild, Settings())  # 12%+ is no upper limit
    # The floor is strict and applies even with the slider at Any: 3% or less, or no ATR yet, is out.
    assert not passes_name_screen(missing, Settings())
    assert not passes_name_screen(quiet, Settings())
    assert not passes_name_screen(at_floor, Settings())
    assert passes_name_screen(just_over, Settings())
    assert alert_symbols([at_floor, just_over, quiet, liquid], Settings()) == ["LIQ", "OVER"]
    tight = Settings(atr_pct_min=2, atr_pct_max=6)
    assert alert_symbols([liquid, quiet, wild, missing], tight) == ["LIQ"]
    assert passes_name_screen(wild, Settings(atr_pct_min=0, atr_pct_max=12))
    short_row = row("SH", 10, 5_000_000, 4, setups=[short], rs=0.05)
    short_ok = row("OK", 10, 30_000_000, 4, setups=[short], rs=0.1)
    for r in (short_row, short_ok):
        r["theme_strength"] = {"rank": 4, "total": 4}
    assert alert_short_symbols([short_row, short_ok], Settings(short_flat=1)) == ["OK"]


def test_open_r_is_for_triggered_trades_still_open():
    from strat.alerts import open_r

    long_row = {"setup": "120", "status": "triggered", "filled": 1, "fill_price": 101.0, "stop_price": 100.0}
    assert open_r(long_row, 102.5) == pytest.approx(1.5)
    assert open_r(long_row, 100.5) == pytest.approx(-0.5)
    assert open_r(long_row, None) is None
    assert open_r({**long_row, "status": "stopped"}, 102.5) is None  # closed: its R is the exit R
    assert open_r({**long_row, "status": "pending", "filled": 0}, 102.5) is None
    short_row = {"setup": "s240", "status": "triggered", "filled": 1, "fill_price": 50.0, "stop_price": 51.0}
    assert open_r(short_row, 48.0) == pytest.approx(2.0)


def test_no_alert_or_entry_after_noon_eastern():
    from strat.alerts import trade_cutoff

    # Noon ET year-round: 17:00 UTC under EST, 16:00 UTC under EDT.
    assert trade_cutoff(datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)) == datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)
    assert trade_cutoff(OPEN) == datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)

    cutoff = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
    go = (100.2, 101.0, 100.1, 100.9)
    # A touch bar that closes exactly at the cutoff still alerts and can fill on the forming bar before it.
    [a] = simulate("AAA", "2026-10-23", bars([TOUCH], start=cutoff - timedelta(minutes=15)), CTX, Settings())
    assert a.status == "pending"
    # ...but a bar that starts at the cutoff cannot fill it: the watch expires at the cutoff.
    [b] = simulate("AAA", "2026-10-23", bars([TOUCH, go], start=cutoff - timedelta(minutes=15)), CTX, Settings())
    assert b.status == "expired" and b.exit_reason == "trade_window" and not b.filled and b.exit_at == cutoff
    forming = {"t": cutoff, "o": 100.3, "h": 100.9, "l": 100.2, "c": 100.85, "v": 10.0}
    [c] = simulate("AAA", "2026-10-23", bars([TOUCH], start=cutoff - timedelta(minutes=15)), CTX, Settings(), forming=forming)
    assert c.status == "pending" and not c.filled
    # A touch at or after the cutoff is not alerted.
    skipped = []
    assert simulate("AAA", "2026-10-23", bars([TOUCH], start=cutoff), CTX, Settings(), skipped=skipped) == []
    assert skipped[0]["reason"] == "after the 12:00 ET trade cutoff"
    # A trade filled before the cutoff is still managed after it.
    [d] = simulate("AAA", "2026-10-23", bars([TOUCH, go, (100.9, 101.1, 99.5, 99.6)], start=cutoff - timedelta(minutes=30)), CTX, Settings())
    assert d.filled and d.status == "stopped"
