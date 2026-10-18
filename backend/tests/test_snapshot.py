import asyncio

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import api, config, data
from strat.backtest import forward_return
from strat.hub import hub


def test_a_split_inside_the_forward_window_is_not_a_crash():
    idx = pd.bdate_range("2026-01-02", periods=40)
    close = pd.Series(100.0, index=idx)
    close.iloc[20:] = 25.0
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1_000_000.0})
    as_of = idx[10]
    ex = idx[20].strftime("%Y-%m-%d")
    assert forward_return(df, as_of, months=1) == pytest.approx(-75.0)
    assert forward_return(df, as_of, months=1, splits=[(ex, 4.0)]) == pytest.approx(0.0)


def test_snapshot_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    rows = [{"symbol": "AAA", "score": 80.0, "price": 10.5, "leader_status": "leader"}]
    data.save_snapshot(4, "2026-10-16T20:00:00+00:00", rows)
    assert data.load_snapshot() == {"version": 4, "computed_at": "2026-10-16T20:00:00+00:00", "rows": rows}
    data.set_meta("last_refresh", "2026-10-16T20:00:00+00:00")


def test_websocket_sends_the_saved_snapshot_then_a_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    data.save_snapshot(3, "2026-10-16T20:00:00+00:00", [{"symbol": "AAA", "score": 1, "price": 10}])
    data.set_meta("last_refresh", "2026-10-16T20:00:00+00:00")
    with TestClient(api.app) as client:
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["version"] == 3
            assert msg["changed"][0]["symbol"] == "AAA"
            assert msg["status"]["delay"] == "15m"
            assert hub.loop is not None
            asyncio.run_coroutine_threadsafe(
                hub._broadcast({"type": "ping", "t": "2026-10-18T14:00:00+00:00"}),
                hub.loop,
            ).result(timeout=2)
            assert ws.receive_json()["type"] == "ping"
