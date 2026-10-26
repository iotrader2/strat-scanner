"""Alerts persistence, settings, the live merge of SIP / IEX bars, and the alerts API."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from strat import alerts_live, alerts_store, config
from strat.alerts import Context, Settings, simulate

OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    return None  # functions use the default user database (SQLite at CACHE_DB in tests)


def _bars(rows):
    return [
        {"t": OPEN + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c, "v": 1000.0}
        for i, (o, h, l, c) in enumerate(rows)
    ]


def _alerts(symbol, rows):
    return simulate(symbol, "2026-10-23", _bars(rows), Context(warm_closes=[100.0] * 60))


A_ROWS = [(100, 101, 99.9, 100.9)]


def test_insert_then_update_outcome_by_key(db):
    now = OPEN + timedelta(minutes=6)
    first = alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=now)
    assert len(first["inserted"]) == 1 and not first["inserted"][0]["late"]
    rows = alerts_store.list_alerts(session="2026-10-23")
    assert rows[0]["status"] == "pending" and rows[0]["fired_at"] == "2026-10-23T13:35:00Z"
    assert rows[0]["top"] and not rows[0]["acknowledged"]
    # Next poll: bar 2 fills it.
    later = alerts_store.save_session(
        "2026-10-23", [a for a in _alerts("AAA", A_ROWS + [(100.9, 101.3, 100.8, 101.2)]) if a.setup == "A"], now=now + timedelta(minutes=5)
    )
    assert later["inserted"] == [] and later["updated"] == 1
    row = alerts_store.list_alerts(session="2026-10-23")[0]
    assert row["status"] == "triggered" and row["filled"] and row["fill_price"] == 101.01
    assert row["detected_at"] == "2026-10-23T13:36:00Z"  # fire / detection times never move


def test_backfilled_alert_is_late(db):
    saved = alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=OPEN + timedelta(minutes=40))
    assert saved["inserted"][0]["late"]


def test_top_is_first_three_names_and_sticks(db):
    now = OPEN + timedelta(minutes=6)
    for sym in ("AAA", "BBB", "CCC"):
        alerts_store.save_session("2026-10-23", _alerts(sym, A_ROWS), now=now)
    alerts_store.save_session("2026-10-23", _alerts("DDD", A_ROWS), now=now)
    top = {r["symbol"]: r["top"] for r in alerts_store.list_alerts(session="2026-10-23")}
    assert top == {"AAA": True, "BBB": True, "CCC": True, "DDD": False}


def test_acknowledge(db):
    alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS) + _alerts("BBB", A_ROWS), now=OPEN + timedelta(minutes=6))
    ids = [r["id"] for r in alerts_store.list_alerts()]
    assert alerts_store.unread_count() == 2
    alerts_store.acknowledge([ids[0]])
    assert alerts_store.unread_count() == 1
    alerts_store.acknowledge()
    assert alerts_store.unread_count() == 0


def test_settings_round_trip_and_validation(db):
    assert alerts_store.load_settings() == Settings()
    s = alerts_store.save_settings({"bunched_pct": 0.75, "top_names": 4})
    assert s.bunched_pct == 0.75 and s.top_names == 4
    assert alerts_store.load_settings().top_names == 4
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"nope": 1})
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"bunched_pct": 99})
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"b_from": 100})  # after b_to
    assert alerts_store.reset_settings() == Settings()


# ------------------------------------------------------------------ live merge


def _raw(t, o, h, l, c, v):
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": l, "c": c, "v": v}


def test_merge_day_prices_from_sip_volume_from_iex():
    day = date(2026, 10, 23)
    pm = OPEN - timedelta(minutes=30)
    sip = [_raw(pm, 99, 99.5, 98.0, 99.2, 50000), _raw(OPEN, 100, 101, 99.9, 100.9, 90000)]
    iex = [_raw(OPEN, 100.02, 100.98, 99.95, 100.88, 1200), _raw(OPEN + timedelta(minutes=5), 100.9, 101.2, 100.8, 101.1, 800),
           _raw(OPEN + timedelta(minutes=10), 101.1, 101.3, 101.0, 101.2, 700)]
    cutoff = OPEN + timedelta(minutes=5)
    now = OPEN + timedelta(minutes=11)  # the 13:40 bar is still forming
    bars, pm_low = alerts_live.merge_day(sip, iex, day, cutoff, now)
    assert pm_low == 98.0
    assert len(bars) == 2
    assert (bars[0]["h"], bars[0]["v"]) == (101, 1200)  # SIP prices, IEX volume
    assert (bars[1]["h"], bars[1]["v"]) == (101.2, 800)  # IEX after the cutoff


def test_volume_profile_by_time_of_day():
    bars = []
    for d in range(3):
        start = OPEN - timedelta(days=d + 1)
        bars.append(_raw(start, 1, 1, 1, 1, 100 * (d + 1)))
        bars.append(_raw(start + timedelta(minutes=5), 1, 1, 1, 1, 10))
    avg, n = alerts_live.volume_profile(bars, date(2026, 10, 23))
    assert n == 3 and avg[0] == 200 and avg[1] == 10


def test_slot_uses_the_new_york_open_all_year():
    assert alerts_live.slot(datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)) == 0  # 6:30 Phoenix (EDT)
    assert alerts_live.slot(datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)) == 0  # 7:30 Phoenix (EST)
    assert alerts_live.slot(datetime(2026, 11, 2, 13, 30, tzinfo=timezone.utc)) is None


class FakeClient:
    requests = 0

    def __init__(self, sip, iex):
        self.sip, self.iex = sip, iex

    def bars(self, symbols, tf, start, end=None, feed=None, adjustment="raw"):
        self.requests += 1
        src = self.iex if feed == "iex" else self.sip
        out = {}
        for s in symbols:
            out[s] = [b for b in src.get(s, []) if start <= datetime.fromisoformat(b["t"].replace("Z", "+00:00")) <= (end or start + timedelta(days=99))]
        return out, []


def test_refresh_end_to_end(db):
    alerts_live.clear()
    sip = {"AAA": [_raw(OPEN - timedelta(days=1) + timedelta(minutes=5 * k), 100, 100, 100, 100, 1) for k in range(78)]}
    iex = {"AAA": [_raw(OPEN, 100, 101, 99.9, 100.9, 1000)] + [_raw(OPEN - timedelta(days=1) + timedelta(minutes=5 * k), 100, 100, 100, 100, 1000) for k in range(78)]}
    client = FakeClient(sip, iex)
    stats = alerts_live.refresh(["AAA"], lambda s, d: 100.0, now=OPEN + timedelta(minutes=6), client=client)
    assert stats["alerts"] == 1 and len(stats["inserted"]) == 1
    row = alerts_store.list_alerts()[0]
    assert row["setup"] == "A" and row["symbol"] == "AAA"
    # Overnight nothing runs; in premarket only the per-day inputs are prepared.
    assert alerts_live.refresh(["AAA"], lambda s, d: 100.0, now=OPEN - timedelta(hours=4), client=client)["skipped"]
    alerts_live.clear()
    pre = alerts_live.refresh(["AAA"], lambda s, d: 100.0, now=OPEN - timedelta(minutes=30), client=client)
    assert pre["skipped"] and pre["prepared"] == 1


# ------------------------------------------------------------------ API


def test_alerts_api(db):
    from strat.api import app

    alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=OPEN + timedelta(minutes=6))
    c = TestClient(app)
    body = c.get("/api/alerts", params={"session": "2026-10-23"}).json()
    assert body["session"] == "2026-10-23" and len(body["alerts"]) == 1 and body["unread"] == 1
    assert body["sessions"] == ["2026-10-23"]
    assert c.post("/api/alerts/ack", json={"ids": None}).json()["unread"] == 0
    m = c.get("/api/alerts/metrics", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert {r["setup"]: r["count"] for r in m["rows"]}["A"] == 1
    assert c.get("/api/alerts/metrics", params={"symbol": "ZZZ"}).json()["rows"][-1]["count"] == 0
    s = c.put("/api/alerts/settings", json={"bunched_pct": 0.6}).json()
    assert s["settings"]["bunched_pct"] == 0.6 and s["defaults"]["bunched_pct"] == 0.5
    assert c.put("/api/alerts/settings", json={"bunched_pct": -1}).status_code == 422
    assert c.delete("/api/alerts/settings").json()["settings"]["bunched_pct"] == 0.5
    assert c.get("/api/alerts", params={"session": "bad"}).status_code == 422
    assert c.get("/api/status").json()["storage"] == {"backend": "sqlite"}
