"""Setup detection (A-F) and outcome tracking on hand-built 5-minute bars."""

from datetime import datetime, timedelta, timezone

import pytest

from strat import alerts
from strat.alerts import Alert, Context, Frame, Settings, simulate, step

OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)  # 09:30 ET = 6:30 Phoenix


def bars(rows, v=1000.0):
    out = []
    for i, r in enumerate(rows):
        o, h, l, c = r[:4]
        out.append({"t": OPEN + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c, "v": r[4] if len(r) > 4 else v})
    return out


def ctx(warm=100.0, n=60, **kw):
    warm_closes = warm if isinstance(warm, list) else [warm] * n
    return Context(warm_closes=warm_closes, **kw)


def run(rows, c=None, settings=None, skipped=None):
    return simulate("TEST", "2026-10-23", bars(rows), c or ctx(), settings, skipped)


def by_setup(found, setup):
    return [a for a in found if a.setup == setup]


# ------------------------------------------------------------------ common rules


def test_setup_bar_green_or_high_closing_doji():
    s = Settings()
    assert alerts.setup_bar_ok({"o": 10, "h": 11, "l": 9, "c": 10.5}, s)
    # Doji: body 0.1 of a 2.0 range (5%), closing at 80% of the range.
    assert alerts.setup_bar_ok({"o": 10.7, "h": 11, "l": 9, "c": 10.6}, s)
    # Doji closing low (30% of range) is not enough.
    assert not alerts.setup_bar_ok({"o": 9.7, "h": 11, "l": 9, "c": 9.6}, s)
    # Red with a real body.
    assert not alerts.setup_bar_ok({"o": 10.8, "h": 11, "l": 9, "c": 10.0}, s)


def test_bunched_threshold():
    s = Settings()
    assert alerts.bunched((100, 100.3, 100.49), s)
    assert not alerts.bunched((100, 100.3, 100.6), s)


def test_ema_matches_watch5m_definition():
    from strat import watch5m

    vals = [100 + (i % 7) * 0.3 for i in range(80)]
    assert alerts.ema_series(vals, 20) == watch5m.ema_series(vals, 20)


# ------------------------------------------------------------------ A


def test_a_opening_bar_breakout_levels_and_fill():
    found = run([(100, 101, 99.9, 100.9), (100.9, 101.3, 100.8, 101.2)])
    a = by_setup(found, "A")[0]
    assert (a.trigger, a.stop) == (101.01, 99.89)
    assert a.setup_index == 0 and a.fired_at == OPEN + timedelta(minutes=5)
    assert a.status == "triggered" and a.fill_price == 101.01


def test_a_wide_bar_uses_two_percent_stop():
    found = run([(100, 103, 99.9, 102.8)])
    a = by_setup(found, "A")[0]
    assert a.trigger == 103.01
    assert a.stop == round(103.01 * 0.98, 2)
    assert a.details["a_stop_capped"] is True


def test_a_needs_close_in_top_30_and_over_emas():
    assert not by_setup(run([(100, 101, 99.9, 100.5)]), "A")  # closes mid-range
    assert not by_setup(run([(100, 101, 99.9, 100.9)], ctx(warm=102.0)), "A")  # under the EMAs


def test_volume_filter_applies_to_a(tmp_path):
    skipped = []
    c = ctx(vol_avg={0: 2000.0}, vol_sessions=20)
    assert not run([(100, 101, 99.9, 100.9, 1000)], c, skipped=skipped)
    assert skipped[0]["setup"] == "A" and "volume" in skipped[0]["reason"]
    # 0.8x is enough.
    assert by_setup(run([(100, 101, 99.9, 100.9, 1600)], c), "A")


def test_volume_filter_off_with_too_little_history():
    c = ctx(vol_avg={0: 2000.0}, vol_sessions=3)
    assert by_setup(run([(100, 101, 99.9, 100.9, 10)], c), "A")


# ------------------------------------------------------------------ C (checked first)


