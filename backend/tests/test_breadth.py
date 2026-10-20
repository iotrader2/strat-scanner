import pandas as pd

from strat.breadth import new_52w_extreme, parse_fear_greed, parse_nasi, universe_breadth
from strat.leadership import HIGH_52W_BARS

NASI = """$NASI, Daily
Day       Date       Open       High        Low      Close      Volume
=== ========== ========== ========== ========== ========== ===========
Thu 10-15-2026   -742.550   -742.550   -742.550   -742.550           0
Wed 10-14-2026   -728.630   -728.630   -728.630   -728.630           0
Tue 10-13-2026    12.000     12.000     12.000     12.000           0
"""

FEAR = {
    "fear_and_greed": {
        "score": 17.94,
        "rating": "extreme fear",
        "previous_close": 31.5,
        "previous_1_week": 46.4,
        "previous_1_month": 27.3,
    }
}

def _frame(n, *, high=None, low=None, close=None):
    idx = pd.bdate_range(end="2026-10-16", periods=n)
    close_s = pd.Series(100.0 if close is None else close, index=idx, dtype=float)
    high_s = pd.Series(101.0 if high is None else high, index=idx, dtype=float)
    low_s = pd.Series(99.0 if low is None else low, index=idx, dtype=float)
    return pd.DataFrame({"open": close_s, "high": high_s, "low": low_s, "close": close_s, "volume": 1.0})


def _last(frame, column, value):
    out = frame.copy()
    out.iloc[-1, out.columns.get_loc(column)] = value
    return out


def test_nasi_is_chronological_with_the_latest_close_and_day_change():
    nasi = parse_nasi(NASI)
    assert [p["time"] for p in nasi["points"]] == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert nasi["points"][0]["value"] == 12.0
    assert nasi["value"] == -742.55
    assert nasi["change"] == -13.92
    assert nasi["as_of"] == "2026-10-15"


def test_nasi_keeps_only_the_recent_window():
    lines = ["$NASI, Daily"] + [
        f"Mon 01-{(i % 28) + 1:02d}-2024   {float(i):.3f}   {float(i):.3f}   {float(i):.3f}   {float(i):.3f}           0"
        for i in range(1, 301)
    ]
    assert len(parse_nasi("\n".join(lines))["points"]) == 252


def test_nasi_rejects_an_empty_table():
    assert parse_nasi("not a quote table") is None


def test_fear_and_greed_reads_the_score_rating_and_history():
    assert parse_fear_greed(FEAR) == {
        "score": 17.9,
        "rating": "extreme fear",
        "previous_close": 31.5,
        "previous_week": 46.4,
        "previous_month": 27.3,
    }
    assert parse_fear_greed({}) is None
    assert parse_fear_greed({"fear_and_greed": {"rating": "fear"}}) is None


def test_new_52w_extreme_needs_a_full_prior_year_and_a_break_of_that_range():
    long = _frame(HIGH_52W_BARS + 1)
    assert new_52w_extreme(long) == (False, False)
    assert new_52w_extreme(_last(long, "high", 101.5)) == (True, False)
    assert new_52w_extreme(_last(long, "low", 98.5)) == (False, True)
    both = _last(_last(long, "high", 130.0), "low", 70.0)
    assert new_52w_extreme(both) == (True, True)
    # One session short of a 52-week window, even if today is the highest print we have.
    short = _last(_frame(HIGH_52W_BARS), "high", 200.0)
    assert new_52w_extreme(short) == (False, False)
    assert new_52w_extreme(None) == (False, False)
    assert new_52w_extreme(pd.DataFrame()) == (False, False)


def test_new_52w_extreme_ignores_a_missing_today_print():
    long = _frame(HIGH_52W_BARS + 1)
    assert new_52w_extreme(_last(long, "high", float("nan"))) == (False, False)


def test_universe_breadth_counts_up_down_and_52w_extremes_for_tracked_names():
    long = _frame(HIGH_52W_BARS + 1)
    rows = [
        {"symbol": "UP", "change_pct": 1.25},
        {"symbol": "DOWN", "change_pct": -0.4},
        {"symbol": "FLAT", "change_pct": 0},
        {"symbol": "HIGH", "change_pct": 3.0},
        {"symbol": "LOW", "change_pct": -2.0},
        {"symbol": "BOTH", "change_pct": 0.1},
        {"symbol": "SHORT", "change_pct": 0.5},
        {"symbol": "SKIP", "change_pct": None},
        {"change_pct": 1.0},
        "not-a-row",
    ]
    daily = {
        "UP": long,
        "DOWN": long,
        "FLAT": long,
        "HIGH": _last(long, "high", 125.0),
        "LOW": _last(long, "low", 80.0),
        "BOTH": _last(_last(long, "high", 140.0), "low", 60.0),
        "SHORT": _last(_frame(40), "high", 200.0),
    }
    assert universe_breadth(rows, daily) == {
        "issues": {"advancing": 4, "declining": 2, "unchanged": 1, "names": 7},
        "highs_lows": {"highs": 2, "lows": 2, "names": 7},
    }


def test_universe_breadth_hides_highs_until_daily_bars_are_loaded():
    rows = [{"symbol": "QQQ", "change_pct": 0.2}, {"symbol": "SPY", "change_pct": -0.1}]
    assert universe_breadth(rows, None)["highs_lows"] is None
    assert universe_breadth(rows, {})["highs_lows"] is None
    assert universe_breadth(rows, None)["issues"] == {
        "advancing": 1,
        "declining": 1,
        "unchanged": 0,
        "names": 2,
    }


def test_universe_breadth_is_empty_without_rows():
    assert universe_breadth([], {}) is None
    assert universe_breadth(None, {}) is None
    assert universe_breadth([{"symbol": "X", "change_pct": True}], {}) is None
