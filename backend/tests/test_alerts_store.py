"""Alerts persistence, settings, the live merge of SIP / IEX bars, and the alerts API."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from strat import alerts, alerts_live, alerts_store, config
from strat.alerts import Context, Settings, simulate

OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    return None  # functions use the default user database (SQLite at CACHE_DB in tests)


def _bars(rows):
    return [
        {"t": OPEN + timedelta(minutes=15 * i), "o": o, "h": h, "l": l, "c": c, "v": 1000.0}
        for i, (o, h, l, c) in enumerate(rows)
    ]


CTX = Context(ma_tail={120: [99.0 + 0.01 * k for k in range(10)]}, prev_close=101.0)


def _alerts(symbol, rows):
    return simulate(symbol, "2026-10-23", _bars(rows), CTX)


# A pullback to the rising 120 EMA (it ended the prior session at 99.09) on the opening bar.
A_ROWS = [(100.5, 100.8, 99.1, 100.2)]


def test_insert_then_update_outcome_by_key(db):
    now = OPEN + timedelta(minutes=16)
    first = alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=now)
    assert len(first["inserted"]) == 1 and not first["inserted"][0]["late"]
    rows = alerts_store.list_alerts(session="2026-10-23")
    assert rows[0]["status"] == "pending" and rows[0]["fired_at"] == "2026-10-23T13:45:00Z"
    assert rows[0]["top"] and not rows[0]["acknowledged"]
    # Next poll: bar 2 fills it.
    alerts_store.acknowledge()
    later = alerts_store.save_session(
        "2026-10-23", _alerts("AAA", A_ROWS + [(100.2, 101.3, 100.1, 101.2)]), now=now + timedelta(minutes=15)
    )
    assert later["inserted"] == [] and later["updated"] == 1
    row = alerts_store.list_alerts(session="2026-10-23")[0]
    assert row["status"] == "triggered" and row["filled"] and row["fill_price"] == 100.81
    # The trigger is a second alert: reported, and the row is unread again.
    assert later["triggered"] == [{"id": row["id"], "symbol": "AAA", "setup": "120"}]
    assert not row["acknowledged"]
    assert row["detected_at"] == "2026-10-23T13:46:00Z"  # fire / detection times never move


def test_backfilled_alert_is_late(db):
    saved = alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=OPEN + timedelta(minutes=40))
    assert saved["inserted"][0]["late"]


def test_top_is_first_three_names_and_sticks(db):
    now = OPEN + timedelta(minutes=16)
    for sym in ("AAA", "BBB", "CCC"):
        alerts_store.save_session("2026-10-23", _alerts(sym, A_ROWS), now=now)
    alerts_store.save_session("2026-10-23", _alerts("DDD", A_ROWS), now=now)
    top = {r["symbol"]: r["top"] for r in alerts_store.list_alerts(session="2026-10-23")}
    assert top == {"AAA": True, "BBB": True, "CCC": True, "DDD": False}


def test_acknowledge(db):
    alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS) + _alerts("BBB", A_ROWS), now=OPEN + timedelta(minutes=16))
    ids = [r["id"] for r in alerts_store.list_alerts()]
    assert alerts_store.unread_count() == 2
    alerts_store.acknowledge([ids[0]])
    assert alerts_store.unread_count() == 1
    alerts_store.acknowledge()
    assert alerts_store.unread_count() == 0


def test_settings_round_trip_and_validation(db):
    assert alerts_store.load_settings() == Settings()
    s = alerts_store.save_settings({"hold_pct": 0.5, "top_names": 4, "max_symbols": 80})
    assert s.hold_pct == 0.5 and s.top_names == 4 and s.max_symbols == 80
    assert alerts_store.load_settings().top_names == 4
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"nope": 1})
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"hold_pct": 99})
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"ma_120": 0, "ma_240": 0, "ma_480": 0})
    assert alerts_store.reset_settings() == Settings()


# ------------------------------------------------------------------ live merge


def _raw(t, o, h, l, c, v):
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": l, "c": c, "v": v}


def test_merge_day_prices_from_sip_volume_from_iex():
    day = date(2026, 10, 23)
    pm = OPEN - timedelta(minutes=30)
    sip = [_raw(pm, 99, 99.5, 98.0, 99.2, 50000), _raw(OPEN, 100, 101, 99.9, 100.9, 90000)]
    iex = [_raw(OPEN, 100.02, 100.98, 99.95, 100.88, 1200), _raw(OPEN + timedelta(minutes=15), 100.9, 101.2, 100.8, 101.1, 800),
           _raw(OPEN + timedelta(minutes=30), 101.1, 101.3, 101.0, 101.2, 700)]
    cutoff = OPEN + timedelta(minutes=15)
    now = OPEN + timedelta(minutes=31)  # the 14:00 bar is still forming
    bars, pm_low = alerts_live.merge_day(sip, iex, day, cutoff, now)
    assert pm_low == 98.0
    assert len(bars) == 2
    assert (bars[0]["h"], bars[0]["v"]) == (101, 1200)  # SIP prices, IEX volume
    assert (bars[1]["h"], bars[1]["v"]) == (101.2, 800)  # IEX after the cutoff


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


def _rising_history(days=7, start=90.0, step=0.01):
    """Regular-session SIP bars on the days before OPEN, rising, so the 120 EMA is known and rising."""
    rows, v = [], start
    for d in range(days, 0, -1):
        for k in range(26):
            rows.append(_raw(OPEN - timedelta(days=d) + timedelta(minutes=15 * k), v, v, v, v, 1))
            v = round(v + step, 4)
    return rows


def test_refresh_keeps_the_daily_setup_on_the_alert(db):
    alerts_live.clear()
    history = _rising_history()
    ctx = alerts.context_from_closes(alerts_live.regular_closes(history, OPEN.date()))
    ma, last = ctx.ma_tail[120][-1], ctx.prev_close
    touch = _raw(OPEN, last, last + 0.3, round(ma, 2), last - 0.1, 1000)
    client = FakeClient({"AAA": history}, {"AAA": [touch]})
    labels = {"AAA": {"long": ["Flat Base Breakout"], "short": []}}
    stats = alerts_live.refresh(["AAA"], now=OPEN + timedelta(minutes=16), client=client, daily_setups=labels)
    assert stats["alerts"] == 1
    row = alerts_store.list_alerts()[0]
    assert row["setup"] == "120" and row["details"]["daily_setups"] == ["Flat Base Breakout"]
    alerts_live.clear()


def test_refresh_end_to_end(db):
    alerts_live.clear()
    history = _rising_history()
    ctx = alerts.context_from_closes(alerts_live.regular_closes(history, OPEN.date()))
    ma, last = ctx.ma_tail[120][-1], ctx.prev_close
    touch = _raw(OPEN, last, last + 0.3, round(ma, 2), last - 0.1, 1000)
    forming = _raw(OPEN + timedelta(minutes=15), last, last + 0.5, last - 0.05, last + 0.4, 500)
    client = FakeClient({"AAA": history}, {"AAA": [touch]})
    stats = alerts_live.refresh(["AAA"], now=OPEN + timedelta(minutes=16), client=client)
    assert stats["alerts"] == 1 and len(stats["inserted"]) == 1
    row = alerts_store.list_alerts()[0]
    assert row["setup"] == "120" and row["symbol"] == "AAA" and row["status"] == "pending"
    assert row["trigger_price"] == round(last + 0.31, 2)
    # Five minutes later the forming candle trades through the buy stop: triggered before it closes.
    client.iex["AAA"].append(forming)
    stats = alerts_live.refresh([], now=OPEN + timedelta(minutes=21), client=client)
    assert stats["symbols"] == 1  # kept because its alert is live, even off the list
    assert len(stats["triggered"]) == 1
    assert alerts_store.list_alerts()[0]["status"] == "triggered"
    # Overnight nothing runs; in premarket only the per-day inputs are prepared.
    assert alerts_live.refresh(["AAA"], now=OPEN - timedelta(hours=4), client=client)["skipped"]
    alerts_live.clear()
    pre = alerts_live.refresh(["AAA"], now=OPEN - timedelta(minutes=30), client=client)
    assert pre["skipped"] and pre["prepared"] == 1


def test_forming_bar_is_the_next_slot_only():
    day = OPEN.date()
    iex = [_raw(OPEN, 1, 2, 1, 2, 1), _raw(OPEN + timedelta(minutes=15), 2, 3, 2, 3, 1)]
    now = OPEN + timedelta(minutes=20)
    assert alerts_live.forming_bar(iex, day, 1, now)["h"] == 3
    assert alerts_live.forming_bar(iex, day, 2, now) is None
    assert alerts_live.forming_bar(iex, day, 1, OPEN + timedelta(minutes=31)) is None


def test_alert_symbols_are_names_with_a_long_daily_setup():
    from strat.api import alert_daily_labels, alert_symbols

    long_d = {"tf": "D", "kind": "flat-base", "label": "Flat Base Breakout", "side": "long"}
    short_d = {"tf": "D", "kind": "flat-base-short", "label": "Flat Base Breakdown", "side": "short"}
    rows = [
        {"symbol": "AAA", "kind": "stock", "in_universe": True, "score": 91, "setups": [long_d]},
        {"symbol": "BBB", "kind": "stock", "in_universe": True, "score": 40, "setups": [long_d]},  # any score
        {"symbol": "CCC", "kind": "etf", "in_universe": True, "score": 95, "setups": [long_d]},
        {"symbol": "DDD", "kind": "stock", "in_universe": False, "score": 99, "setups": [short_d]},  # short only
        {"symbol": "EEE", "kind": "stock", "in_universe": True, "score": 75, "setups": []},  # no daily setup
        {"symbol": "theme-x", "kind": "theme", "score": 99, "setups": [long_d]},
        {"symbol": "FFF", "kind": "stock", "in_universe": False, "score": None, "setups": [long_d]},
        {"symbol": "GGG", "kind": "stock", "in_universe": True, "score": 99, "setups": [{**long_d, "tf": "W"}]},
    ]
    assert alert_symbols(rows, Settings()) == ["CCC", "AAA", "BBB", "FFF"]
    assert alert_symbols(rows, Settings(max_symbols=1)) == ["CCC"]
    labels = alert_daily_labels(rows)
    assert labels["AAA"] == {"long": ["Flat Base Breakout"], "short": []}
    assert labels["DDD"] == {"long": [], "short": ["Flat Base Breakdown"]}
    assert "EEE" not in labels and "theme-x" not in labels and "GGG" not in labels


# ------------------------------------------------------------------ API


def test_alerts_attach_live_15m_ema_without_fetching(db, monkeypatch):
    """The alerts payload reads the lists poll's EMA memory. It does not call Alpaca."""
    from strat import watch15m
    from strat.api import State, app

    watch15m.clear()
    State.scan = []
    alerts_store.save_session(
        "2026-10-23", _alerts("AAA", A_ROWS) + _alerts("BBB", A_ROWS), now=OPEN + timedelta(minutes=16)
    )
    monkeypatch.setattr(watch15m, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched on request")))
    try:
        with TestClient(app) as c:
            with watch15m._lock:
                watch15m._ema["AAA"] = {
                    "price": 101.2,
                    "basis": "live",
                    "time": "2026-10-23T14:00:00Z",
                    "bar_time": "2026-10-23T13:55:00Z",
                    "ema6": 100.0,
                    "ema20": 102.0,
                    "vs6": "above",
                    "vs20": "below",
                    "highlight": [],
                    "highlight_bar": None,
                    "highlight_until": None,
                }
            body = c.get("/api/alerts", params={"session": "2026-10-23"}).json()
        assert set(body["ema5m"]) == {"AAA", "BBB"}
        assert body["ema5m"]["AAA"]["vs6"] == "above"
        assert body["ema5m"]["AAA"]["vs20"] == "below"
        assert body["ema5m"]["AAA"]["ema6"] == 100.0
        assert body["ema5m"]["AAA"]["price"] == 101.2
        assert body["ema5m"]["BBB"] is None
        assert "ema5m" not in body["alerts"][0]
    finally:
        watch15m.clear()
        State.scan = []


def test_alerts_api(db):
    from strat.api import State, app

    alerts_store.save_session("2026-10-23", _alerts("AAA", A_ROWS), now=OPEN + timedelta(minutes=16))
    c = TestClient(app)
    State.scan = []
    missing = c.get("/api/alerts", params={"session": "2026-10-23"}).json()["alerts"][0]
    assert missing["score"] is None and missing["score_breakdown"] == []
    State.scan = [{
        "symbol": "AAA", "score": 88.4, "score_raw": 60.0, "score_max_raw": 72,
        "score_breakdown": [{"key": "rs", "label": "Relative strength", "points": 18, "max_points": 24, "weight_pct": 33, "detail": "Top decile", "sub_weights": []}],
    }]
    try:
        body = c.get("/api/alerts", params={"session": "2026-10-23"}).json()
    finally:
        State.scan = []
    assert body["session"] == "2026-10-23" and len(body["alerts"]) == 1 and body["unread"] == 1
    assert body["alerts"][0]["score"] == 88.4
    assert body["alerts"][0]["score_breakdown"][0]["key"] == "rs"
    assert body["sessions"] == ["2026-10-23"]
    assert c.post("/api/alerts/ack", json={"ids": None}).json()["unread"] == 0
    m = c.get("/api/alerts/metrics", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert {r["setup"]: r["count"] for r in m["rows"]}["120"] == 1
    assert c.get("/api/alerts/metrics", params={"symbol": "ZZZ"}).json()["rows"][-1]["count"] == 0
    s = c.put("/api/alerts/settings", json={"hold_pct": 0.6}).json()
    assert s["settings"]["hold_pct"] == 0.6 and s["defaults"]["hold_pct"] == 0.3
    assert c.put("/api/alerts/settings", json={"hold_pct": -1}).status_code == 422
    assert c.delete("/api/alerts/settings").json()["settings"]["hold_pct"] == 0.3
    assert c.get("/api/alerts", params={"session": "bad"}).status_code == 422
    assert c.get("/api/status").json()["storage"] == {"backend": "sqlite"}


def test_regular_closes_drop_premarket_and_after_hours():
    day = OPEN.date()
    prev = OPEN - timedelta(days=1)
    rows = [_raw(prev - timedelta(minutes=30), 1, 1, 1, 1, 1), _raw(prev, 2, 2, 2, 2, 1),
            _raw(prev + timedelta(hours=6, minutes=25), 3, 3, 3, 3, 1), _raw(prev + timedelta(hours=6, minutes=30), 4, 4, 4, 4, 1),
            _raw(OPEN, 5, 5, 5, 5, 1)]
    assert alerts_live.regular_closes(rows, day) == [2.0, 3.0]


def test_ensure_profiles_keeps_only_the_ema_tails(db):
    alerts_live.clear()
    sip = {"AAA": _rising_history(days=25)}
    client = FakeClient(sip, {"AAA": []})
    assert alerts_live.ensure_profiles(client, ["AAA"], OPEN.date()) == 1
    closes = alerts_live.regular_closes(sip["AAA"], OPEN.date())
    assert len(closes) >= 480
    p = alerts_live._profiles["AAA"]
    assert set(p["tail"]) == {120, 240, 480}
    assert p["tail"][480][-1] == pytest.approx(alerts.ema_seed(closes, 480))
    assert p["prev_close"] == closes[-1]
    ctx = alerts_live.context_for("AAA", 26)
    assert ctx.ma_tail[120] == p["tail"][120] and ctx.prev_close == closes[-1]
    # Same day, another call: nothing fetched. A name that leaves the list keeps its profile today.
    before = client.requests
    assert alerts_live.ensure_profiles(client, ["BBB"], OPEN.date()) == 1
    assert "AAA" in alerts_live._profiles and client.requests == before + 1
    assert alerts_live.ensure_profiles(client, ["AAA"], OPEN.date()) == 0


def test_a_name_off_the_list_only_advances_its_alert_and_never_starts_one(db):
    """A low-score name kept for tracking (or one with an old A-F row) must not get a new pullback alert."""
    from strat.alerts import Alert

    alerts_live.clear()
    history = _rising_history()
    ctx = alerts.context_from_closes(alerts_live.regular_closes(history, OPEN.date()))
    ma, last = ctx.ma_tail[120][-1], ctx.prev_close
    touch = _raw(OPEN, last, last + 0.3, round(ma, 2), last - 0.1, 1000)
    # MU had an alert from the old watchlist rules still open today.
    old = Alert(symbol="MU", session="2026-10-23", setup="D", origin_bar=OPEN - timedelta(minutes=15),
                setup_bar=OPEN - timedelta(minutes=15), setup_index=0, trigger=1.0, stop=0.5,
                setup_low=0.6, setup_high=0.99, ref_price=0.9)
    alerts_store.save_session("2026-10-23", [old], now=OPEN)
    client = FakeClient({"MU": history}, {"MU": [touch]})
    stats = alerts_live.refresh([], now=OPEN + timedelta(minutes=16), client=client)
    assert stats["skipped"] and stats["symbols"] == 0  # the old row does not pull MU into the poll
    assert [r["setup"] for r in alerts_store.list_alerts()] == ["D"]

    # A new-rules alert that is live keeps MU tracked, but the same touch cannot mint a second alert.
    watch = alerts.simulate("MU", "2026-10-23", [alerts_live._bar(touch)], ctx)
    assert len(watch) == 1
    alerts_store.save_session("2026-10-23", watch, now=OPEN + timedelta(minutes=16))
    nxt = _raw(OPEN + timedelta(minutes=15), last, last + 0.05, round(ma, 2) - 0.01, last - 0.05, 1000)
    client.iex["MU"].append(nxt)
    stats = alerts_live.refresh([], now=OPEN + timedelta(minutes=31), client=client)
    assert stats["symbols"] == 1 and stats["inserted"] == []
    assert sorted(r["setup"] for r in alerts_store.list_alerts()) == ["120", "D"]