def test_c_drive_second_bar_closes_over_opening_high():
    # Under the EMAs, so no A; a strong green opening bar, then bar 2 closes over its high.
    found = run([(100, 101, 99.9, 100.9), (100.9, 101.6, 100.8, 101.5)], ctx(warm=102.0))
    c = by_setup(found, "C")[0]
    assert c.details["variant"] == "drive" and c.setup_index == 1
    assert (c.trigger, c.stop) == (101.61, 100.79)


def test_c_tight_run_rearms_on_the_last_tight_bar():
    rows = [
        (100, 102, 99.9, 101.9),  # strong opening bar, range 2.1
        (101.8, 102.0, 101.5, 101.9),  # tight, closes over the 6 EMA
        (101.9, 101.95, 101.6, 101.92),  # tight again: entry moves here
    ]
    found = run(rows)
    cs = by_setup(found, "C")
    assert len(cs) == 1
    c = cs[0]
    assert c.details["variant"] == "tight" and c.details["rearmed"] == 1
    assert c.setup_index == 2 and (c.trigger, c.stop) == (101.96, 101.59)
    assert c.origin_bar == OPEN + timedelta(minutes=5)  # key stays on the first tight bar


def test_c_is_checked_before_other_setups():
    # Bar 1 would also be a B (dip under the open, green reclaim of bunched EMAs) but C wins the tag.
    rows = [(100, 100.6, 99.7, 100.55), (100.5, 100.8, 100.45, 100.75)]
    found = run(rows, ctx(warm=100.6))
    assert {a.setup for a in found if a.setup_index == 1} == {"C"}


# ------------------------------------------------------------------ B


def test_b_flush_then_reclaim_of_bunched_emas():
    rows = [(100, 100.3, 99.5, 99.8), (99.8, 100.4, 99.7, 100.35)]
    found = run(rows, ctx(prev_close=101.0))
    b = by_setup(found, "B")
    assert len(b) == 1 and b[0].setup_index == 1
    assert (b[0].trigger, b[0].stop) == (100.41, 99.69)


def test_b_only_the_first_reclaim():
    rows = [(100, 100.3, 99.5, 99.8), (99.8, 100.4, 99.7, 100.35), (100.3, 100.35, 99.9, 99.95), (99.95, 100.5, 99.9, 100.45)]
    found = run(rows, ctx(prev_close=101.0))
    assert len(by_setup(found, "B")) == 1


def test_b_needs_bunched_emas():
    # EMAs spread: warm closes ramp from 95 to 100, so the 50 sits far under the 6.
    warm = [95 + i * 5 / 59 for i in range(60)]
    rows = [(100, 100.3, 99.5, 99.8), (99.8, 100.6, 99.7, 100.55)]
    assert not by_setup(run(rows, ctx(warm=warm, prev_close=101.0)), "B")


def test_b_premarket_dip_counts():
    # The regular bars never trade under the open or the prior close; the premarket low did.
    rows = [(100, 100.2, 100.0, 100.0), (100.0, 100.4, 100.0, 100.35)]
    assert not by_setup(run(rows, ctx(prev_close=99.0)), "B")
    assert by_setup(run(rows, ctx(prev_close=99.0, premarket_low=98.5)), "B")


# ------------------------------------------------------------------ D


def _build(rows_fn, c):
    """Build bars one at a time so a bar can be placed against the EMAs of the bars before it."""
    rows = []
    for k in range(40):
        nxt = rows_fn(k, rows, c)
        if nxt is None:
            break
        rows.append(nxt)
    return rows


def test_d_pullback_to_rising_20_then_close_back_over_6():
    warm = [90 + i * 10 / 59 for i in range(60)]  # a steady uptrend: 6 > 20 > 50, all rising
    c = ctx(warm=warm)

    def nxt(k, rows, c):
        last = rows[-1][3] if rows else 100.0
        if k < 6:  # keep trending (small red-ish bars so nothing else tags)
            return (last, last + 0.45, last - 0.05, last + 0.2)
        f = Frame(bars(rows + [(last, last, last, last)]), c)
        if k in (6, 7):  # pull back: low touches the 20 EMA, close holds above it
            e20 = f.e20[-1]
            return (last, last + 0.02, e20, max(e20 + 0.05, last - 0.35))
        if k == 8:
            return (last, last + 0.8, last - 0.02, last + 0.7)
        return None

    rows = _build(nxt, c)
    found = run(rows, c)
    d = by_setup(found, "D")
    assert d and d[0].setup_index == 8


