import sqlite3

import pandas as pd
import pytest

from strat import backtest as bt
from strat import config, data
from strat.universe import Member


def _history(drift, n=420, end="2026-10-15", wobble=0.0):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series([100 + i * drift + (i % 5) * wobble for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 3_000_000.0})


def _market(n_stocks=40):
    members = [Member(f"S{i:02d}", f"S{i:02d}", "Information Technology", "stock", "SP500") for i in range(n_stocks)]
    members += [Member("SPY", "SPY", "Other", "etf", "benchmark"), Member("QQQ", "QQQ", "Other", "etf", "benchmark")]
    hist = {f"S{i:02d}": _history(-0.05 + i * 0.04, wobble=0.5) for i in range(n_stocks)}
    hist["SPY"], hist["QQQ"] = _history(0.1), _history(0.12)
    return members, hist


class TestForwardReturn:
    def test_return_to_the_close_one_month_later(self):
        df = _history(1.0)
        as_of = df.index[200]
        end = df[: as_of + pd.DateOffset(months=1)].close.iloc[-1]
        assert bt.forward_return(df, as_of) == pytest.approx((end / df.close.iloc[200] - 1) * 100)

    def test_none_when_the_window_is_not_fully_observed(self):
        df = _history(1.0)
        assert bt.forward_return(df, df.index[-5]) is None

    def test_none_when_the_symbol_did_not_exist_yet(self):
        df = _history(1.0, n=100)
        assert bt.forward_return(df, df.index[0] - pd.Timedelta(days=30)) is None

    def test_weekend_cutoffs_use_the_last_close_before_them(self):
        df = _history(1.0)
        saturday = pd.Timestamp("2026-05-16")
        assert saturday.dayofweek == 5
        friday_close = df.close[: saturday].iloc[-1]
        end = df.close[: saturday + pd.DateOffset(months=1)].iloc[-1]
        assert bt.forward_return(df, saturday) == pytest.approx((end / friday_close - 1) * 100)


def test_cut_off_drops_later_bars_and_symbols_without_history():
    hist = {"A": _history(1.0), "B": _history(1.0, n=30)}
    cut = bt.cut_off(hist, pd.Timestamp("2026-08-14"))
    assert cut["A"].index[-1] <= pd.Timestamp("2026-08-14")
    assert "B" not in cut  # only 30 bars ending 2026-10-15, none before the cut-off


class TestListStats:
    PICKS = [{"symbol": s} for s in "ABCDEFGHIJ"]

    def test_means_hit_rates_and_winners(self):
        forward = {s: float(i) for i, s in enumerate("ABCDEFGHIJ")}  # A 0 ... J 9
        winners = {"I", "J", "A"}
        st = bt.list_stats(self.PICKS, forward, winners, {"J", "I", "Z"})
        assert st.count == 10
        assert st.top[10] == pytest.approx(4.5) and st.top[30] == pytest.approx(4.5)
        assert st.hit[10] == pytest.approx(0.3)
        assert st.winners_in_top30 == 2

    def test_names_without_a_forward_return_are_skipped(self):
        st = bt.list_stats(self.PICKS, {"A": 10.0, "B": 20.0}, {"A"}, set())
        assert st.top[10] == pytest.approx(15.0) and st.hit[10] == pytest.approx(0.5)

    def test_an_empty_list_has_no_stats(self):
        st = bt.list_stats([], {}, set(), set())
        assert st.count == 0 and st.top[10] is None and st.hit[30] is None


class TestRunDate:
    def test_new_list_is_leaders_only_and_old_list_needs_a_setup(self):
        members, hist = _market()
        snap = bt.run_date(hist, members, None, "2026-06-12", reference=("S39", "S00", "SPY"))
        assert snap.universe > 30
        new, old = snap.variants["new"], snap.variants["old"]
        assert new.count <= 6  # the top decile of 40 stocks, minus anything broken
        assert old.count != new.count
        assert snap.ref_new["S39"] == 1  # the strongest riser leads the list
        assert snap.ref_new["S00"] is None and snap.ref_status["S00"] == "laggard"
        assert snap.ref_status["SPY"] == "leader" or snap.ref_new["SPY"] is None  # ETFs are never in the stock list
        assert snap.ref_fwd["S39"] is not None
        # a persistent riser beats the median name over the next month
        assert new.top[10] > snap.median

    def test_only_data_up_to_the_cutoff_is_used(self):
        members, hist = _market()
        late = {k: v.copy() for k, v in hist.items()}
        for df in late.values():  # a crash after the cut-off must not affect that day's picks
            df.iloc[-40:, :4] *= 0.3
        a = bt.run_date(hist, members, None, "2026-06-12", reference=("S39",))
        b = bt.run_date(late, members, None, "2026-06-12", reference=("S39",))
        assert a.ref_new == b.ref_new and a.variants["new"].count == b.variants["new"].count

    def test_old_comparison_can_be_skipped(self):
        members, hist = _market()
        snap = bt.run_date(hist, members, None, "2026-06-12", reference=("S39",), with_old=False)
        assert "old" not in snap.variants and snap.ref_old == {}


