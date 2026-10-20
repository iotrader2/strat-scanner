"""The 5-day poll must not keep a second copy of the price cache, and RSS must stay flat.

RSS is the number Heroku's R14 quota uses (resident set plus swap). tracemalloc
watches the Python heap for a retained frame or a growing list.
"""

import threading
import time
import tracemalloc

import numpy as np
import pandas as pd

from strat import api, config, data, memory
from strat.provider import FetchResult
from strat.universe import Member


def _seed(db, symbols: list[str], bars: int) -> None:
    idx = pd.bdate_range("2024-01-02", periods=bars)
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    rng = np.random.default_rng(1)
    rows = []
    for sym in symbols:
        px = 50 * np.cumprod(1 + rng.normal(0, 0.01, bars))
        for i, day in enumerate(dates):
            c = float(px[i])
            rows.append((sym, day, c, c, c, c, 1_000_000.0))
    with data.connect(db) as conn:
        conn.executemany(
            "INSERT INTO bars(symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            rows,
        )


class _Poll:
    """5-day frames for the symbols already in the cache. No network."""

    def __init__(self, symbols: list[str]) -> None:
        idx = pd.bdate_range("2024-01-02", periods=120)[-5:]
        self.frames = {
            sym: pd.DataFrame(
                {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1_000_000.0},
                index=idx,
            )
            for sym in symbols
        }

    def fetch_history(self, symbols, period):
        return FetchResult(frames={s: self.frames[s] for s in symbols if s in self.frames})


def test_reload_daily_matches_a_full_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    idx = pd.bdate_range("2024-06-03", periods=30)
    raw = pd.DataFrame(
        {"Open": 40.0, "High": 41.0, "Low": 39.0, "Close": 40.0, "Volume": 100.0},
        index=idx,
    )
    data.save_bars("AAA", raw)
    data.save_bars("BBB", raw)
    data.save_splits("AAA", [(idx[10].strftime("%Y-%m-%d"), 4.0)])
    data.save_session_bar(
        "BBB",
        pd.DataFrame(
            {"Open": 10.0, "High": 12.0, "Low": 9.0, "Close": 11.0, "Volume": 50.0},
            index=pd.to_datetime(["2026-10-19"]),
        ),
    )
    # A symbol that only exists in the caller's dict must be dropped.
    held = {"CCC": raw.copy()}
    data.reload_daily(held, batch=1)
    fresh = data.load_all_daily()
    assert set(held) == set(fresh) == {"AAA", "BBB"}
    for sym in fresh:
        pd.testing.assert_frame_equal(held[sym], fresh[sym])


def _block_rows(df: pd.DataFrame) -> int:
    """Rows in the numpy block behind ``df``. A groupby view spans the whole query."""
    arr = df.to_numpy()
    base = arr.base
    if base is None or not hasattr(base, "shape") or len(base.shape) == 0:
        return len(df)
    return int(base.shape[-1])


def _reset_state() -> None:
    api.State.daily = {}
    api.State.scan = []
    api.State.result = None
    api.State.scan_key = None
    api.State.refreshing = False
    api.State.error = None
    api.State.version = 0
    from strat.perf import MomentumRanks

    api.State.strengths = {}
    api.State.ranks = MomentumRanks({})
    api.State.qqq = {}
    api.State.prior = {}
    api.State.theme_map = None
    api.State.progress = {"done": 0, "total": 0, "message": ""}


def test_intraday_polls_keep_rss_flat(tmp_path, monkeypatch, capsys):
    symbols = [f"S{i:03d}" for i in range(200)]
    symbols[0] = "QQQ"
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    monkeypatch.setenv("STRAT_FETCH_SUBPROCESS", "1")
    _seed(config.CACHE_DB, symbols, bars=400)
    members = [Member(sym, sym, "Information Technology", "stock", "SP500") for sym in symbols]
    monkeypatch.setattr(api, "_universe", lambda: members)
    monkeypatch.setattr("strat.provider.get_provider", lambda: _Poll(symbols))
    # The indicator pass is covered by the scanner tests. Here it would dominate
    # the runtime without changing how many price frames the refresh retains.
    from strat.scanner import ScanResult

    def cheap_scan(members, daily, themes=None, method=None, changes=True):
        rows = []
        for member in members:
            frame = daily.get(member.symbol)
            if frame is None or frame.empty:
                continue
            rows.append(
                {
                    "symbol": member.symbol,
                    "price": float(frame["close"].iloc[-1]),
                    "score": 1.0,
                    "change_pct": 0.0,
                    "leader_status": "",
                    "setup": "",
                    "rs": 0.5,
                }
            )
        return ScanResult(rows)

    monkeypatch.setattr(api, "scan_all", cheap_scan)
    from strat import fetch_worker

    child: list = []
    monkeypatch.setattr(fetch_worker, "fetch_in_child", lambda *a: child.append(a))

    _reset_state()
    data.reload_daily(api.State.daily)
    memory.release_heap()
    for sym, df in api.State.daily.items():
        assert _block_rows(df) == len(df), sym

    tracemalloc.start()
    rss, traced, peaks = [], [], []

    def watch(stop: threading.Event, sink: list[float]) -> None:
        while not stop.is_set():
            sink.append(memory.rss_mb())
            time.sleep(0.01)

    try:
        for _ in range(6):
            stop = threading.Event()
            seen: list[float] = []
            thread = threading.Thread(target=watch, args=(stop, seen), daemon=True)
            thread.start()
            api._run_refresh(full=False, period="5d", with_earnings=False)
            stop.set()
            thread.join(timeout=1)
            memory.release_heap()
            rss.append(memory.rss_mb())
            current, _peak = tracemalloc.get_traced_memory()
            traced.append(current)
            peaks.append(max(seen) if seen else rss[-1])
    finally:
        tracemalloc.stop()
        _reset_state()
        memory.release_heap()

    out = capsys.readouterr().out
    detail = f"rss={['%.1f' % v for v in rss]} peaks={['%.1f' % v for v in peaks]} traced={traced}"
    print(detail)
    assert "refresh start" in out and "rss=" in out and "fetch=in-process" in out
    assert child == []
    assert api.State.error is None
    # The old full-query view pinned ~150 MB on a universe this size and did not
    # come back after the next poll. Batch reloads stay inside a much smaller band.
    assert max(rss) - min(rss) < 40, detail
    assert max(peaks) - min(rss) < 80, detail
    assert traced[-1] - traced[0] < 8 * 1024 * 1024, detail
