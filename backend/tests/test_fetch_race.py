"""One background job at a time, retries for symbols a batch dropped, and a locked cache that waits instead of failing.

On the v32 stage deploy the first download dropped QQQ, AMAT, AMD, DGX, DLR, ETN and EOG: yfinance's own SQLite
cache answered "database is locked" inside a threaded download, the failed tickers came back as all-NaN columns,
and the refresh treated them as downloaded and saved nothing. A manual refresh lost SMH the same way.
"""

import sqlite3
import threading
import time

import pandas as pd
import pytest

from strat import api, config, data
from strat.provider import FetchResult, YahooProvider


def _frame(close=10.0):
    idx = pd.to_datetime(["2026-10-15", "2026-10-16"])
    return pd.DataFrame(
        {"Open": [close, close], "High": [close, close], "Low": [close, close], "Close": [close, close], "Volume": [1.0, 1.0]},
        index=idx,
    )


def _nan_frame():
    f = _frame()
    f[:] = float("nan")
    return f


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(data, "RETRY_SLEEP", 0)
    monkeypatch.setattr("strat.scheduler.regular_session", lambda clock: False)
    return tmp_path / "cache.sqlite3"


@pytest.fixture
def clean_state():
    api.State.job = None
    api.State.refreshing = False
    api.State.quoting = False
    yield
    api.State.job = None
    api.State.refreshing = False
    api.State.quoting = False


# --- the job slot -----------------------------------------------------------------------------


def test_a_running_refresh_blocks_a_second_refresh_and_the_quote_poll_until_its_rescan_ends(monkeypatch, clean_state):
    in_fetch, release_fetch = threading.Event(), threading.Event()
    in_scan, release_scan = threading.Event(), threading.Event()
    starts = []

    def fake_refresh(symbols, full=False, progress=None, period=None, db_path=None):
        starts.append(full)
        in_fetch.set()
        release_fetch.wait(5)

    def fake_scan(force=False):
        in_scan.set()
        release_scan.wait(5)
        return []

    monkeypatch.delenv("STRAT_FETCH_SUBPROCESS", raising=False)
    monkeypatch.setattr(data, "refresh", fake_refresh)
    monkeypatch.setattr(api, "_ensure_scan", fake_scan)
    monkeypatch.setattr(api, "_publish_status", lambda: None)
    monkeypatch.setattr(api, "backfill_industries", lambda members: None)
    monkeypatch.setattr(api, "_refresh_earnings", lambda *a, **k: None)
    quotes_ran = []
    monkeypatch.setattr(api, "_run_index_quotes", lambda: quotes_ran.append(1))

    assert api.start_refresh(full=True)
    assert in_fetch.wait(5)
    assert not api.start_refresh(full=False)  # POST /api/refresh during the startup download
    assert not api.start_index_quotes()
    release_fetch.set()
    assert in_scan.wait(5)
    # The download finished but the rescan still holds the universe in memory: still one job.
    assert api.State.refreshing is False and api.State.job == "refresh"
    assert not api.start_index_quotes()
    assert not api.start_refresh()
    release_scan.set()
    for _ in range(100):
        if api.State.job is None:
            break
        time.sleep(0.02)
    assert api.State.job is None
    assert starts == [True]
    assert quotes_ran == []


def test_earnings_warm_up_waits_for_the_job_slot(monkeypatch, clean_state):
    ran = []
    monkeypatch.setattr(api, "_refresh_earnings", lambda **k: ran.append(api.State.job))
    api.State.job = "refresh"
    t = threading.Thread(target=api._warm_earnings, kwargs={"wait_seconds": 5, "poll": 0.01})
    t.start()
    time.sleep(0.1)
    assert ran == []  # still waiting, not racing the download
    api.State.job = None
    t.join(5)
    assert ran == ["earnings"] and api.State.job is None


def test_scheduler_skips_a_tick_while_a_job_holds_the_slot(monkeypatch, clean_state):
    ticks = {"n": 0}

    def sleep(_):
        ticks["n"] += 1
        if ticks["n"] > 2:
            raise SystemExit

    monkeypatch.setattr(api.time, "sleep", sleep)
    monkeypatch.setattr(api, "decide", lambda *a, **k: (_ for _ in ()).throw(AssertionError("decided while busy")))
    api.State.job = "earnings"
    with pytest.raises(SystemExit):
        api._scheduler_loop()


