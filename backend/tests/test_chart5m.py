"""5-minute chart EMAs (including the 360-bar seed) and the per-symbol endpoint."""

import pickle
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import api, chart5m
from strat.alpaca import AlpacaError
from strat.scheduler import CLOSE, ET, OPEN
from strat.watch5m import ema as watch_ema
from strat.watch5m import ema_series as watch_series


def et(day: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm, ss), tzinfo=ET).astimezone(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


THU = date(2026, 10, 22)  # a Thursday


def weekdays_ending(end: date, n: int) -> list[date]:
    days: list[date] = []
    day = end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    return days


def session_bars(day: date, close, start=(9, 30), end=(16, 0)) -> list[dict]:
    out = []
    t = et(day, *start)
    stop = et(day, *end)
    i = 0
    while t < stop:
        px = float(close(day, i) if callable(close) else close)
        out.append({"t": iso(t), "o": px, "h": px + 0.4, "l": px - 0.4, "c": px, "v": 1000 + i})
        t += timedelta(minutes=5)
        i += 1
    return out


class FakeClient:
    """Serves 5-minute bars for one feed map and records every request. No network."""

    def __init__(self, feeds: dict):
        self.feeds = feeds  # {feed: {symbol: [bars]}} or {feed: [bars]} for every symbol
        self.calls: list[dict] = []

    def bars(self, symbols, timeframe, start, end=None, feed=None, adjustment="raw", now=None):
        syms = list(symbols)
        self.calls.append(
            {"symbols": syms, "timeframe": timeframe, "feed": feed, "start": start, "end": end, "adjustment": adjustment}
        )
        sym = syms[0]
        source = self.feeds.get(feed, {})
        rows = source if isinstance(source, list) else source.get(sym, source.get("*", []))
        out = []
        for b in rows:
            ts = chart5m._parse(b["t"])
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue
            out.append(b)
        return ({sym: out} if out else {}), []


@pytest.fixture(autouse=True)
def _fresh():
    chart5m.clear()
    yield
    chart5m.clear()


def test_session_length_is_one_regular_day():
    assert len(session_bars(THU, 1)) == 78


def test_ema_matches_the_sma_seed_then_the_smoothing_constant():
    short = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    series = chart5m.ema_series(short, 5)
    assert series[:4] == [None, None, None, None]
    assert series[4] == pytest.approx(3.0)  # SMA of the first 5
    assert series[5] == pytest.approx(3.0 + (2 / 6) * (6 - 3))
    assert series[-1] == pytest.approx(watch_ema(short, 5))

    long = [float(i) for i in range(1, 401)]
    got = chart5m.ema_series(long, 360)
    assert got[358] is None
    seed = sum(long[:360]) / 360
    assert got[359] == pytest.approx(seed)
    k = 2 / 361
    prev = seed
    for value in long[360:]:
        prev = prev + k * (value - prev)
    assert got[-1] == pytest.approx(prev)
    assert got[-1] == pytest.approx(watch_series(long, 360)[-1])
    # Same recurrence for the other chart lengths.
    for period in (5, 20, 50):
        assert chart5m.ema_series(long, period)[-1] == pytest.approx(watch_ema(long, period))


def _flat_history(sessions: int, price: float, jump_at: int | None = None, jump: float = 130.0) -> list[dict]:
    days = weekdays_ending(THU, sessions)
    rows: list[dict] = []
    for i, day in enumerate(days):
        px = jump if jump_at is not None and i >= jump_at else price
        rows.extend(session_bars(day, px))
    # Premarket, the closing print, and a Saturday bar must not enter the EMA.
    rows.extend(session_bars(THU, 999, start=(4, 0), end=(9, 30)))
    rows.append({"t": iso(et(THU, 16, 0)), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    rows.extend(session_bars(THU + timedelta(days=2), 50))  # Saturday
    return rows


def test_displayed_360_is_seeded_by_the_weeks_before_the_window():
    rows = _flat_history(chart5m.SEED_SESSIONS, 100.0, jump_at=chart5m.SEED_SESSIONS - chart5m.DISPLAY_SESSIONS)
    client = FakeClient({"sip": rows})
    body = chart5m.chart("AAPL", now=et(THU, 17, 0), client=client)

    assert body["session"] == "regular"
    assert body["display_sessions"] == 5 and body["seed_sessions"] == 30
    assert body["sessions"] == 5
    bars = body["bars"]
    assert len(bars) == 5 * 78
    # One SIP history request, for this ticker only, covering the seed lookback.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["symbols"] == ["AAPL"] and call["timeframe"] == "5Min" and call["feed"] == "sip"
    assert call["adjustment"] == "raw"
    assert (THU - call["start"].astimezone(ET).date()).days == chart5m.LOOKBACK_DAYS

    for bar in bars:
        local = datetime.fromtimestamp(bar["time"], ET)
        assert local.weekday() < 5
        assert OPEN <= local.time() < CLOSE
        assert bar["close"] == 130.0
        assert set(bar["ema"]) == {"5", "20", "50", "360"}
        assert all(bar["ema"][p] is not None for p in ("5", "20", "50", "360"))

    # The displayed window is all 130s. A 360 EMA computed on only those bars has no
    # value on the first candle (390 < 360 + 1). The seeded value is still near the
    # prior weeks of 100s: one smoothing step off 100.
    seeded = round(100 + (2 / 361) * (130 - 100), 4)
    assert bars[0]["ema"]["360"] == seeded
    assert bars[0]["ema"]["5"] == pytest.approx(110.0)
    assert bars[-1]["ema"]["360"] < 130
    assert bars[-1]["ema"]["360"] > bars[0]["ema"]["360"]

    # Asking again reuses the cache instead of refetching weeks of bars.
    chart5m.chart("AAPL", now=et(THU, 17, 0), client=client)
    assert len(client.calls) == 1


def test_360_starts_during_the_window_when_only_one_extra_session_seeds_it():
    rows = _flat_history(chart5m.DISPLAY_SESSIONS + 1, 100.0)
    body = chart5m.chart("MSFT", now=et(THU, 17, 0), client=FakeClient({"sip": rows}))
    bars = body["bars"]
    assert len(bars) == 5 * 78
    # One hidden session (78 bars) moves the 360th close 78 bars earlier than a
    # display-only EMA, which would still be empty until index 359.
    first = next(i for i, bar in enumerate(bars) if bar["ema"]["360"] is not None)
    assert first == 359 - 78
    assert bars[first - 1]["ema"]["360"] is None
    assert bars[first]["ema"]["360"] == 100.0


def test_premarket_is_not_a_bar_and_iex_only_covers_the_live_tail():
    today = session_bars(THU, 50, start=(9, 30), end=(10, 40))
    # 10:40 is the SIP cutoff at 11:00 ET, so this SIP print must lose to IEX.
    sip_tail = [{"t": iso(et(THU, 10, 40)), "o": 1, "h": 1, "l": 1, "c": 1, "v": 9}]
    pre = session_bars(THU, 123, start=(8, 0), end=(9, 30))
    iex = [
        {"t": iso(et(THU, 10, 30)), "o": 9, "h": 9, "l": 9, "c": 9, "v": 3},  # older than the cutoff: SIP wins
        {"t": iso(et(THU, 10, 40)), "o": 77, "h": 78, "l": 76, "c": 77, "v": 4},
        {"t": iso(et(THU, 8, 15)), "o": 5, "h": 5, "l": 5, "c": 5, "v": 5},  # premarket IEX
    ]
    history = session_bars(date(2026, 10, 21), 40)
    client = FakeClient({"sip": {"QQQ": history + pre + today + sip_tail}, "iex": {"QQQ": iex}})
    body = chart5m.chart("QQQ", now=et(THU, 11, 0), client=client)
    by_minute = {datetime.fromtimestamp(b["time"], ET).strftime("%H:%M"): b for b in body["bars"] if datetime.fromtimestamp(b["time"], ET).date() == THU}
    assert "08:00" not in by_minute and "09:25" not in by_minute and "08:15" not in by_minute
    assert by_minute["10:30"]["close"] == 50.0  # SIP
    assert by_minute["10:40"]["close"] == 77.0  # IEX
    assert by_minute["10:40"]["volume"] == 4
    assert all(c["symbols"] == ["QQQ"] for c in client.calls)
    assert {c["feed"] for c in client.calls} == {"sip", "iex"}


def test_cache_is_bounded_to_a_handful_of_symbols():
    rows = _flat_history(chart5m.SEED_SESSIONS, 80.0)
    client = FakeClient({"sip": rows})
    now = et(THU, 17, 0)
    names = [f"S{i}" for i in range(chart5m.CACHE_LIMIT + 1)]
    for name in names:
        chart5m.chart(name, now=now, client=client)
    assert len(chart5m._cache) == chart5m.CACHE_LIMIT
    assert "S0" not in chart5m._cache
    assert all(len(call["symbols"]) == 1 for call in client.calls)
    # The evicted name is fetched again; the names still cached are not.
    before = len(client.calls)
    chart5m.chart("S1", now=now, client=client)
    chart5m.chart("S0", now=now, client=client)
    assert len(client.calls) == before + 1
    assert client.calls[-1]["symbols"] == ["S0"]
    stored = next(iter(chart5m._cache.values()))["history"]
    assert stored and isinstance(stored[0], tuple)
    assert len(pickle.dumps(chart5m._cache, protocol=4)) < 8 * 1024 * 1024


def test_endpoint_serves_one_symbol(monkeypatch):
    frame = pd.DataFrame({"close": [1.0]})
    monkeypatch.setattr(api.State, "daily", {"NVDA": frame})
    monkeypatch.setattr(api, "live_bars_enabled", lambda: True)
    rows = _flat_history(chart5m.SEED_SESSIONS, 100.0, jump_at=chart5m.SEED_SESSIONS - chart5m.DISPLAY_SESSIONS)
    fake = FakeClient({"sip": rows})
    monkeypatch.setattr(chart5m, "AlpacaClient", lambda: fake)
    # Freeze "now" so the seed window is the fixture's Thursday, not the wall clock.
    real = chart5m.chart

    def at_thursday(symbol, now=None, client=None):
        return real(symbol, now=now or et(THU, 17, 0), client=client)

    monkeypatch.setattr(chart5m, "chart", at_thursday)
    client = TestClient(api.app)
    res = client.get("/api/symbol/nvda/bars5m")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "NVDA"
    assert body["session"] == "regular"
    assert body["bars"][0]["ema"]["360"] == pytest.approx(round(100 + (2 / 361) * 30, 4))
    assert {tuple(c["symbols"]) for c in fake.calls} == {("NVDA",)}
    before = len(fake.calls)
    assert client.get("/api/symbol/AAPL/bars5m").status_code == 404
    assert len(fake.calls) == before


def test_endpoint_requires_alpaca_and_hides_upstream_errors(monkeypatch):
    frame = pd.DataFrame({"close": [1.0]})
    monkeypatch.setattr(api.State, "daily", {"NVDA": frame})
    monkeypatch.setattr(api, "live_bars_enabled", lambda: False)
    monkeypatch.setattr(chart5m, "AlpacaClient", lambda: (_ for _ in ()).throw(AssertionError("fetched")))
    client = TestClient(api.app)
    unavailable = client.get("/api/symbol/NVDA/bars5m")
    assert unavailable.status_code == 503
    assert "Alpaca" in unavailable.json()["detail"]

    monkeypatch.setattr(api, "live_bars_enabled", lambda: True)

    class Boom:
        def bars(self, *args, **kwargs):
            raise AlpacaError("subscription does not permit querying recent SIP data")

    monkeypatch.setattr(chart5m, "AlpacaClient", lambda: Boom())
    failed = client.get("/api/symbol/NVDA/bars5m")
    assert failed.status_code == 502
    assert "unavailable" in failed.json()["detail"]
    assert "subscription" not in failed.json()["detail"]
