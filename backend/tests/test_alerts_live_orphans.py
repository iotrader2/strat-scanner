"""ACTIVE alerts missing from simulate still advance via advance_stored + save_session."""

from datetime import datetime, timedelta, timezone

import pytest

from strat import alerts_live, alerts_store, config
from strat.alerts import Alert, Context, Settings


OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    return None


def _bars_setup_then_miss():
    """Setup at index 2 (high 100.5 → trigger 100.51); next 3 bars stay under trigger."""
    rows = [
        (100.0, 100.3, 99.9, 100.2),
        (100.2, 100.35, 100.1, 100.25),
        (100.25, 100.5, 100.1, 100.4),  # setup
        (100.4, 100.45, 100.3, 100.42),
        (100.42, 100.48, 100.35, 100.4),
        (100.4, 100.49, 100.35, 100.45),
        (100.45, 101.0, 100.4, 100.9),  # late print above trigger — after expiry window
    ]
    return [
        {"t": OPEN + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c, "v": 1000.0}
        for i, (o, h, l, c) in enumerate(rows)
    ]


def test_orphan_pending_expires_when_simulate_drops_it(db):
    bars = _bars_setup_then_miss()
    setup_t = bars[2]["t"]
    pending = Alert(
        symbol="TEAM",
        session="2026-10-23",
        setup="E",
        origin_bar=setup_t,
        setup_bar=setup_t,
        setup_index=2,
        trigger=100.51,
        stop=99.9,
        setup_low=100.1,
        setup_high=100.5,
        ref_price=100.4,
        details={"note": "orphan"},
    )
    alerts_store.save_session("2026-10-23", [pending], now=setup_t + timedelta(minutes=5))
    assert alerts_store.list_alerts(session="2026-10-23")[0]["status"] == "pending"

    ctx = Context(warm_closes=[99.0] * 60, session_bars=78)
    # Rematch failed: simulate returns nothing for this key.
    found = []
    advanced = alerts_live._advance_orphans(
        "2026-10-23",
        found,
        {"TEAM": bars},
        {"TEAM": ctx},
        Settings(entry_valid_bars=3),
    )
    assert len(advanced) == 1
    assert advanced[0].status == "expired"
    assert advanced[0].exit_reason == "not_triggered"
    assert not advanced[0].filled

    saved = alerts_store.save_session("2026-10-23", found + advanced, now=OPEN + timedelta(minutes=40))
    assert saved["updated"] == 1
    row = alerts_store.list_alerts(session="2026-10-23")[0]
    assert row["status"] == "expired"
    assert row["exit_reason"] == "not_triggered"
    assert row["trigger_price"] == 100.51  # frozen levels unchanged


def test_known_key_is_not_double_advanced(db):
    bars = _bars_setup_then_miss()
    setup_t = bars[2]["t"]
    a = Alert(
        symbol="TEAM",
        session="2026-10-23",
        setup="E",
        origin_bar=setup_t,
        setup_bar=setup_t,
        setup_index=2,
        trigger=100.51,
        stop=99.9,
        setup_low=100.1,
        setup_high=100.5,
        ref_price=100.4,
    )
    alerts_store.save_session("2026-10-23", [a], now=setup_t + timedelta(minutes=5))
    ctx = Context(warm_closes=[99.0] * 60)
    # Already in found → orphan helper skips
    assert alerts_live._advance_orphans("2026-10-23", [a], {"TEAM": bars}, {"TEAM": ctx}, Settings()) == []
