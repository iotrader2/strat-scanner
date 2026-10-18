from datetime import date, datetime, timezone

import pandas as pd
import pytest

from strat import config, data
from strat.adjust import apply_splits
from strat.provider import FetchResult, get_provider, splits_in


def _frame(closes, start="2026-05-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
        index=idx,
    )


def test_a_split_after_the_view_date_does_not_rewrite_prices():
    df = _frame([400.0, 400.0, 100.0])
    ex = df.index[2].strftime("%Y-%m-%d")
    before = apply_splits(df, [(ex, 4.0)], df.index[1])
    assert before is df
    assert before.iloc[0]["close"] == 400.0


def test_a_split_on_or_before_the_view_date_adjusts_earlier_bars_only():
    df = _frame([400.0, 400.0, 100.0])
    ex = df.index[2].strftime("%Y-%m-%d")
    out = apply_splits(df, [(ex, 4.0)], df.index[2])
    assert out.iloc[0]["close"] == 100.0
    assert out.iloc[0]["volume"] == 4000.0
    assert out.iloc[2]["close"] == 100.0
    assert out.iloc[2]["volume"] == 1000.0


def test_a_reverse_split_multiplies_earlier_prices():
    df = _frame([10.0, 10.0, 100.0])
    ex = df.index[2].strftime("%Y-%m-%d")
    out = apply_splits(df, [(ex, 0.1)], "2026-12-31")
    assert out.iloc[0]["close"] == pytest.approx(100.0)
    assert out.iloc[2]["close"] == pytest.approx(100.0)


def test_as_of_hides_a_later_split_from_the_loader(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    raw = _frame([400.0] * 5 + [100.0] * 5, start="2026-06-01").rename(columns=str.title)
    data.save_bars("AAA", raw)
    ex = raw.index[5].strftime("%Y-%m-%d")
    data.save_splits("AAA", [(ex, 4.0)])

    monkeypatch.setattr(config, "AS_OF", raw.index[4].strftime("%Y-%m-%d"))
    assert data.load_daily("AAA").iloc[-1]["close"] == 400.0

    monkeypatch.setattr(config, "AS_OF", raw.index[5].strftime("%Y-%m-%d"))
    adjusted = data.load_daily("AAA")
    assert adjusted.iloc[0]["close"] == 100.0
    assert adjusted.iloc[-1]["close"] == 100.0
    assert data.load_all_daily(adjust=False)["AAA"].iloc[0]["close"] == 400.0


def test_session_bar_is_today_only_and_stays_out_of_a_cut_off_view(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    confirmed = pd.DataFrame(
        {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5], "Volume": [100.0]},
        index=pd.to_datetime(["2026-10-16"]),
    )
    data.save_bars("AAA", confirmed)
    data.save_session_bar(
        "AAA",
        pd.DataFrame(
            {"Open": [10.5], "High": [12.0], "Low": [10.0], "Close": [11.5], "Volume": [50.0]},
            index=pd.to_datetime(["2026-10-19"]),
        ),
    )
    live = data.load_daily("AAA")
    assert list(live.index) == [pd.Timestamp("2026-10-16"), pd.Timestamp("2026-10-19")]
    assert live.iloc[-1]["close"] == 11.5

    monkeypatch.setattr(config, "AS_OF", "2026-10-19")
    assert data.load_daily("AAA").index[-1] == pd.Timestamp("2026-10-16")


def test_an_open_session_keeps_today_out_of_confirmed_bars():
    idx = pd.to_datetime(["2026-10-16", "2026-10-19"])
    df = pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [12.0, 13.0], "Low": [9.0, 10.0], "Close": [11.0, 12.0], "Volume": [1.0, 2.0]},
        index=idx,
    )
    midday = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
    done, session = data._split_partial(df, midday)
    assert list(done.index) == [pd.Timestamp("2026-10-16")]
    assert session is not None and session.index[-1] == pd.Timestamp("2026-10-19")

    after = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)  # 17:00 ET
    done, session = data._split_partial(df, after)
    assert session is None and len(done) == 2


def test_refresh_stores_raw_bars_and_splits(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")

    class Fake:
        name = "fake"

        def fetch_history(self, symbols, period):
            idx = pd.to_datetime(["2026-10-16", "2026-10-19"])
            frame = pd.DataFrame(
                {
                    "Open": [40.0, 11.0],
                    "High": [41.0, 12.0],
                    "Low": [39.0, 10.0],
                    "Close": [40.0, 11.0],
                    "Volume": [100.0, 400.0],
                    "Stock Splits": [0.0, 4.0],
                },
                index=idx,
            )
            return FetchResult(frames={"AAA": frame}, splits={"AAA": splits_in(frame)})

    monkeypatch.setattr("strat.provider.get_provider", lambda: Fake())
    monkeypatch.setattr("strat.scheduler.regular_session", lambda clock: False)
    saved = data.refresh(["AAA"], full=True)
    assert saved["AAA"] == 2
    assert data.load_splits()["AAA"] == [("2026-10-19", 4.0)]
    assert data.newest_bar_date() == date(2026, 10, 19)
    raw = data.load_all_daily(adjust=False)["AAA"]
    assert raw.iloc[0]["close"] == 40.0


def test_unknown_provider_name_is_rejected(monkeypatch):
    monkeypatch.setenv("STRAT_DATA_PROVIDER", "massive")
    with pytest.raises(ValueError):
        get_provider()
