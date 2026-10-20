"""The scheduler has to start on an empty cache.

Heroku wipes the cache on every deploy. Boot used to return after kicking off
the initial download, so the 15-minute poll, the after-close history refresh,
and the premarket/after-hours index quotes never ran.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from strat import api, config

ET = ZoneInfo("America/New_York")


class _Stop(Exception):
    pass


class _InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._kwargs = kwargs or {}

    def start(self):
        self._target(**self._kwargs)


def test_an_empty_cache_starts_a_full_download_then_the_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "AS_OF", None)
    monkeypatch.setattr(api.data, "cached_symbols", lambda: {})

    def start_refresh(full=False, **_kwargs):
        calls.append(("refresh", full))
        api.State.refreshing = True
        return True

    monkeypatch.setattr(api, "start_refresh", start_refresh)
    monkeypatch.setattr(api, "start_index_quotes", lambda: calls.append("quotes") or True)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: calls.append(("scan", force)) or [])
    monkeypatch.setattr(api, "_scheduler_loop", lambda: calls.append(("scheduler", api.State.refreshing)))
    try:
        api._boot()
    finally:
        api.State.refreshing = False
    assert calls == [("refresh", True), ("scheduler", True)]


def test_a_warm_cache_scans_then_starts_the_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "AS_OF", None)
    monkeypatch.setattr(api.data, "cached_symbols", lambda: {"QQQ": "2026-10-19"})
    monkeypatch.setattr(api, "start_refresh", lambda **_kwargs: calls.append("refresh") or True)
    monkeypatch.setattr(api, "start_index_quotes", lambda: calls.append("quotes") or True)
    monkeypatch.setattr(api, "_refresh_earnings", lambda **_kwargs: calls.append("earnings"))
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: calls.append(("scan", force)) or [])
    monkeypatch.setattr(api, "_scheduler_loop", lambda: calls.append("scheduler"))
    monkeypatch.setattr(api.threading, "Thread", _InlineThread)
    api._boot()
    assert calls == ["earnings", ("scan", True), "scheduler"]


def test_a_fixed_as_of_scans_once_and_does_not_schedule(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "AS_OF", "2026-10-16")
    monkeypatch.setattr(api.data, "cached_symbols", lambda: {})
    monkeypatch.setattr(api, "start_refresh", lambda **_kwargs: calls.append("refresh") or True)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: calls.append(("scan", force)) or [])
    monkeypatch.setattr(api, "_scheduler_loop", lambda: calls.append("scheduler"))
    api._boot()
    assert calls == [("scan", True)]


def _drive(monkeypatch, *, now, newest, ticks, refreshing_until):
    """Run ``ticks`` scheduler iterations. The first ``refreshing_until`` still count as the download.

    A refresh the loop itself starts holds ``State.refreshing``, the same way ``start_refresh`` does,
    so the next tick waits instead of firing the same job again.
    """
    refreshes = []
    quotes = []
    step = {"n": 0}

    def sleep(_seconds):
        step["n"] += 1
        if step["n"] > ticks:
            raise _Stop
        if step["n"] <= refreshing_until:
            api.State.refreshing = True
        elif step["n"] == refreshing_until + 1:
            api.State.refreshing = False

    def start_refresh(full=False, period=None, with_earnings=True):
        refreshes.append({"full": full, "period": period, "with_earnings": with_earnings})
        api.State.refreshing = True
        return True

    monkeypatch.setattr(api.time, "sleep", sleep)
    monkeypatch.setattr(config, "AS_OF", None)
    monkeypatch.setattr(api, "now_et", lambda: now)
    monkeypatch.setattr(api.data, "newest_bar_date", lambda: newest)
    monkeypatch.setattr(api.data, "clear_index_quotes", lambda: False)
    monkeypatch.setattr(api, "start_refresh", start_refresh)
    monkeypatch.setattr(api, "start_index_quotes", lambda: quotes.append(step["n"]) or True)
    api.State.refreshing = True
    api.State.quoting = False
    try:
        api._scheduler_loop()
    except _Stop:
        pass
    finally:
        api.State.refreshing = False
        api.State.quoting = False
    return refreshes, quotes


def test_the_tick_after_the_initial_download_does_not_start_another_full_refresh(monkeypatch):
    # Premarket, regular session, and just after the close. The download has already
    # stored bars through the last completed session (or through today, once the close
    # is in the cache). None of those clocks asks for another 3y fetch.
    premarket_refreshes, _premarket_quotes = _drive(
        monkeypatch,
        now=datetime(2026, 10, 20, 8, 0, tzinfo=ET),
        newest=date(2026, 10, 19),
        ticks=4,
        refreshing_until=2,
    )
    assert premarket_refreshes == []

    session, session_quotes = _drive(
        monkeypatch,
        now=datetime(2026, 10, 20, 10, 0, tzinfo=ET),
        newest=date(2026, 10, 19),
        ticks=4,
        refreshing_until=2,
    )
    assert session == [{"full": False, "period": "5d", "with_earnings": False}]
    assert session_quotes == []

    behind, behind_quotes = _drive(
        monkeypatch,
        now=datetime(2026, 10, 20, 16, 30, tzinfo=ET),
        newest=date(2026, 10, 19),
        ticks=4,
        refreshing_until=2,
    )
    assert behind == [{"full": False, "period": config.INCREMENTAL_PERIOD, "with_earnings": True}]
    assert behind_quotes == []


def test_index_quotes_start_once_after_the_initial_download(monkeypatch):
    # Two ticks after the download, still inside one poll interval. Extended hours
    # start the quote thread on the first of those ticks and not again.
    for now, newest in (
        (datetime(2026, 10, 20, 8, 0, tzinfo=ET), date(2026, 10, 19)),
        (datetime(2026, 10, 20, 16, 30, tzinfo=ET), date(2026, 10, 20)),
    ):
        refreshes, quotes = _drive(monkeypatch, now=now, newest=newest, ticks=4, refreshing_until=2)
        assert refreshes == []
        assert quotes == [3]
