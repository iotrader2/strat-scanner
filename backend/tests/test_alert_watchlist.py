"""After the close the watchlist is cleared, then the next session's alert names are added."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from strat import api, config, data
from strat.alerts import Settings

ET = ZoneInfo("America/New_York")
# 16:01 ET. November 2026 is standard time, so this is 2:01 PM Phoenix.
MONDAY = datetime(2026, 11, 9, 16, 1, tzinfo=ET)
TUESDAY = datetime(2026, 11, 10, 16, 1, tzinfo=ET)
SUNDAY = datetime(2026, 11, 8, 12, 0, tzinfo=ET)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return tmp_path


def test_the_first_sync_of_the_day_clears_alert_names_then_adds(db):
    data.add_to_watchlist("KEEP")
    data.sync_alert_watchlist(["OLD"], include_manual=False, now=MONDAY)
    assert data.watch_sources()["OLD"] == "alert"
    # Before the next close: a name that fell off the list stays, and a new one is appended.
    again = data.sync_alert_watchlist(["NEW"], include_manual=False, now=MONDAY.replace(hour=11))
    assert again["reset"] is False
    assert data.watchlist() == ["KEEP", "OLD", "NEW"]
    # Next close: yesterday's alert names are gone, the one still qualifying is added back, the manual name stays.
    nxt = data.sync_alert_watchlist(["OLD"], include_manual=False, now=TUESDAY)
    assert nxt["reset"] is True and nxt["added"] == ["OLD"]
    assert data.watchlist() == ["KEEP", "OLD"]
    assert "NEW" not in data.watchlist()


def test_a_name_that_still_qualifies_is_not_wiped_by_its_own_reset(db):
    data.sync_alert_watchlist(["SAME"], include_manual=False, now=MONDAY)
    data.sync_alert_watchlist(["SAME"], include_manual=False, now=TUESDAY)
    assert data.watchlist() == ["SAME"]
    assert data.watch_sources()["SAME"] == "alert"


def test_reset_manual_clears_names_you_added(db):
    data.add_to_watchlist("MINE")
    data.sync_alert_watchlist(["AAA"], include_manual=False, now=MONDAY)
    data.sync_alert_watchlist(["BBB"], include_manual=True, now=TUESDAY)
    assert data.watchlist() == ["BBB"]


def test_an_empty_qualifying_list_still_clears_yesterdays_alert_names(db):
    data.sync_alert_watchlist(["OLD"], include_manual=False, now=MONDAY)
    data.add_to_watchlist("MINE")
    nxt = data.sync_alert_watchlist([], include_manual=False, now=TUESDAY)
    assert nxt["reset"] is True and nxt["added"] == []
    assert data.watchlist() == ["MINE"]


def test_a_weekend_does_not_reset_or_add(db):
    data.sync_alert_watchlist(["AAA"], include_manual=False, now=MONDAY)
    data.add_to_watchlist("MINE")
    skipped = data.sync_alert_watchlist(["ZZZ"], include_manual=False, now=SUNDAY)
    assert skipped == {"reset": False, "added": [], "session": None, "setups_changed": 0}
    assert data.watchlist() == ["AAA", "MINE"]


def test_adding_an_alert_name_yourself_keeps_it(db):
    data.sync_alert_watchlist(["KEEP"], include_manual=False, now=MONDAY)
    data.add_to_watchlist("KEEP")
    assert data.watch_sources()["KEEP"] == "manual"
    data.sync_alert_watchlist(["OTHER"], include_manual=False, now=TUESDAY)
    assert data.watchlist() == ["KEEP", "OTHER"]


def test_rows_saved_before_source_existed_count_as_manual(db, tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY, added_at TEXT NOT NULL)")
    conn.execute("INSERT INTO watchlist(symbol, added_at) VALUES ('OLD', '2026-01-01T00:00:00')")
    conn.commit()
    conn.close()
    # Point the user database at this file and let the migration add source.
    import strat.config as config_mod
    # fixture already set CACHE_DB; reopen through the migrated connection by swapping the path.
    config_mod.CACHE_DB = path
    assert data.watch_sources()["OLD"] == "manual"
    assert data.watch_setups()["OLD"] == []
    data.sync_alert_watchlist(["NEW"], include_manual=False, now=MONDAY)
    assert data.watchlist() == ["OLD", "NEW"]


def test_the_alert_refresh_adds_qualifying_names(db, monkeypatch):
    api.State.scan_key = "2026-11-09"
    api.State.scan = [{
        "symbol": "AAA", "kind": "stock", "score": 90, "rs": 0.2, "avg_dollar_volume": 50_000_000, "atr_pct": 5.0, "atr_pct": 5.0,
        "theme_strength": {"rank": 1, "total": 4},
        "setups": [{"tf": "D", "kind": "ema-crossback", "label": "EMA Crossback", "side": "long", "triggered": False}],
    }]
    monkeypatch.setattr(api.config, "AS_OF", None)
    try:
        api._sync_alert_watchlist(Settings())
        assert data.watchlist() == ["AAA"]
        assert data.watch_sources()["AAA"] == "alert"
        assert data.watch_setups()["AAA"] == [{"kind": "ema-crossback", "label": "EMA Crossback", "side": "long"}]
    finally:
        api.State.scan_key = None
        api.State.scan = []


def test_sync_stores_setups_and_refreshes_them(db):
    ep = {"kind": "episodic-pivot", "label": "Episodic Pivot", "side": "long"}
    cross = {"kind": "ema-crossback", "label": "EMA Crossback", "side": "long"}
    ma10 = {"kind": "ma-overcut-fail", "label": "MA Overcut and Fail (10-day)", "side": "short", "period": 10}
    ma20 = {"kind": "ma-overcut-fail", "label": "MA Overcut and Fail (20-day)", "side": "short", "period": 20}
    data.add_to_watchlist("MINE")
    data.sync_alert_watchlist(
        ["AAA", "BBB"], setups={"AAA": [ep, cross], "BBB": [ma10, ma20]}, include_manual=False, now=MONDAY,
    )
    assert data.watch_setups()["AAA"] == [ep, cross]
    assert data.watch_setups()["BBB"] == [ma10, ma20]
    assert data.watch_setups()["MINE"] == []
    # Same day: AAA's setups change, BBB no longer qualifies but stays on the list with a dash.
    data.sync_alert_watchlist(["AAA"], setups={"AAA": [ep]}, include_manual=False, now=MONDAY.replace(hour=11))
    assert data.watchlist() == ["MINE", "AAA", "BBB"]
    assert data.watch_setups()["AAA"] == [ep]
    assert data.watch_setups()["BBB"] == []
    # Starring AAA keeps it, and a later sync still refreshes the setups while it qualifies.
    data.add_to_watchlist("AAA")
    data.sync_alert_watchlist(["AAA"], setups={"AAA": [ep, cross]}, include_manual=False, now=MONDAY.replace(hour=12))
    assert data.watch_sources()["AAA"] == "manual"
    assert data.watch_setups()["AAA"] == [ep, cross]
    # Next close AAA no longer qualifies, so the column clears. The new auto name carries its setup.
    data.sync_alert_watchlist(["CCC"], setups={"CCC": [cross]}, include_manual=False, now=TUESDAY)
    assert data.watchlist() == ["MINE", "AAA", "CCC"]
    assert data.watch_setups()["AAA"] == []
    assert data.watch_setups()["CCC"] == [cross]


def _stock(symbol, score=50, rs=0.5, setups=(), rank=None, total=4, kind="stock"):
    row = {"symbol": symbol, "kind": kind, "score": score, "rs": rs, "setups": list(setups), "avg_dollar_volume": 50_000_000, "atr_pct": 5.0}
    if rank is not None:
        row["theme_strength"] = {"rank": rank, "total": total}
    return row


_LONG = {"tf": "D", "kind": "ema-crossback", "label": "EMA Crossback", "side": "long", "triggered": False}
_SHORT = {"tf": "D", "kind": "flat-base-breakdown", "label": "Flat Base Breakdown", "side": "short", "triggered": False}


def test_a_manual_name_with_no_setup_is_checked_long(db):
    data.add_to_watchlist("MINE")
    data.sync_alert_watchlist(["STAR"], include_manual=False, now=MONDAY)
    data.add_to_watchlist("STAR")  # starred: the user kept an auto-added name
    data.add_to_watchlist("THEME")
    longs, shorts, labels = api.alert_refresh_inputs(
        [_stock("MINE"), _stock("STAR"), _stock("THEME", kind="theme")],
        Settings(theme_gate=0),
    )
    assert longs == ["MINE", "STAR"]
    assert shorts == []
    assert labels["MINE"]["long"] == [{"kind": "watchlist", "label": "Watchlist", "side": "long"}]
    assert labels["STAR"]["long"] == labels["MINE"]["long"]


def test_a_manual_name_that_qualifies_short_stays_short(db):
    data.add_to_watchlist("ZZZ")
    scan = [_stock("ZZZ", score=10, rs=0.05, setups=[_SHORT], rank=4)]
    longs, shorts, labels = api.alert_refresh_inputs(scan, Settings(short_flat=1))
    assert shorts == ["ZZZ"]
    assert "ZZZ" not in longs
    assert labels["ZZZ"]["short"][0]["kind"] == "flat-base-breakdown"
    assert not any(ref.get("kind") == "watchlist" for ref in labels["ZZZ"].get("long") or [])


def test_manual_names_skip_the_theme_gate_and_the_cap(db):
    data.add_to_watchlist("MINE")
    scan = [
        _stock("AAA", score=90, rs=0.2, setups=[_LONG], rank=1),
        _stock("MINE", score=1, rs=0.9, setups=[{"tf": "D", "kind": "episodic-pivot", "label": "Episodic Pivot", "side": "long"}], rank=4),
    ]
    longs, _, labels = api.alert_refresh_inputs(scan, Settings(max_symbols=1))
    assert longs == ["AAA", "MINE"]
    assert [ref["kind"] for ref in labels["AAA"]["long"]] == ["ema-crossback"]
    assert [ref["kind"] for ref in labels["MINE"]["long"]] == ["episodic-pivot", "watchlist"]


def test_the_manual_watchlist_toggle_off_restores_the_old_list(db):
    data.add_to_watchlist("MINE")
    scan = [_stock("MINE"), _stock("AAA", score=90, setups=[_LONG], rank=1)]
    longs, shorts, labels = api.alert_refresh_inputs(scan, Settings(alert_manual_watchlist=0))
    assert longs == ["AAA"] and shorts == []
    assert "MINE" not in labels


def test_auto_added_names_are_not_checked_unless_they_qualify(db):
    data.sync_alert_watchlist(["AUTO"], include_manual=False, now=MONDAY)
    scan = [
        _stock("AUTO"),
        _stock("QUAL", score=90, setups=[_LONG], rank=1),
    ]
    longs, _, labels = api.alert_refresh_inputs(scan, Settings())
    assert longs == ["QUAL"]
    assert [ref["kind"] for ref in labels["QUAL"]["long"]] == ["ema-crossback"]
    assert "AUTO" not in labels


def test_a_thin_manual_name_still_alerts(db):
    data.add_to_watchlist("MINE")
    scan = [_stock("MINE", setups=[_LONG], rank=1)]
    scan[0]["avg_dollar_volume"] = 1_000_000
    auto = _stock("AUTO", score=90, setups=[_LONG], rank=1)
    auto["avg_dollar_volume"] = 1_000_000
    # The ATR slider does not apply to manual names either.
    longs, _, labels = api.alert_refresh_inputs([scan[0], auto], Settings(min_avg_dollar_volume=10_000_000, atr_pct_min=8))
    assert longs == ["MINE"]
    assert "AUTO" not in longs


def test_a_manual_name_at_or_under_3_pct_atr_does_not_alert(db):
    for sym in ("LOW", "EDGE", "HIGH"):
        data.add_to_watchlist(sym)
    rows = [_stock("LOW"), _stock("EDGE"), _stock("HIGH")]
    rows[0]["atr_pct"], rows[1]["atr_pct"], rows[2]["atr_pct"] = 0.2, 3.0, 3.5
    longs, shorts, _ = api.alert_refresh_inputs(rows, Settings())
    assert longs == ["HIGH"] and shorts == []


def test_an_off_universe_manual_name_waits_for_its_scan_row(db):
    # Without a scan row there is no ATR %, so it cannot clear the 3% floor yet.
    data.add_to_watchlist("SOFI")
    data.save_extra_symbol("SOFI", "SoFi", "Financials", "stock", "Banks")
    longs, shorts, labels = api.alert_refresh_inputs([], Settings())
    assert longs == [] and shorts == []
    row = _stock("SOFI")
    row["atr_pct"] = 4.2
    longs, _, labels = api.alert_refresh_inputs([row], Settings())
    assert longs == ["SOFI"]
    assert labels["SOFI"]["long"][0]["kind"] == "watchlist"


def test_one_minute_before_the_close_does_not_reset(db):
    data.add_to_watchlist("KEEP")
    early = data.sync_alert_watchlist(["OLD"], include_manual=False, now=MONDAY.replace(minute=0))
    assert early["reset"] is False
    assert data.watchlist() == ["KEEP", "OLD"]
    reset = data.sync_alert_watchlist(["NEXT"], include_manual=False, now=MONDAY)
    assert reset["reset"] is True and reset["session"] == "2026-11-10" and reset["added"] == ["NEXT"]
    assert data.watchlist() == ["KEEP", "NEXT"]
    # The same close does not clear again; a new qualifier is appended.
    later = data.sync_alert_watchlist(["ALSO"], include_manual=False, now=MONDAY.replace(minute=30))
    assert later["reset"] is False and later["added"] == ["ALSO"]
    assert data.watchlist() == ["KEEP", "NEXT", "ALSO"]


def test_friday_close_loads_monday_and_the_weekend_does_not(db):
    friday = datetime(2026, 11, 13, 16, 1, tzinfo=ET)
    done = data.sync_alert_watchlist(["FRI"], include_manual=False, now=friday)
    assert done["reset"] is True and done["session"] == "2026-11-16"
    saturday = datetime(2026, 11, 14, 16, 1, tzinfo=ET)
    skipped = data.sync_alert_watchlist(["SAT"], include_manual=False, now=saturday)
    assert skipped == {"reset": False, "added": [], "session": None, "setups_changed": 0}
    assert data.watchlist() == ["FRI"]


def test_a_restart_during_the_session_does_not_wipe_a_missed_close(db):
    # Wednesday's close loaded Thursday. Thursday's close never ran. Monday morning must not wipe.
    wednesday = datetime(2026, 11, 4, 16, 1, tzinfo=ET)
    data.add_to_watchlist("KEEP")
    data.sync_alert_watchlist(["WED"], include_manual=False, now=wednesday)
    assert data.watchlist_session() == "2026-11-05"
    monday_open = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    mid = data.sync_alert_watchlist(["MON"], include_manual=False, now=monday_open)
    assert mid["reset"] is False
    assert data.watchlist() == ["KEEP", "WED", "MON"]
    # After 16:01 the same day, the missed reset runs and loads Tuesday.
    caught = data.sync_alert_watchlist(["TUE"], include_manual=False, now=MONDAY)
    assert caught["reset"] is True and caught["session"] == "2026-11-10" and caught["added"] == ["TUE"]
    assert data.watchlist() == ["KEEP", "TUE"]


def test_the_close_reset_waits_for_a_scan_then_clears_and_adds(db, monkeypatch):
    data.add_to_watchlist("KEEP")
    data.sync_alert_watchlist(["OLD"], include_manual=False, now=datetime(2026, 11, 9, 10, 0, tzinfo=ET))
    api.State.scan_key = None
    api.State.scan = []
    monkeypatch.setattr(api.config, "AS_OF", None)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: None)
    assert api._close_watchlist_reset(MONDAY) is False
    assert data.watchlist() == ["KEEP", "OLD"]
    api.State.scan_key = "ready"
    api.State.scan = [_stock("NEXT", score=90, setups=[_LONG], rank=1)]
    assert api._close_watchlist_reset(MONDAY) is True
    assert data.watchlist_session() == "2026-11-10"
    assert data.watchlist() == ["KEEP", "NEXT"]

    def fail_scan(force=False):
        raise AssertionError("the stored close must not scan again")

    monkeypatch.setattr(api, "_ensure_scan", fail_scan)
    assert api._close_watchlist_reset(MONDAY) is True
    assert data.watchlist() == ["KEEP", "NEXT"]
    api.State.scan_key = None
    api.State.scan = []


def test_the_close_reset_does_not_run_before_1601(db):
    assert api._close_watchlist_reset(datetime(2026, 11, 9, 16, 0, tzinfo=ET)) is False
    assert api._close_watchlist_reset(datetime(2026, 11, 14, 16, 1, tzinfo=ET)) is False


def test_a_scan_that_has_not_finished_does_not_clear_the_list(db, monkeypatch):
    data.add_to_watchlist("MINE")
    api.State.scan_key = None
    api.State.scan = []
    monkeypatch.setattr(api.config, "AS_OF", None)
    api._sync_alert_watchlist(Settings(reset_manual=1))
    assert data.watchlist() == ["MINE"]
