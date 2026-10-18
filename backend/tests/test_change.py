import numpy as np
import pandas as pd
import pytest

from strat import change
from strat.change import Snapshot, entered_leaders, rs_change_points, worsened
from strat.scanner import scan_all
from strat.universe import Member


def _frame(close, index: pd.DatetimeIndex) -> pd.DataFrame:
    s = pd.Series(np.asarray(close, dtype=float), index=index)
    return pd.DataFrame({"open": s, "high": s * 1.01, "low": s * 0.99, "close": s, "volume": 2_000_000.0})


def _market(n=320, tails=None, seed=7):
    """QQQ plus 24 stocks with steady, different drifts. ``tails`` maps a symbol to a multiple of its close ``len``
    sessions ago, per session, replacing its last closes (e.g. a collapse in the final sessions)."""
    idx = pd.bdate_range("2025-06-02", periods=n)
    rng = np.random.default_rng(seed)
    members = [Member("QQQ", "QQQ", "Other", "etf", "SP500")]
    closes = {"QQQ": 100 * np.cumprod(1 + rng.normal(0.0004, 0.004, n))}
    for i in range(24):
        sym = f"S{i:02d}"
        members.append(Member(sym, sym, "Industrials", "stock", "SP500"))
        closes[sym] = 100 * np.cumprod(1 + rng.normal(0.0001 + i * 0.00008, 0.006, n))
    for sym, multiples in (tails or {}).items():
        base = closes[sym][-len(multiples) - 1]
        closes[sym][-len(multiples) :] = base * np.asarray(multiples)
    return members, {s: _frame(c, idx) for s, c in closes.items()}


def _rows(members, daily):
    return {r["symbol"]: r for r in scan_all(members, daily).rows}


def _cut(daily, sessions_back):
    cut = daily["QQQ"].index[-1 - sessions_back]
    return {s: df.loc[:cut] for s, df in daily.items()}, cut


def test_prior_rs_is_the_cut_off_scan_of_five_sessions_earlier():
    members, daily = _market()
    rows = _rows(members, daily)
    cut_daily, cut = _cut(daily, change.RS_LOOKBACK)
    older = _rows(members, cut_daily)
    assert len(rows) == 25
    for sym, row in rows.items():
        assert row["rs_prev"] == pytest.approx(older[sym]["rs"], abs=1e-4)
        assert row["rs_prev_date"] == cut.strftime("%Y-%m-%d")
        assert row["rs_change"] == round(row["rs"] * 100) - round(older[sym]["rs"] * 100)


def test_prior_snapshots_match_cut_off_scans_for_rs_and_breakdown_level():
    members, daily = _market(tails={"S20": [0.97, 0.85, 0.70, 0.60]})
    result = scan_all(members, daily)
    assert next(r for r in result.rows if r["symbol"] == "S20")["leadership"]["breakdown"] == "broken"
    levels = set()
    for k in (1, 2, 3):
        cut_daily, _ = _cut(daily, k)
        older = _rows(members, cut_daily)["S20"]
        snap = change.snapshot("stock", daily["S20"], result.prior[k])
        assert snap.level == older["leadership"]["breakdown"]
        assert snap.rs == pytest.approx(older["rs"], abs=1e-4)
        levels.add(snap.level)
    assert len(levels) > 1


def test_a_fresh_collapse_is_flagged_new_with_its_date():
    members, daily = _market(tails={"S23": [1.0, 0.80, 0.60]})
    row = _rows(members, daily)["S23"]
    assert row["leadership"]["breakdown"] == "broken"
    assert row["leadership"]["breakdown_new"] == {
        "from": "none",
        "to": "broken",
        "since": daily["QQQ"].index[-2].strftime("%Y-%m-%d"),
        "sessions_ago": 1,
    }
    assert row["rs_change"] < 0


def test_a_collapse_older_than_three_sessions_is_not_new():
    members, daily = _market(tails={"S23": [1.0, 0.60] + [0.60] * 6})
    row = _rows(members, daily)["S23"]
    assert row["leadership"]["breakdown"] == "broken"
    assert row["leadership"]["breakdown_new"] is None


def test_rows_always_carry_the_change_fields():
    members, daily = _market()
    for row in _rows(members, daily).values():
        assert {"rs_prev", "rs_prev_date", "rs_change"} <= set(row)
        assert {"breakdown_new", "leader_new"} <= set(row["leadership"])
        if row["leadership"]["breakdown"] == "none":
            assert row["leadership"]["breakdown_new"] is None