def test_d_needs_stacked_emas():
    c = ctx(warm=100.0)
    rows = [(100, 100.1, 99.9, 100)] * 8 + [(100, 100.5, 99.95, 100.4)]
    assert not by_setup(run(rows, c), "D")


# ------------------------------------------------------------------ E


E_ROWS = [
    (103.0, 103.2, 102.0, 102.2),
    (102.2, 102.3, 101.5, 101.6),
    (101.6, 102.0, 101.0, 101.9),  # session low
    (101.9, 102.1, 101.5, 101.7),
    (101.7, 101.9, 101.3, 101.8),  # higher low
    (101.8, 102.1, 101.6, 102.0),
    (102.0, 103.4, 101.9, 103.3),  # first green close over the 20 EMA
]


def test_e_gap_down_higher_low_then_close_over_20():
    found = run(E_ROWS, ctx(warm=103.0, prev_close=105.0))
    e = by_setup(found, "E")
    assert len(e) == 1 and e[0].setup_index == 6 and e[0].details["variant"] == "gap"


def test_e_needs_gap_or_washout():
    rows = [(102.0, 102.2, 101.9, 102.1)] + E_ROWS[1:]
    rows[1] = (102.1, 102.2, 101.7, 101.8)
    rows[2] = (101.8, 102.0, 101.6, 101.9)
    # Open is level with the prior close, and the low never becomes a higher-low V under the averages.
    assert not by_setup(run(rows, ctx(warm=103.0, prev_close=102.0)), "E")


def test_e_washout_far_below_20_and_50_then_reclaims_20():
    # Flat open (no gap). The low is well under the 20 and the 50, a higher low holds, then the first close back over the 20.
    rows = [
        (110.0, 110.4, 107.0, 107.4),
        (107.4, 107.6, 103.0, 103.4),
        (103.4, 103.8, 100.0, 101.2),  # session low
        (101.2, 104.0, 101.0, 103.5),  # bounce
        (103.5, 103.8, 100.6, 101.4),  # higher low
        (101.4, 106.0, 101.2, 105.0),
        (105.0, 108.4, 106.6, 108.2),  # first close back over the 20, stop inside 2%
    ]
    found = run(rows, ctx(warm=110.0, prev_close=110.0))
    e = by_setup(found, "E")
    assert len(e) == 1 and e[0].setup_index == 6 and e[0].details["variant"] == "washout"


def test_e_gap_up_opening_wick_is_not_a_v():
    # RBRK 2026-10-26, 6:30-7:00 Phoenix. Prior close 128.74, open 132.03 (gap up).
    # The 6:30 wick to 130 is still above the 20/50. The 7:00 bar is a chop, not a V reclaim.
    rows = [
        (132.03, 132.88, 130.00, 132.71),
        (132.94, 133.26, 131.65, 132.76),
        (132.79, 133.61, 131.93, 133.53),
        (133.34, 133.60, 132.56, 132.79),
        (132.63, 133.30, 132.00, 132.78),
        (132.61, 133.25, 132.31, 132.31),
        (132.14, 133.22, 132.00, 132.97),
    ]
    assert not by_setup(run(rows, ctx(warm=129.0, prev_close=128.74)), "E")


# ------------------------------------------------------------------ F


def test_f_midday_squeeze_breakout_on_heavy_volume():
    flat = [(100.0, 100.05, 99.95, 100.0)] * 30
    breakout = (100.0, 100.7, 99.98, 100.65, 3000)
    avg = {i: 1000.0 for i in range(78)}
    found = run(flat + [breakout], ctx(vol_avg=avg, vol_sessions=20))
    f = by_setup(found, "F")
    assert len(f) == 1 and f[0].setup_index == 30


