"""Alpaca provider: mocked HTTP only. No test touches the network or reads real keys."""

import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from strat import alpaca, config, data, intraday, scheduler
from strat.alpaca import AlpacaClient, RateLimiter, from_alpaca, period_start, pick_feed, to_alpaca
from strat.candles import Setup
from strat.provider import AlpacaProvider, active_name, get_provider

UTC = timezone.utc
ET = scheduler.ET


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")


class FakeHTTP:
    """Routes a request to ``handler(params) -> (status, payload)`` and records every call."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, url, headers):
        parsed = urllib.parse.urlparse(url)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        params["_path"] = parsed.path
        self.calls.append(params)
        assert headers["APCA-API-KEY-ID"] == "test-key"
        assert headers["APCA-API-SECRET-KEY"] == "test-secret"
        status, payload = self.handler(params)
        return status, {}, json.dumps(payload).encode()


def client(handler):
    http = FakeHTTP(handler)
    return AlpacaClient(transport=http, limiter=RateLimiter(10_000), sleep=lambda s: None), http


def bar(t, o=10.0, h=11.0, l=9.0, c=10.5, v=100):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


# --- symbols, periods, feed -------------------------------------------------------------------


def test_class_shares_map_to_dot_form_and_back():
    assert to_alpaca("BRK-B") == "BRK.B"
    assert to_alpaca("bf-b") == "BF.B"
    assert to_alpaca("QQQ") == "QQQ"
    assert from_alpaca("BRK.B") == "BRK-B"


def test_period_strings_become_start_dates():
    today = date(2026, 10, 22)
    assert period_start("3y", today) == date(2023, 10, 22)
    assert period_start("3mo", today) == date(2026, 7, 22)
    assert period_start("5d", today) <= today - timedelta(days=9)
    assert period_start("max", today) == date(2016, 1, 1)


def test_old_end_stays_on_sip():
    now = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    end = now - timedelta(minutes=30)
    assert pick_feed(end, now) == ("sip", end)


def test_recent_or_missing_end_is_clamped_on_sip_by_default():
    now = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    feed, end = pick_feed(now - timedelta(minutes=2), now)
    assert feed == "sip" and end <= now - timedelta(minutes=15)
    feed, end = pick_feed(None, now)
    assert feed == "sip" and end <= now - timedelta(minutes=15)


def test_recent_end_can_use_delayed_sip(monkeypatch):
    monkeypatch.setattr(alpaca, "RECENT_FEED", "delayed_sip")
    now = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    recent = now - timedelta(minutes=2)
    assert pick_feed(recent, now) == ("delayed_sip", recent)
    assert pick_feed(now - timedelta(hours=1), now)[0] == "sip"


# --- HTTP: pagination, invalid symbols, retries ----------------------------------------------


def test_bars_follow_next_page_token_and_map_symbols():
    pages = {
        None: {"bars": {"AAA": [bar("2026-10-20T04:00:00Z")]}, "next_page_token": "p2"},
        "p2": {"bars": {"AAA": [bar("2026-10-21T04:00:00Z")], "BRK.B": [bar("2026-10-20T04:00:00Z")]}, "next_page_token": None},
    }
    c, http = client(lambda p: (200, pages[p.get("page_token")]))
    out, invalid = c.bars(["AAA", "BRK-B"], "1Day", date(2026, 10, 1))
    assert len(http.calls) == 2
    assert http.calls[0]["symbols"] == "AAA,BRK.B"
    assert http.calls[0]["feed"] == "sip" and http.calls[0]["adjustment"] == "raw"
    assert [r["t"][:10] for r in out["AAA"]] == ["2026-10-20", "2026-10-21"]
    assert "BRK-B" in out and invalid == []


def test_symbols_are_batched(monkeypatch):
    monkeypatch.setattr(alpaca, "SYMBOLS_PER_REQUEST", 2)
    c, http = client(lambda p: (200, {"bars": {}, "next_page_token": None}))
    c.bars(["A", "B", "C"], "1Day", date(2026, 10, 1))
    assert [call["symbols"] for call in http.calls] == ["A,B", "C"]


def test_an_invalid_symbol_is_dropped_and_the_batch_resent():
    def handler(p):
        if "BAD$" in p["symbols"]:
            return 400, {"message": "invalid symbol: BAD$"}
        return 200, {"bars": {"AAA": [bar("2026-10-20T04:00:00Z")]}, "next_page_token": None}

    c, http = client(handler)
    out, invalid = c.bars(["AAA", "BAD$"], "1Day", date(2026, 10, 1))
    assert invalid == ["BAD$"] and "AAA" in out and len(http.calls) == 2


def test_rate_limit_and_server_errors_are_retried():
    replies = iter([(429, {"message": "too many requests"}), (502, {"message": "bad gateway"}), (200, {"bars": {}})])
    c, http = client(lambda p: next(replies))
    c.bars(["AAA"], "1Day", date(2026, 10, 1))
    assert len(http.calls) == 3


def test_missing_keys_fail_without_a_request(monkeypatch):
    monkeypatch.delenv("ALPACA_API_SECRET_KEY")
    c, http = client(lambda p: (200, {}))
    with pytest.raises(alpaca.AlpacaError):
        c.bars(["AAA"], "1Day", date(2026, 10, 1))
    assert http.calls == []


def test_rate_limiter_waits_once_the_window_is_full():
    clock = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    lim = RateLimiter(2, clock=lambda: clock[0], sleep=sleep)
    lim.wait(); lim.wait(); lim.wait()
    assert slept and clock[0] >= 60


# --- provider ---------------------------------------------------------------------------------


def test_provider_returns_cache_frames_and_splits():
    def handler(p):
        if p["_path"] == "/v1/corporate-actions":
            assert p["types"] == "forward_split,reverse_split,spin_off"
            return 200, {
                "corporate_actions": {
                    "forward_splits": [{"symbol": "AAA", "ex_date": "2026-10-21", "new_rate": 4, "old_rate": 1}],
                    "reverse_splits": [{"symbol": "BRK.B", "ex_date": "2026-10-20", "new_rate": 1, "old_rate": 10}],
                },
                "next_page_token": None,
            }
        return 200, {
            "bars": {
                "AAA": [bar("2026-10-20T04:00:00Z", c=100), bar("2026-10-21T04:00:00Z", o=25.5, c=25)],
                "BRK.B": [bar("2026-10-20T04:00:00Z")],
            },
            "next_page_token": None,
        }

    c, _ = client(handler)
    result = AlpacaProvider(client=c).fetch_history(["AAA", "BRK-B"], "3mo")
    frame = result.frames["AAA"]
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert [d.strftime("%Y-%m-%d") for d in frame.index] == ["2026-10-20", "2026-10-21"]
    assert frame.index.tz is None
    assert result.splits == {"AAA": [("2026-10-21", 4.0)], "BRK-B": [("2026-10-20", 0.1)]}


def _frame(rows):
    return alpaca.daily_frame([bar(t, o=o, c=c) for t, o, c in rows])


def test_a_reported_split_without_a_price_gap_is_ignored():
    # HON 2026-06-29: Alpaca lists a 1-for-2 reverse split, but the stock opened where it closed.
    frame = _frame([("2026-06-26T04:00:00Z", 231, 232.21), ("2026-06-29T04:00:00Z", 228.5, 227.8)])
    splits, spins = alpaca.validate_actions(frame, {"splits": [("2026-06-29", 0.5)], "spinoffs": ["2026-06-29"]})
    assert splits == [] and spins == []  # a 1.6% gap is not a spin-off adjustment either


def test_a_real_reverse_split_is_kept():
    frame = _frame([("2026-06-23T04:00:00Z", 47, 46.67), ("2026-06-24T04:00:00Z", 139.0, 137.82)])
    splits, _ = alpaca.validate_actions(frame, {"splits": [("2026-06-24", 1 / 3)], "spinoffs": []})
    assert splits == [("2026-06-24", 1 / 3)]


def test_a_spin_off_becomes_a_price_factor_from_the_ex_date_gap():
    frame = _frame([("2026-09-30T04:00:00Z", 87, 87.5), ("2026-10-01T04:00:00Z", 12.5, 12.57)])
    _, spins = alpaca.validate_actions(frame, {"splits": [], "spinoffs": ["2026-10-01"]})
    assert spins == [("2026-10-01", 7.0)]


def test_spin_off_factor_adjusts_prices_but_not_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite3")
    raw = pd.DataFrame(
        {"Open": [80.0, 12.0], "High": [81.0, 13.0], "Low": [79.0, 11.0], "Close": [80.0, 12.5], "Volume": [1000.0, 1000.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-09-30"), pd.Timestamp("2026-10-01")]),
    )
    data.save_bars("CTVA", raw)
    data.save_spinoffs("CTVA", [("2026-10-01", 6.4)])
    df = data.load_daily("CTVA")
    assert df.close.iloc[0] == pytest.approx(12.5)
    assert df.volume.iloc[0] == 1000.0
    assert df.close.iloc[1] == 12.5


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("STRAT_DATA_PROVIDER", raising=False)
    assert active_name() == "alpaca"  # keys present (fixture)
    monkeypatch.setenv("STRAT_DATA_PROVIDER", "yahoo")
    assert get_provider().name == "yahoo"
    monkeypatch.setenv("STRAT_DATA_PROVIDER", "alpaca")
    assert get_provider().name == "alpaca"
    monkeypatch.delenv("STRAT_DATA_PROVIDER")
    monkeypatch.delenv("ALPACA_API_KEY_ID")
    assert active_name() == "yahoo"


# --- intraday: 5-minute bars -> today's daily bar ----------------------------------------------


def _intraday_handler(iex, sip, calls):
    def handler(p):
        calls.append(p)
        rows = iex if p["feed"] == "iex" else sip
        return 200, {"bars": rows, "next_page_token": None}

    return handler


def test_poll_builds_todays_bar_from_iex_and_keeps_volume_to_sip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite3")
    now = datetime(2026, 10, 22, 14, 0, 12, tzinfo=UTC)  # 10:00:12 ET
    iex = {
        "AAA": [
            bar("2026-10-22T13:30:00Z", o=10, h=10.5, l=9.8, c=10.2, v=50),
            bar("2026-10-22T13:35:00Z", o=10.2, h=10.9, l=10.1, c=10.8, v=40),
            bar("2026-10-22T13:55:00Z", o=10.8, h=11.4, l=10.7, c=11.3, v=30),
        ]
    }
    sip = {"AAA": [bar("2026-10-22T13:30:00Z", o=10.01, h=10.55, l=9.75, c=10.2, v=5000)]}
    calls = []
    c, _ = client(_intraday_handler(iex, sip, calls))
    stats = intraday.poll(["AAA"], now=now, client=c)
    assert stats["symbols"] == 1
    sip_call = next(p for p in calls if p["feed"] == "sip")
    # SIP only asks for bars that closed 15+ minutes ago.
    assert sip_call["end"] == "2026-10-22T13:39:59Z"
    frames = data._session_frames(None)
    day = frames["AAA"].iloc[-1]
    assert frames["AAA"].index[-1] == pd.Timestamp("2026-10-22")
    assert day.open == 10.01  # SIP open replaced the IEX one
    assert day.high == 11.4 and day.low == 9.75 and day.close == 11.3
    assert day.volume == 5000  # IEX volume is never added to the daily volume


def test_sip_backfill_overwrites_iex_and_iex_never_overwrites_sip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite3")
    t = "2026-10-22T13:30:00Z"
    intraday.upsert([("AAA", t, 1, 2, 0.5, 1.5, 10)], "iex")
    intraday.upsert([("AAA", t, 1.01, 2.02, 0.49, 1.5, 999)], "sip")
    intraday.upsert([("AAA", t, 9, 9, 9, 9, 1)], "iex")
    with data.connect() as conn:
        row = conn.execute("SELECT high, low, volume, feed FROM intraday_bars").fetchone()
    assert row == (2.02, 0.49, 999, "sip")


def test_backfill_advances_and_old_sessions_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite3")
    intraday.upsert([("AAA", "2026-10-21T19:55:00Z", 1, 1, 1, 1, 1)], "sip")  # yesterday
    calls = []
    c, _ = client(_intraday_handler({}, {}, calls))
    intraday.poll(["AAA"], now=datetime(2026, 10, 22, 14, 0, 12, tzinfo=UTC), client=c)
    with data.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM intraday_bars").fetchone()[0] == 0
    first_sip = [p for p in calls if p["feed"] == "sip"][0]
    calls.clear()
    intraday.poll(["AAA"], now=datetime(2026, 10, 22, 14, 5, 12, tzinfo=UTC), client=c)
    second_sip = [p for p in calls if p["feed"] == "sip"][0]
    assert first_sip["start"] == "2026-10-22T13:30:00Z" and first_sip["end"] == "2026-10-22T13:39:59Z"
    assert second_sip["start"] == "2026-10-22T13:40:00Z" and second_sip["end"] == "2026-10-22T13:44:59Z"


def test_poll_before_the_open_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite3")
    c, http = client(lambda p: (200, {"bars": {}}))
    assert intraday.poll(["AAA"], now=datetime(2026, 10, 22, 13, 0, tzinfo=UTC), client=c)["requests"] == 0
    assert http.calls == []


# --- scheduler alignment ----------------------------------------------------------------------


def test_aligned_poll_runs_once_per_five_minute_mark():
    at = lambda h, m, s: datetime(2026, 10, 22, h, m, s, tzinfo=ET)
    assert not scheduler.intraday_due(at(10, 5, 5), at(10, 0, 11), aligned=True)  # before 10:05:10
    assert scheduler.intraday_due(at(10, 5, 11), at(10, 0, 11), aligned=True)
    assert not scheduler.intraday_due(at(10, 5, 30), at(10, 5, 11), aligned=True)
    assert scheduler.intraday_due(at(16, 0, 12), at(15, 55, 11), aligned=True)  # picks up the 15:55 bar
    assert not scheduler.intraday_due(at(16, 2, 0), at(16, 0, 12), aligned=True)
    assert scheduler.scheduler_sleep(at(10, 4, 58), True) <= 13


# --- IEX tolerance on live trigger breaks -----------------------------------------------------


def test_tolerance_needs_the_live_high_to_clear_the_trigger_by_more_than_it():
    from strat import candles

    def fresh():
        return type("S", (), {"tf": "W", "setups": [Setup("x", "x", 100.0, False, "")]})()

    s = fresh()
    candles.apply_live_triggers(s, 100.04, tolerance=0.05)
    assert not s.setups[0].triggered
    s = fresh()
    candles.apply_live_triggers(s, 100.06, tolerance=0.05)
    assert s.setups[0].triggered
    s = fresh()
    candles.apply_live_triggers(s, 100.01)  # no tolerance: strictly above, as before
    assert s.setups[0].triggered


def test_tolerance_only_while_alpaca_session_bar_is_live(monkeypatch):
    from strat import scanner

    daily = pd.DataFrame({"high": [1.0], "close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-10-22")]))
    session = datetime(2026, 10, 22, 11, 0, tzinfo=ET)
    monkeypatch.setenv("STRAT_DATA_PROVIDER", "alpaca")
    assert scanner.live_trigger_tolerance(daily, session) == config.LIVE_TRIGGER_TOLERANCE
    assert scanner.live_trigger_tolerance(daily, datetime(2026, 10, 22, 17, 0, tzinfo=ET)) == 0.0
    monkeypatch.setenv("STRAT_DATA_PROVIDER", "yahoo")
    assert scanner.live_trigger_tolerance(daily, session) == 0.0
