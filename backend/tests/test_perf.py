import pandas as pd
import pytest

from strat.perf import MOMENTUM_WEIGHTS, MomentumRanks, blend, period_returns


def _close(values, end="2026-10-15"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_weights_sum_to_one_and_favor_the_medium_term():
    assert sum(MOMENTUM_WEIGHTS.values()) == pytest.approx(1.0)
    assert MOMENTUM_WEIGHTS == {"1m": 0.20, "3m": 0.40, "6m": 0.40}


class TestPeriodReturns:
    def test_calendar_month_returns_use_the_close_on_or_before_the_start_date(self):
        close = _close([100.0 + i for i in range(200)])
        last = close.index[-1]
        got = period_returns(close)
        for period, months in (("1m", 1), ("3m", 3), ("6m", 6)):
            base = close[: last - pd.DateOffset(months=months)].iloc[-1]
            assert got[period] == pytest.approx((close.iloc[-1] / base - 1) * 100, abs=0.01)

    def test_a_flat_then_doubling_series(self):
        idx = pd.bdate_range(end="2026-10-15", periods=200)
        close = pd.Series(50.0, index=idx)
        close[close.index > pd.Timestamp("2026-09-15")] = 100.0
        got = period_returns(close)
        assert got["1m"] == pytest.approx(100.0)
        assert got["3m"] == pytest.approx(100.0)
        assert got["6m"] == pytest.approx(100.0)

    def test_negative_returns(self):
        got = period_returns(_close([100.0] * 150 + [80.0] * 50))
        assert got["1m"] == pytest.approx(0.0)
        assert got["3m"] < 0 or got["3m"] == pytest.approx(0.0)

    def test_short_history_leaves_the_longer_periods_empty(self):
        got = period_returns(_close([100.0 + i for i in range(30)]))
        assert got["1m"] is not None
        assert got["3m"] is None and got["6m"] is None

    def test_empty_series(self):
        assert period_returns(pd.Series(dtype=float)) == {"1m": None, "3m": None, "6m": None}


class TestBlend:
    def test_weighted_average(self):
        assert blend({"1m": 1.0, "3m": 0.5, "6m": 0.0}) == pytest.approx(0.2 * 1.0 + 0.4 * 0.5)

    def test_missing_periods_renormalize_the_weights(self):
        assert blend({"1m": 0.8, "3m": None, "6m": None}) == pytest.approx(0.8)
        assert blend({"1m": None, "3m": 1.0, "6m": 0.0}) == pytest.approx(0.5)

    def test_nothing_available(self):
        assert blend({"1m": None, "3m": None, "6m": None}) is None


class TestRanks:
    PEERS = {
        "stock": {
            "A": {"1m": -10.0, "3m": -10.0, "6m": -10.0},
            "B": {"1m": 0.0, "3m": 0.0, "6m": 0.0},
            "C": {"1m": 10.0, "3m": 10.0, "6m": 10.0},
            "D": {"1m": 20.0, "3m": None, "6m": None},
        },
        "theme": {"X": {"1m": 5.0, "3m": 5.0, "6m": 5.0}, "Y": {"1m": 6.0, "3m": 6.0, "6m": 6.0}},
    }

    def test_percentile_places_the_value_among_its_peers_with_ties_in_the_middle(self):
        ranks = MomentumRanks.from_perf(self.PEERS)
        assert ranks.percentile("stock", "1m", -10.0) == pytest.approx(0.5 / 4)
        assert ranks.percentile("stock", "1m", 20.0) == pytest.approx(3.5 / 4)
        assert ranks.percentile("stock", "1m", 100.0) == 1.0
        assert ranks.percentile("stock", "1m", -100.0) == 0.0
        assert ranks.percentile("stock", "1m", None) is None
        assert ranks.percentile("nobody", "1m", 1.0) is None

    def test_missing_returns_do_not_count_as_peers(self):
        ranks = MomentumRanks.from_perf(self.PEERS)
        assert ranks.peers("stock", "1m") == 4 and ranks.peers("stock", "3m") == 3

    def test_groups_are_ranked_separately(self):
        ranks = MomentumRanks.from_perf(self.PEERS)
        stock = ranks.momentum("stock", {"1m": 5.0, "3m": 5.0, "6m": 5.0})
        theme = ranks.momentum("theme", {"1m": 5.0, "3m": 5.0, "6m": 5.0})
        assert stock.blended == pytest.approx((0.2 * 2 / 4) + 0.8 * (2 / 3))
        assert theme.blended == pytest.approx(0.25)  # lowest of two themes: (0 + 0.5) / 2 for the tie
        assert stock.group == "stock" and theme.group == "theme"

    def test_blended_is_none_without_any_return(self):
        ranks = MomentumRanks.from_perf(self.PEERS)
        assert ranks.momentum("stock", {"1m": None, "3m": None, "6m": None}).blended is None
