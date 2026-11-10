"""Completed alert bars use consolidated prices, not the IEX high, once Yahoo or SIP has the candle."""

from datetime import datetime, timezone

import pytest

from strat import alerts_live, alerts_store, config
from strat.alerts import Alert, Settings
from strat.yahoo_15m import fetch_yahoo_15m as fetch_live
from strat.yahoo_15m import parse_chart

# Nov 10 2026 is EST: 9:30 ET is 14:30 UTC. The app's IEX highs vs the consolidated highs that morning.
OPEN_BAR = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
IEX_HIGH = {"TOST": 34.64, "ABBV": 293.675}
REAL_HIGH = {"TOST": 34.67, "ABBV": 294.425}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    return tmp_path


def _raw(t, o, h, l, c, v=1000):
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": l, "c": c, "v": v}


def _chart(symbol: str, high: float, when: datetime = OPEN_BAR) -> dict:
    return {
        "chart": {
            "result": [{
                "timestamp": [int(when.timestamp())],
                "indicators": {"quote": [{
                    "open": [high - 0.2], "high": [high], "low": [high - 0.5],
                    "close": [high - 0.1], "volume": [10000],
                }]},
            }],
            "error": None,
        }
    }


def test_parse_chart_reads_the_consolidated_open_bar():
    bars = parse_chart(_chart("TOST", 34.67), OPEN_BAR.date())
    assert len(bars) == 1
    assert bars[0]["h"] == 34.67 and bars[0]["src"] == "yahoo"
    assert bars[0]["t"] == OPEN_BAR


def test_the_open_bar_uses_yahoo_until_sip_has_it_and_iex_only_if_yahoo_fails(caplog):
    day = OPEN_BAR.date()
    just_after = datetime(2026, 11, 10, 14, 46, tzinfo=timezone.utc)  # 9:46 ET, SIP does not have 9:30 yet
    later = datetime(2026, 11, 10, 15, 1, tzinfo=timezone.utc)  # 10:01 ET, SIP has 9:30
    early_cut = alerts_live.sip_cutoff(just_after)
    late_cut = alerts_live.sip_cutoff(later)

    def iex(high):
        return [_raw(OPEN_BAR, high - 0.3, high, high - 0.4, high - 0.05)]

    def yahoo(high):
        return [_raw(OPEN_BAR, high - 0.2, high, high - 0.5, high - 0.1)]

    for sym, iex_high in IEX_HIGH.items():
        real = REAL_HIGH[sym]
        bars, _ = alerts_live.merge_day([], iex(iex_high), day, early_cut, just_after, yahoo(real))
        assert bars[0]["h"] == real and bars[0]["src"] == "yahoo", sym
        # SIP wins once the candle is old enough, even if Yahoo disagrees.
        sip = [_raw(OPEN_BAR, real - 0.1, real + 0.05, real - 0.4, real)]
        later_bars, _ = alerts_live.merge_day(sip, iex(iex_high), day, late_cut, later, yahoo(real))
        assert later_bars[0]["src"] == "sip" and later_bars[0]["h"] == real + 0.05

    # ABBV with no Yahoo bar keeps the IEX high.
    iex_only, _ = alerts_live.merge_day([], iex(IEX_HIGH["ABBV"]), day, early_cut, just_after, None)
    assert iex_only[0]["h"] == 293.675 and iex_only[0]["src"] == "iex"

    def get(symbol, params):
        assert params["interval"] == "15m"
        if symbol == "ABBV":
            raise RuntimeError("HTTP 503")
        return _chart(symbol, REAL_HIGH["TOST"]), None

    with caplog.at_level("WARNING", logger="strat.yahoo_15m"):
        got, failed = fetch_live(["TOST", "ABBV"], day, just_after, get=get)
    assert failed == {"ABBV"}
    assert got["TOST"][0]["h"] == 34.67
    assert "ABBV" in caplog.text and "IEX" in caplog.text


def test_the_forming_bar_is_judged_on_the_yahoo_high():
    now = datetime(2026, 11, 10, 14, 40, tzinfo=timezone.utc)  # 9:40 ET, the 9:30 bar is still forming
    iex = [_raw(OPEN_BAR, 293.0, IEX_HIGH["ABBV"], 292.5, 293.2)]
    yahoo = [_raw(OPEN_BAR, 293.2, REAL_HIGH["ABBV"], 292.4, 293.9)]
    bar = alerts_live.forming_bar(iex, OPEN_BAR.date(), 0, now, yahoo)
    assert bar["h"] == 294.425 and bar["src"] == "yahoo"
    assert alerts_live.forming_bar(iex, OPEN_BAR.date(), 0, now)["h"] == 293.675


def test_pending_alerts_priced_from_iex_are_repriced_to_the_consolidated_high(db):
    """Today's watches keep their id and move the buy to the real high + 1c. Filled trades stay put."""
    session = "2026-11-10"

    def pending(symbol, high, low=None):
        low = high - 0.4 if low is None else low
        return Alert(
            symbol=symbol, session=session, setup="120",
            origin_bar=OPEN_BAR, setup_bar=OPEN_BAR, setup_index=0,
            trigger=round(high + 0.01, 2), stop=round(round(high + 0.01, 2) * 0.99, 2),
            setup_low=low, setup_high=high, ref_price=high - 0.05,
            details={"bar_feed": "iex"},
        )

    filled = pending("PPG", 110.0)
    filled.filled = True
    filled.status = "triggered"
    filled.fill_price = filled.trigger
    alerts_store.save_session(session, [pending("TOST", 34.64), pending("ABBV", 293.675), filled], now=OPEN_BAR)

    def bar(high):
        return {"t": OPEN_BAR, "o": high - 0.2, "h": high, "l": high - 0.5, "c": high - 0.1, "v": 1, "src": "yahoo"}

    fixed = alerts_live.correct_pending(
        session,
        {"TOST": [bar(34.67)], "ABBV": [bar(294.425)], "PPG": [bar(111.0)]},
        {},
        Settings(),
        set(),
    )
    by = {a.symbol: a for a in fixed}
    assert set(by) == {"TOST", "ABBV"}
    assert by["TOST"].trigger == 34.68 and by["TOST"].setup_high == 34.67
    assert by["TOST"].stop == round(34.68 * 0.99, 2)
    assert by["TOST"].details["bar_feed"] == "yahoo"
    assert by["ABBV"].trigger == round(294.425 + 0.01, 2) == 294.44
    assert by["ABBV"].stop == round(by["ABBV"].trigger * 0.99, 2)
    # The stored filled trade is not rewritten.
    assert alerts_store.list_alerts(session=session, symbol="PPG")[0]["trigger_price"] == round(110.01, 2)