# --- retries instead of drops -----------------------------------------------------------------


def test_symbols_missing_from_a_batch_are_retried_not_dropped(cache, monkeypatch):
    calls = []

    class Flaky:
        name = "flaky"

        def fetch_history(self, symbols, period):
            calls.append(list(symbols))
            # First pass loses QQQ and AMD (the lock miss); the retry gets them.
            drop = {"QQQ", "AMD"} if len(calls) == 1 else set()
            return FetchResult(frames={s: _frame() for s in symbols if s not in drop})

    monkeypatch.setattr("strat.provider.get_provider", lambda: Flaky())
    saved = data.refresh(["AAPL", "QQQ", "AMD"], full=True)
    assert set(saved) == {"AAPL", "QQQ", "AMD"}
    assert calls[1] == ["QQQ", "AMD"]


def test_all_nan_frames_count_as_missing(cache, monkeypatch):
    calls = []

    class NaNs:
        name = "nan"

        def fetch_history(self, symbols, period):
            calls.append(list(symbols))
            return FetchResult(frames={s: (_nan_frame() if len(calls) == 1 and s == "SMH" else _frame()) for s in symbols})

    monkeypatch.setattr("strat.provider.get_provider", lambda: NaNs())
    saved = data.refresh(["SMH", "SPY"], full=True)
    assert "SMH" in saved and "SMH" in data.cached_symbols()


def test_yahoo_leaves_out_locked_tickers_so_they_are_retried_serially(monkeypatch):
    calls = []

    def download(symbols, **kwargs):
        symbols = list(symbols)
        calls.append((symbols, kwargs["threads"]))
        cols = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
        df = pd.DataFrame({c: [1.0] for c in cols}, index=pd.to_datetime(["2026-10-16"]))
        if kwargs["threads"]:
            df["QQQ"] = float("nan")  # "OperationalError('database is locked')" in yfinance's cache
        return df

    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch_history(["AAPL", "QQQ"], "3y")
    assert calls == [(["AAPL", "QQQ"], True), (["QQQ"], False)]
    assert set(result.frames) == {"AAPL", "QQQ"}
    assert not result.frames["QQQ"].isna().all().all()


def test_a_missing_benchmark_fails_loudly_instead_of_zeroing_vs_qqq(cache, monkeypatch):
    class NoQQQ:
        name = "noqqq"

        def fetch_history(self, symbols, period):
            return FetchResult(frames={s: _frame() for s in symbols if s != "QQQ"})

    monkeypatch.setattr("strat.provider.get_provider", lambda: NoQQQ())
    with pytest.raises(RuntimeError, match="QQQ"):
        data.refresh(["AAPL", "QQQ"], full=True)
    assert "AAPL" in data.cached_symbols()  # everything else was still saved


def test_a_benchmark_miss_keeps_the_previous_bars(cache, monkeypatch):
    data.save_bars("QQQ", _frame(500.0))

    class NoQQQ:
        name = "noqqq"

        def fetch_history(self, symbols, period):
            return FetchResult(frames={s: _frame() for s in symbols if s != "QQQ"})

    monkeypatch.setattr("strat.provider.get_provider", lambda: NoQQQ())
    data.refresh(["AAPL", "QQQ"], period="5d")
    assert data.load_daily("QQQ").close.iloc[-1] == 500.0


# --- the cache itself ---------------------------------------------------------------------------


def test_a_write_waits_for_another_writer_instead_of_failing(cache):
    data.save_bars("AAA", _frame())  # create the file
    holder = sqlite3.connect(cache, timeout=0, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")  # another process (the fetch child) holds the write lock
    released = threading.Timer(0.5, lambda: holder.execute("COMMIT"))
    released.start()
    start = time.monotonic()
    data.save_bars("BBB", _frame())  # would raise "database is locked" without a busy timeout
    assert time.monotonic() - start >= 0.4
    released.join()
    holder.close()
    assert "BBB" in data.cached_symbols()


def test_concurrent_writers_in_one_process_do_not_lose_rows(cache):
    errors = []

    def write(sym):
        try:
            for _ in range(5):
                data.save_bars(sym, _frame())
        except Exception as exc:  # pragma: no cover - the failure being tested for
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(f"S{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(data.cached_symbols()) == 8