def test_f_needs_heavy_volume_and_two_hours_of_bunching():
    flat = [(100.0, 100.05, 99.95, 100.0)] * 30
    avg = {i: 1000.0 for i in range(78)}
    assert not by_setup(run(flat + [(100.0, 100.7, 99.98, 100.65, 1200)], ctx(vol_avg=avg, vol_sessions=20)), "F")
    assert not by_setup(run(flat + [(100.0, 100.7, 99.98, 100.65, 3000)], ctx()), "F")  # no volume history
    short = [(100.0, 100.05, 99.95, 100.0)] * 20
    assert not by_setup(run(short + [(100.0, 100.7, 99.98, 100.65, 3000)], ctx(vol_avg=avg, vol_sessions=20)), "F")


# ------------------------------------------------------------------ stop width, attempts, duplicates


def test_skip_when_stop_over_two_percent_except_a():
    skipped = []
    rows = [(100, 101, 99.9, 100.9), (100.9, 103.5, 100.8, 103.4)]  # C drive bar 2.7% tall
    found = run(rows, ctx(warm=102.0), skipped=skipped)
    assert not by_setup(found, "C")
    assert skipped and skipped[0]["setup"] == "C" and "stop" in skipped[0]["reason"]


def _forced(monkeypatch, tags):
    monkeypatch.setattr(alerts, "tag_bar", lambda f, i, s: tags.get(i))


def test_max_two_triggered_attempts(monkeypatch):
    _forced(monkeypatch, {0: ("A", "x"), 2: ("D", "x"), 4: ("E", "x"), 5: ("F", "x")})
    rows = [
        (100, 100.5, 99.9, 100.4),
        (100.4, 100.6, 100.3, 100.5),  # fills A
        (100.5, 100.7, 100.45, 100.65),
        (100.65, 100.9, 100.6, 100.85),  # fills D
        (100.85, 100.95, 100.8, 100.9),
        (100.9, 101.0, 100.85, 100.95),
    ]
    found = run(rows, ctx(warm=99.0))
    assert [a.setup for a in found] == ["A", "D"]  # E and F not alerted: two have triggered


def test_pending_alert_expires_once_two_have_triggered(monkeypatch):
    _forced(monkeypatch, {0: ("A", "x"), 1: ("D", "x"), 2: ("E", "x")})
    rows = [
        (100, 100.5, 99.9, 100.4),
        (100.4, 100.5, 100.3, 100.45),  # D set up, trigger 100.51 like A
        (100.45, 100.5, 100.35, 100.45),  # E set up, trigger 100.51
        (100.45, 101.0, 100.4, 100.95),  # reaches all three triggers: A and D fill first
    ]
    found = run(rows, ctx(warm=99.0))
    assert [a.filled for a in found] == [True, True, False]
    e = by_setup(found, "E")[0]
    assert e.status == "expired" and e.exit_reason == "max_attempts"


def test_no_duplicate_of_a_live_setup(monkeypatch):
    _forced(monkeypatch, {1: ("D", "x"), 2: ("D", "x")})
    rows = [(100, 100.2, 99.9, 100.1), (100.1, 100.4, 100.0, 100.3), (100.3, 100.38, 100.2, 100.35)]
    assert len(run(rows, ctx(warm=99.0))) == 1


# ------------------------------------------------------------------ outcome tracking


def alert(trigger=101.0, stop=99.0, low=99.01):
    t = OPEN
    return Alert(symbol="T", session="2026-10-23", setup="A", origin_bar=t, setup_bar=t, setup_index=0,
                 trigger=trigger, stop=stop, setup_low=low, setup_high=trigger - 0.01, ref_price=100.5, current_stop=stop)


def bar(i, o, h, l, c):
    return {"t": OPEN + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c, "v": 1}


S = Settings()


def test_fill_at_trigger_or_at_open_on_a_gap():
    a = alert()
    step(a, bar(1, 100.5, 101.5, 100.4, 101.2), 100.0, S)
    assert a.status == "triggered" and a.fill_price == 101.0 and a.filled
    g = alert()
    step(g, bar(1, 101.4, 101.8, 101.3, 101.6), 100.0, S)
    assert g.fill_price == 101.4


def test_stop_in_the_fill_bar_counts_first():
    a = alert()
    step(a, bar(1, 100.5, 101.5, 98.9, 101.2), 100.0, S)
    assert a.status == "stopped" and a.stop_hit and a.exit_price == 99.0
    assert a.r_multiple == pytest.approx(-1.0)


