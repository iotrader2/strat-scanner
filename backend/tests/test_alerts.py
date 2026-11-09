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
    assert a.stop == 99.09  # pullback low - 1c
    assert a.fired_at == OPEN + timedelta(minutes=15)
    assert a.details["ma"] == pytest.approx(99.09 + 2 / 121 * (100.2 - 99.09), abs=1e-4)
    assert a.details["touched"] == [120]
    assert a.key == "AAA|2026-10-23|120|2026-10-23T13:30:00Z"


def test_next_candle_over_the_high_triggers():
    [a] = run([TOUCH, (100.2, 101.0, 100.1, 100.9)])
    assert a.status == "triggered" and a.filled
    assert a.fill_price == 100.81 and a.fill_at == OPEN + timedelta(minutes=15)


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
    [a] = run([(100.6, 100.7, 98.95, 100.3)], ctx)
    assert a.setup == "240" and a.details["touched"] == [120, 240]


def test_a_turned_off_ema_is_skipped():
    s = Settings(ma_120=0)
    assert run([TOUCH], settings=s) == []
    assert Settings().periods() == [120, 240, 480]


def test_trigger_follows_the_previous_candle_while_waiting():
    rows = [TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)]
    [a] = run(rows)
    assert a.status == "triggered"
    # Bar 1 did not take out 100.81; its own high (100.60) + 1c became the buy stop, filled on bar 2.
    assert a.fill_price == 100.61 and a.fill_at == OPEN + timedelta(minutes=30)
    assert a.stop == 99.04  # the lower pullback low on bar 1
    assert a.setup_bar == OPEN + timedelta(minutes=15) and a.setup_high == 100.6
    assert a.fired_at == OPEN + timedelta(minutes=15)  # the watch time never moves


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
    [a] = run(rows, ctx, settings=Settings(hold_pct=0))
    assert a.status == "exited" and a.exit_reason == "close_under_ma" and a.exit_price == 98.55
    [b] = run(rows, ctx, settings=Settings(hold_pct=0, exit_close_under_ma=0))
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


def test_metrics_by_ema():
    rows = [
        {"setup": "120", "filled": True, "r_multiple": 1.5},
        {"setup": "120", "filled": True, "r_multiple": -1.0},
        {"setup": "240", "filled": False, "r_multiple": None},
    ]
    by = {m["setup"]: m for m in metrics(rows)}
    assert by["120"]["win_rate"] == 50.0 and by["120"]["total_r"] == 0.5
    assert by["240"]["fill_rate"] == 0.0
    assert by["All"]["count"] == 3 and by["480"]["count"] == 0



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
    "watch": ([TOUCH], CTX, Settings()),
    "trigger": ([TOUCH, _STEP], CTX, Settings()),
    "trigger follows the candle": ([TOUCH, (100.2, 100.6, 99.05, 100.3), (100.3, 100.65, 100.2, 100.5)], CTX, Settings()),
    "cancel": ([TOUCH, (100.2, 100.3, 98.0, 98.2)], CTX, Settings()),
    "expire": ([TOUCH] + [(100.2, 100.5, 100.0, 100.3)] * 4, CTX, Settings(watch_bars=4)),
    "break-even stop": (
        [TOUCH, _STEP, (100.9, 101.2, 100.8, 101.1), (101.1, 101.4, 101.0, 101.3), (101.3, 101.5, 101.2, 101.4),
         (101.4, 101.45, 100.7, 100.8)],
        CTX, Settings(breakeven_after_new_highs=3),
    ),
    "exit on a close through the EMA": (
        [(100.5, 100.8, 98.5, 100.2), _STEP, (100.9, 100.95, 98.55, 98.55)],
        Context(ma_tail={120: rising(98.5)}, prev_close=101.0), Settings(hold_pct=0),
    ),
    "stop": ([TOUCH, _STEP, (100.9, 100.95, 98.9, 99.0)], CTX, Settings()),
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

    short_d = {"tf": "D", "kind": "flat-base-short", "label": "Flat Base Breakdown", "side": "short"}
    long_d = {"tf": "D", "kind": "flat-base", "label": "Flat Base Breakout", "side": "long"}

    def r(sym, rs, setups, kind="stock"):
        return {"symbol": sym, "rs": rs, "kind": kind, "in_universe": True, "setups": setups}

    rows = [
        r("AAA", 0.08, [short_d]), r("BBB", 0.02, [short_d]), r("CCC", 0.90, [short_d]),  # any RS
        r("DDD", 0.05, [long_d]), r("EEE", 0.01, [short_d], kind="etf"), r("FFF", 0.01, [short_d], kind="theme"),
    ]
    assert alert_short_symbols(rows, Settings()) == ["EEE", "BBB", "AAA", "CCC"]
    assert alert_short_symbols(rows, Settings(max_short_symbols=2)) == ["EEE", "BBB"]
    assert alert_short_symbols(rows, Settings(shorts=0)) == []