class TestReport:
    def _snaps(self):
        members, hist = _market()
        return [bt.run_date(hist, members, None, d, reference=("S39", "S00")) for d in ("2026-05-15", "2026-06-12")]

    def test_report_has_old_vs_new_and_reference_rank_tables(self):
        report = bt.render_report(self._snaps(), reference=("S39", "S00"))
        assert "Old top 30" in report and "New top 30" in report
        assert "| 2026-05-15 |" in report and "| 2026-06-12 |" in report and "**Average**" in report
        assert "Reference leaders: rank on each date" in report
        assert "**#1**" in report  # S39 leads
        assert "laggard" in report  # S00 is filtered out
        assert "New, leaders that also have a weekly setup" in report

    def test_reference_names_include_pltr(self):
        assert "PLTR" in bt.REFERENCE
        assert {"HPE", "DELL", "MU", "SNDK", "ARM", "NBIS", "AMD"} <= set(bt.REFERENCE)

    def test_default_dates_cover_the_required_window(self):
        assert "2026-08-13" in bt.DEFAULT_DATES
        assert len(bt.DEFAULT_DATES) >= 5
        run = [d for d in bt.DEFAULT_DATES if bt.RUN_START <= d <= bt.RUN_END]
        assert len(run) >= 5  # late April through September 2026
        assert any(d < bt.RUN_START for d in bt.DEFAULT_DATES)  # and other market conditions


class TestTimeline:
    def _points(self, ranks):
        prices = [10, 12, 14, 13, 11, 9]
        return [
            bt.TimelinePoint(f"2026-0{i + 1}-01", r, "leader" if r else "broken", 50.0, p, None)
            for i, (r, p) in enumerate(zip(ranks, prices))
        ]

    def test_demotion_is_the_first_week_off_the_list_after_leading(self):
        d = bt.demotion(self._points([None, 5, 3, 4, None, None]))
        assert d["date"] == "2026-05-01" and d["status"] == "broken"
        assert d["below_peak_pct"] == pytest.approx((14 - 11) / 14 * 100)

    def test_a_name_that_never_led_is_not_demoted(self):
        assert bt.demotion(self._points([None, None, 40, None, None, None])) is None

    def test_timeline_runs_weekly_and_reports_ranks(self):
        members, hist = _market(24)
        series = bt.run_timeline(hist, members, None, "2026-06-05", "2026-06-26", reference=("S23", "S00"))
        assert [p.as_of for p in series["S23"]] == ["2026-06-05", "2026-06-12", "2026-06-19", "2026-06-26"]
        assert all(p.rank == 1 for p in series["S23"]) and all(p.rank is None for p in series["S00"])
        text = bt.render_timeline(series)
        assert "| 2026-06-12 |" in text and "S23" in text and "never a top-30 leader" in text


class TestCutOffView:
    def test_the_as_of_setting_hides_later_bars_from_the_loaders(self, tmp_path, monkeypatch):
        db = tmp_path / "cache.sqlite3"
        monkeypatch.setattr(config, "CACHE_DB", db)
        df = _history(1.0, n=60).rename(columns=str.title)
        data.save_bars("AAA", df)
        assert data.load_daily("AAA").index[-1] == pd.Timestamp("2026-10-15")
        monkeypatch.setattr(config, "AS_OF", "2026-09-30")
        assert data.load_daily("AAA").index[-1] == pd.Timestamp("2026-09-30")
        assert data.load_all_daily()["AAA"].index[-1] == pd.Timestamp("2026-09-30")
        monkeypatch.setattr(config, "AS_OF", None)
        assert len(data.load_all_daily()["AAA"]) == 60
        assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 60