def test_expires_after_three_bars_without_fill():
    a = alert()
    for i in (1, 2, 3):
        step(a, bar(i, 100.5, 100.8, 100.2, 100.6), 100.0, S)
    assert a.status == "expired" and not a.filled


def test_cancelled_on_close_under_setup_low():
    a = alert()
    step(a, bar(1, 100.0, 100.2, 98.95 + 0.1, 99.0), 100.0, S)
    assert a.status == "cancelled"


def test_breakeven_after_third_new_high_then_stopped_at_entry():
    a = alert()
    step(a, bar(1, 100.9, 101.2, 100.8, 101.1), 100.0, S)  # fill, high 101.2
    for i, h in ((2, 101.4), (3, 101.6)):
        step(a, bar(i, h - 0.2, h, h - 0.3, h - 0.1), 100.0, S)
    assert a.breakeven_at is None
    step(a, bar(4, 101.5, 101.8, 101.4, 101.7), 100.0, S)  # third new high
    assert a.breakeven_at == OPEN + timedelta(minutes=25) and a.current_stop == 101.0
    step(a, bar(5, 101.6, 101.65, 100.9, 101.2), 100.0, S)
    assert a.status == "breakeven" and a.exit_price == 101.0 and a.r_multiple == pytest.approx(0.0)
    assert a.high_reached == 101.8


def test_exit_on_close_under_20_ema_at_the_close():
    a = alert()
    step(a, bar(1, 100.9, 101.6, 100.8, 101.5), 100.0, S)
    step(a, bar(2, 101.5, 101.7, 100.3, 100.4), 100.6, S)
    assert a.status == "exited" and a.exit_price == 100.4 and a.exit_reason == "close_under_20ema"
    assert a.r_multiple == pytest.approx((100.4 - 101.0) / 2.0)


def test_gap_through_stop_exits_at_open():
    a = alert()
    step(a, bar(1, 100.9, 101.6, 100.8, 101.5), 100.0, S)
    step(a, bar(2, 98.5, 98.9, 98.0, 98.7), 98.0, S)
    assert a.status == "stopped" and a.exit_price == 98.5


def test_session_end_closes_open_trades_and_pending_entries():
    flat = [(100, 100.1, 99.9, 100.05)] * 77
    rows = [(100, 101, 99.9, 100.9), (100.9, 101.3, 100.8, 101.2)] + flat[:76]
    c = ctx()
    found = run(rows, c)
    assert len(rows) == 78
    for a in found:
        assert a.status in alerts.FINAL


def test_r_multiple_win():
    a = alert()
    step(a, bar(1, 100.9, 101.6, 100.8, 101.5), 100.0, S)
    step(a, bar(2, 101.5, 105.2, 101.4, 105.0), 100.0, S)
    alerts.finish_session(a, bar(3, 105.0, 105.1, 104.9, 105.0))
    assert a.r_multiple == pytest.approx(2.0)


# ------------------------------------------------------------------ top names and metrics


def test_mark_top_first_three_distinct_names():
    rows = [
        {"symbol": "AAA", "fired_at": "2026-10-23T13:35:00Z"},
        {"symbol": "AAA", "fired_at": "2026-10-23T13:40:00Z"},
        {"symbol": "BBB", "fired_at": "2026-10-23T13:40:00Z"},
        {"symbol": "CCC", "fired_at": "2026-10-23T13:50:00Z"},
        {"symbol": "DDD", "fired_at": "2026-10-23T13:55:00Z"},
    ]
    assert alerts.mark_top(rows, 3) == {"AAA", "BBB", "CCC"}