def test_changes_can_be_switched_off():
    members, daily = _market()
    result = scan_all(members, daily, changes=False)
    assert result.prior == {}
    row = result.rows[0]
    assert row["rs_prev"] is None and row["rs_change"] is None
    assert row["leadership"]["breakdown_new"] is None and row["leadership"]["leader_new"] is None


def test_short_history_has_no_prior_values():
    members, daily = _market(n=34)
    row = scan_all(members, daily).rows[0]
    assert row["rs_prev"] is None and row["rs_change"] is None


def test_prior_sessions_follow_the_cut_off_calendar():
    members, daily = _market()
    cut_daily, _ = _cut(daily, 9)
    result = scan_all(members, cut_daily)
    index = cut_daily["QQQ"].index
    assert {r["rs_prev_date"] for r in result.rows} == {index[-1 - change.RS_LOOKBACK].strftime("%Y-%m-%d")}
    assert result.prior[1].date == index[-2]


def test_calendar_falls_back_to_the_longest_history_without_qqq():
    _, daily = _market()
    del daily["QQQ"]
    short = {**daily, "S00": daily["S00"].iloc[-100:]}
    assert len(change.session_calendar(short)) == len(daily["S01"])
    assert change.session_calendar({}) is None


def test_rs_change_is_measured_in_the_displayed_whole_points():
    assert rs_change_points(0.914, 0.984) == -7  # RS 91 vs RS 98
    assert rs_change_points(0.93, 0.90) == 3
    assert rs_change_points(0.5, None) is None and rs_change_points(None, 0.5) is None


def _snaps(**levels):
    return [Snapshot(int(k[1:]), f"D{k[1:]}", None, v) for k, v in levels.items()]


class TestWorsened:
    def test_none_to_warning_is_new_and_dated_to_the_first_worse_session(self):
        got = worsened("warning", _snaps(k1="none", k2="none", k3="none"), "D0")
        assert got == {"from": "none", "to": "warning", "since": "D0", "sessions_ago": 0}
        got = worsened("warning", _snaps(k1="warning", k2="none", k3="none"), "D0")
        assert got == {"from": "none", "to": "warning", "since": "D1", "sessions_ago": 1}

    def test_warning_to_broken_is_new(self):
        got = worsened("broken", _snaps(k1="warning", k2="warning", k3="none"), "D0")
        assert got == {"from": "warning", "to": "broken", "since": "D0", "sessions_ago": 0}
        got = worsened("broken", _snaps(k1="broken", k2="warning", k3="none"), "D0")
        assert got == {"from": "warning", "to": "broken", "since": "D1", "sessions_ago": 1}

    def test_unchanged_or_improving_is_not_new(self):
        assert worsened("warning", _snaps(k1="warning", k2="warning", k3="warning"), "D0") is None
        assert worsened("warning", _snaps(k1="broken", k2="broken", k3="warning"), "D0") is None
        assert worsened("none", _snaps(k1="broken", k2="warning", k3="none"), "D0") is None
        assert worsened("broken", _snaps(k1="broken", k2="broken", k3="broken"), "D0") is None

    def test_only_the_last_three_sessions_count(self):
        assert worsened("warning", _snaps(k1="warning", k2="warning", k3="warning", k5="none"), "D0") is None

    def test_missing_history_is_not_new(self):
        assert worsened("broken", [], "D0") is None
        assert worsened("broken", [Snapshot(1, "D1", None, None)], "D0") is None


class TestEnteredLeaders:
    @staticmethod
    def _rs(**rs):
        return [Snapshot(int(k[1:]), f"D{k[1:]}", v, None) for k, v in rs.items()]

    def test_crossing_the_gate_within_three_sessions_is_new(self):
        got = entered_leaders(0.93, "none", self._rs(k1=0.91, k2=0.88, k3=0.87), "D0")
        assert got == {"since": "D1", "sessions_ago": 1, "from_rs": 0.88}
        got = entered_leaders(0.91, "warning", self._rs(k1=0.89), "D0")
        assert got == {"since": "D0", "sessions_ago": 0, "from_rs": 0.89}

    def test_already_above_the_gate_broken_or_below_is_not_new(self):
        assert entered_leaders(0.95, "none", self._rs(k1=0.94, k2=0.93, k3=0.92), "D0") is None
        assert entered_leaders(0.95, "broken", self._rs(k1=0.80), "D0") is None
        assert entered_leaders(0.85, "none", self._rs(k1=0.80), "D0") is None
        assert entered_leaders(None, "none", self._rs(k1=0.80), "D0") is None
        assert entered_leaders(0.95, "none", self._rs(k1=None, k5=0.5), "D0") is None
