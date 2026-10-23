"""Watchlist / positions premarket prints, 5-minute EMAs and the reclaim highlight (Alpaca, mocked)."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from strat import api, config, scheduler, watch5m
from strat.scheduler import ET


def et(day: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm, ss), tzinfo=ET).astimezone(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


THU = date(2026, 10, 22)
EMPTY = {"premarket": None, "ema5m": None, "ema5m_cross": None, "ema5m_cross_bar": None, "day_range": None}
WED = date(2026, 10, 21)
SESSIONS = [date(2026, 10, d) for d in (15, 16, 19, 20, 21)]


def session_bars(day: date, close, start=(9, 30), end=(16, 0)):
    out, t = [], et(day, *start)
    stop = et(day, *end)
    i = 0
    while t < stop:
        c = close(day, i)
        out.append({"t": iso(t), "o": c, "h": c, "l": c, "c": c, "v": 1000})
        t += timedelta(minutes=5)
        i += 1
    return out


class FakeClient:
    """Serves bars per feed from a list and records every request."""

    def __init__(self, bars: dict, trades: dict | None = None):
        self.all = bars  # {feed: {symbol: [bar]}}
        self.trades = trades or {}
        self.requests = 0
        self.calls: list[tuple] = []

    def bars(self, symbols, timeframe, start, end=None, feed=None, adjustment="raw", now=None):
        self.requests += 1
        self.calls.append(("bars", feed, start, end))
        out = {}
        for s in symbols:
            rows = [b for b in self.all.get(feed, {}).get(s, []) if start <= watch5m._ts(b["t"]) <= end]
            if rows:
                out[s] = rows
        return out, []

    def get(self, path, params):
        self.requests += 1
        self.calls.append(("get", params.get("feed")))
        return {"trades": self.trades.get(params.get("feed"), {})}


@pytest.fixture(autouse=True)
def fresh():
    watch5m.clear()
    yield
    watch5m.clear()


def flat(value):
    return lambda day, i: value


def history(close):
    return [b for d in SESSIONS for b in session_bars(d, close)]


def test_ema_matches_the_textbook_definition():
    assert watch5m.ema([1, 2, 3], 3) == pytest.approx(2.0)
    assert watch5m.ema([1, 2, 3, 4], 3) == pytest.approx(3.0)  # 2 + 0.5 * (4 - 2)
    assert watch5m.ema([1, 2], 3) is None
    series = watch5m.ema_series([1, 2, 3, 4], 3)
    assert series[:2] == [None, None] and series[-1] == pytest.approx(watch5m.ema([1, 2, 3, 4], 3))


def test_premarket_reading_uses_the_newest_print_and_prior_close():
    now = et(THU, 9, 0, 10)
    sip = {"TEAM": history(flat(100.0)) + session_bars(THU, flat(101.0), start=(4, 0), end=(8, 40))}
    trades = {
        "iex": {"TEAM": {"t": iso(et(THU, 8, 59, 30)), "p": 102.0}},  # real time, newest
        "delayed_sip": {"TEAM": {"t": iso(et(THU, 8, 44, 50)), "p": 101.5}},
    }
    client = FakeClient({"sip": sip}, trades)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=client)
    pm = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["premarket"]
    assert pm["price"] == 102.0 and pm["source"] == "iex"
    assert pm["change_pct"] == 2.0
    assert pm["volume"] == 1000 * len(session_bars(THU, flat(1), start=(4, 0), end=(8, 40)))
    assert pm["final"] is False
    em = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["ema5m"]
    assert em["basis"] == "premarket" and em["vs6"] == "above" and em["vs20"] == "above"
    # 1 history + 1 SIP premarket + 2 latest-trade requests; nothing for the universe.
    assert client.requests == 4


def test_yesterdays_trade_is_not_a_premarket_print():
    now = et(THU, 4, 30, 10)
    trades = {"delayed_sip": {"TEAM": {"t": iso(et(WED, 19, 59)), "p": 99.0}}}
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": {}}, trades))
    assert watch5m.snapshot(["TEAM"], now=now)["TEAM"] == EMPTY


def test_premarket_freezes_at_the_open_then_hides_after_the_close():
    sip = {"TEAM": history(flat(100.0)) + session_bars(THU, lambda d, i: 101.0 + i * 0.01, start=(4, 0), end=(16, 0))}
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 9, 25, 10), client=FakeClient({"sip": sip}))
    early = watch5m.snapshot(["TEAM"], now=et(THU, 9, 25, 10))["TEAM"]["premarket"]
    # 09:35: the 09:25 SIP bar is not served yet, the last premarket reading stays.
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 9, 35, 10), client=FakeClient({"sip": sip, "iex": {}}))
    assert watch5m.snapshot(["TEAM"], now=et(THU, 9, 35, 10))["TEAM"]["premarket"] == early
    # 09:50: exact premarket close (09:25 bar) and full 04:00-09:30 volume.
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 9, 50, 10), client=FakeClient({"sip": sip, "iex": {}}))
    final = watch5m.snapshot(["TEAM"], now=et(THU, 12, 0))["TEAM"]["premarket"]
    assert final["final"] is True
    assert final["time"] == iso(et(THU, 9, 25))
    assert final["volume"] == 1000 * 66
    assert watch5m.snapshot(["TEAM"], now=et(THU, 16, 0, 1))["TEAM"]["premarket"] is None


def test_ema_uses_regular_session_bars_only_and_warms_up_from_history():
    # Premarket bars at 50 would drag both EMAs down if they were counted.
    sip = {"TEAM": history(flat(100.0)) + session_bars(THU, flat(50.0), start=(4, 0), end=(9, 30))}
    sip["TEAM"] += session_bars(THU, flat(100.5), start=(9, 30), end=(11, 0))
    now = et(THU, 11, 30, 10)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip, "iex": {}}))
    em = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["ema5m"]
    assert 100.0 < em["ema20"] <= em["ema6"] <= 100.5
    assert em["basis"] == "live"


def test_no_history_means_a_dash_not_a_guess():
    now = et(THU, 11, 0, 10)
    watch5m.refresh(["NEW"], lambda s, d: None, now=now, client=FakeClient({"sip": {}, "iex": {}}))
    assert watch5m.snapshot(["NEW"], now=now)["NEW"] == EMPTY


def test_history_is_fetched_once_per_session():
    sip = {"TEAM": history(flat(100.0))}
    client = FakeClient({"sip": sip})
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 2, 0), client=client)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 3, 0), client=client)
    assert client.requests == 1
    # After 16:20 ET today's session is the one to have, so it is checked again.
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=et(THU, 20, 0), client=client)
    assert client.requests == 2


def reclaim_closes(day, i):
    # Flat at 100 then a dip to 99 and a close back above at bar 10 (10:20 bar).
    return 99.0 if 5 <= i <= 9 else 100.0 if i < 10 else 100.6


def test_reclaim_highlight_lasts_until_the_next_bar_completes():
    sip = {"TEAM": history(flat(100.0))}
    iex = {"TEAM": session_bars(THU, reclaim_closes, end=(10, 30))}  # bars 09:30 .. 10:25
    now = et(THU, 10, 25, 10)  # the 10:20 bar just completed; 10:25 is forming
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip, "iex": iex}))
    em = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["ema5m"]
    assert em["highlight"] == [6, 20]
    assert em["highlight_bar"] == iso(et(THU, 10, 20))
    assert em["highlight_until"] == iso(et(THU, 10, 30))
    snap = watch5m.snapshot(["TEAM"], now=now)["TEAM"]
    assert snap["ema5m_cross"] == "6+20" and snap["ema5m_cross_bar"] == iso(et(THU, 10, 20))
    assert watch5m.snapshot(["TEAM"], now=et(THU, 10, 30))["TEAM"]["ema5m_cross"] is None
    assert watch5m.snapshot(["TEAM"], now=et(THU, 10, 30))["TEAM"]["ema5m"]["highlight"] == []


def test_highlight_rule_is_a_crossover_not_just_above():
    assert watch5m.highlight_rule(99.0, 99.5, 100.0, 99.6) is True
    assert watch5m.highlight_rule(99.5, 99.5, 100.0, 99.6) is True  # at, then above
    assert watch5m.highlight_rule(100.0, 99.5, 100.2, 99.6) is False  # already above
    assert watch5m.highlight_rule(99.0, 99.5, 99.4, 99.6) is False


def test_the_forming_bar_never_triggers_the_highlight():
    sip = {"TEAM": history(flat(100.0))}
    iex = {"TEAM": session_bars(THU, reclaim_closes, end=(10, 25))}  # 10:20 bar still forming
    now = et(THU, 10, 22)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip, "iex": iex}))
    assert watch5m.snapshot(["TEAM"], now=now)["TEAM"]["ema5m"]["highlight"] == []


def test_scheduler_polls_the_lists_every_five_minutes_in_premarket_only():
    pre = datetime(2026, 10, 22, 8, 0, 12, tzinfo=ET)
    assert scheduler.lists_due(pre, None, aligned=True)
    assert not scheduler.lists_due(pre, pre, aligned=True)
    assert scheduler.lists_due(pre + timedelta(minutes=5), pre, aligned=True)
    assert not scheduler.lists_due(pre, None, aligned=False)  # Yahoo provider: off
    assert not scheduler.lists_due(datetime(2026, 10, 22, 10, 0, 12, tzinfo=ET), None, aligned=True)
    assert scheduler.decide(pre, date(2026, 10, 21), None, None, aligned=True, last_lists=None) == "lists"


def test_payloads_carry_the_lists_snapshot_without_fetching(monkeypatch):
    monkeypatch.setattr(api.data, "watchlist", lambda *a: ["TEAM"])
    monkeypatch.setattr(api.data, "positions", lambda *a: [])
    monkeypatch.setattr(watch5m, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched on request")))
    body = api.get_watchlist()
    assert body["intraday"]["TEAM"] == EMPTY
    assert api.get_positions()["intraday"] == {}


def test_refresh_runs_inside_the_job_slot_and_only_for_the_lists(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "scheduler_enabled", lambda: True)
    monkeypatch.setattr(api, "live_bars_enabled", lambda: True)
    monkeypatch.setattr(api, "_list_symbols", lambda: ["TEAM", "NVDA"])
    monkeypatch.setattr(watch5m, "refresh", lambda symbols, prev, **k: seen.append((api.State.job, symbols)) or {})
    assert api._claim_job("lists")
    api._run_watch5m()
    assert seen == [("lists", ["TEAM", "NVDA"])]
    assert api.State.job is None


def ranged(day, i):
    return 100.0 + i * 0.1  # rising: each bar's h/l = its close


def test_day_range_is_todays_regular_session_with_the_latest_price():
    today = session_bars(THU, ranged, end=(10, 30))  # 09:30 .. 10:25, closes 100.0 .. 101.1
    today[3] = {**today[3], "h": 103.0, "l": 99.0}  # 09:45: SIP bar (older than 15 min)
    sip = {"TEAM": history(flat(100.0)) + today}
    iex = {"TEAM": today}
    now = et(THU, 10, 27)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip, "iex": iex}))
    rng = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["day_range"]
    assert (rng["low"], rng["high"], rng["last"]) == (99.0, 103.0, 101.1)
    assert rng["pct"] == pytest.approx(52.5)
    assert rng["basis"] == "regular" and rng["session"] == "2026-10-22"


def test_premarket_range_includes_the_latest_print():
    now = et(THU, 9, 0, 10)
    sip = {"TEAM": history(flat(100.0)) + session_bars(THU, flat(101.0), start=(4, 0), end=(8, 40))}
    trades = {"iex": {"TEAM": {"t": iso(et(THU, 8, 59, 30)), "p": 102.0}}}
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip}, trades))
    rng = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["day_range"]
    assert (rng["low"], rng["high"], rng["pct"], rng["basis"]) == (101.0, 102.0, 100.0, "premarket")


def test_outside_the_session_the_last_session_range_is_shown():
    sip = {"TEAM": history(ranged)}
    now = et(THU, 2, 0)
    watch5m.refresh(["TEAM"], lambda s, d: 100.0, now=now, client=FakeClient({"sip": sip}))
    rng = watch5m.snapshot(["TEAM"], now=now)["TEAM"]["day_range"]
    assert rng["basis"] == "last session" and rng["session"] == "2026-10-21"
    assert (rng["low"], rng["high"], rng["pct"]) == (100.0, 107.7, 100.0)


def test_a_flat_range_is_a_dash():
    assert watch5m.make_range([{"h": 5.0, "l": 5.0}], 5.0, "regular", "2026-10-22") is None
    assert watch5m.make_range([], 5.0, "regular", "2026-10-22") is None