def test_metrics_by_setup():
    rows = [
        {"setup": "A", "filled": True, "r_multiple": 2.0},
        {"setup": "A", "filled": True, "r_multiple": -1.0},
        {"setup": "A", "filled": False, "r_multiple": None},
        {"setup": "B", "filled": True, "r_multiple": None},  # still open
        {"setup": "C", "filled": True, "r_multiple": 0.0003},  # 1-cent scratch: not a win
    ]
    m = {r["setup"]: r for r in alerts.metrics(rows)}
    assert m["A"]["count"] == 3 and m["A"]["fill_rate"] == pytest.approx(66.7)
    assert m["A"]["win_rate"] == 50.0 and m["A"]["avg_r"] == 0.5 and m["A"]["total_r"] == 1.0
    assert m["B"]["open"] == 1 and m["B"]["win_rate"] is None
    assert m["C"]["win_rate"] == 0.0
    assert m["All"]["count"] == 5


# ------------------------------------------------------------------ not extended (5-minute EMA 360)


def test_ema_seed_and_continue_match_one_long_series():
    vals = [100 + (i % 11) * 0.2 + i * 0.01 for i in range(900)]
    full = alerts.ema_series(vals, 360)
    seed = alerts.ema_seed(vals[:800], 360)
    assert seed == pytest.approx(full[799])
    assert alerts.ema_continue(seed, vals[800:], 360) == pytest.approx(full[800:])
    assert alerts.ema_seed(vals[:359], 360) is None
    assert alerts.ema_continue(None, [1.0, 2.0]) == [None, None]


def test_ema360_is_thirty_hours_of_five_minute_bars():
    assert alerts.EMA_LONG * 5 == 30 * 60


A_BAR = [(100, 101, 99.9, 100.9)]  # a clean A on its own


def test_not_extended_passes_near_the_ema360_and_records_distance():
    found = run(A_BAR, ctx(ema360_seed=100.0))
    a = by_setup(found, "A")[0]
    e = 100.0 + 2 / 361 * (100.9 - 100.0)
    assert a.details["ema360"] == pytest.approx(e, abs=1e-4)
    assert a.details["ema360_close_pct"] == pytest.approx((100.9 - e) / e * 100, abs=0.01)
    assert a.details["ema360_low_pct"] == pytest.approx((99.9 - e) / e * 100, abs=0.01)


def test_extended_setup_is_blocked_with_a_reason():
    skipped = []
    # EMA 360 ~5% under: the low is far over it.
    assert not run(A_BAR, ctx(ema360_seed=95.0), skipped=skipped)
    assert skipped[0]["setup"] == "A" and skipped[0]["reason"].startswith("extended")


def test_low_near_but_close_stretched_is_blocked():
    s = Settings(ext_low_pct=1.0, ext_close_pct=0.5)
    skipped = []
    assert not run(A_BAR, ctx(ema360_seed=99.5), settings=s, skipped=skipped)  # low +0.4%, close +1.4%
    assert "extended" in skipped[0]["reason"]
    assert by_setup(run(A_BAR, ctx(ema360_seed=99.5), settings=Settings(ext_low_pct=1.0, ext_close_pct=2.0)), "A")


def test_pullback_low_in_the_last_hour_counts():
    # Bar 0 dips to the EMA 360, bar 1 is far over it: the hour's low still qualifies, a 1-bar lookback does not.
    rows = [(100, 100.5, 99.0, 100.4), (100.4, 101.6, 100.4, 101.5)]
    c = ctx(warm=102.0, ema360_seed=99.0)
    assert by_setup(run(rows, c), "C")
    assert not by_setup(run(rows, c, settings=Settings(ext_lookback_bars=1)), "C")


def test_filter_off_or_without_history_does_not_block():
    assert by_setup(run(A_BAR, ctx(ema360_seed=90.0), settings=Settings(ext_filter=0)), "A")
    a = by_setup(run(A_BAR, ctx()), "A")[0]  # no EMA 360 seed yet
    assert a.details["ema360"] is None and a.details["ema360_close_pct"] is None


def test_ext_settings_round_trip_and_limits():
    s = Settings.from_mapping({"ext_filter": "0", "ext_low_pct": "1.5", "ext_lookback_bars": "6"})
    assert (s.ext_filter, s.ext_low_pct, s.ext_lookback_bars) == (0, 1.5, 6)
    for k in ("ext_filter", "ext_low_pct", "ext_close_pct", "ext_lookback_bars"):
        assert k in alerts.SETTING_LIMITS
