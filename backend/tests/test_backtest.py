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


def _rows(n=120, winners=("W1", "W2"), score_of=None, listed_n=12):
    """A fake market: stock i returns i % 40 % over 1M and twice that over 3M; the winners double their return."""
    rows = []
    for i in range(n):
        sym = f"S{i:03d}"
        f1 = float(i % 40)
        rows.append(dict(symbol=sym, score=float(i), rs=i / n, status="leader" if i >= n - listed_n else "laggard",
                         has_setup=False, listed=i >= n - listed_n, breakout=None, fwd1=f1, fwd3=2 * f1))
    for sym in winners:
        rows.append(dict(symbol=sym, score=500.0 if sym == "W1" else 1.0, rs=0.95, status="leader", has_setup=True,
                         listed=True, breakout=None, fwd1=50.0, fwd3=150.0))
    return rows


class TestRankDate:
    def test_top_n_excess_is_measured_against_the_median_of_all_stocks(self):
        dr = bt.rank_date("2026-01-02", _rows())
        median1 = dr.median[1]
        assert dr.excess[(1, 1)] == pytest.approx(50.0 - median1)  # W1 has the top score
        assert dr.excess[(5, 3)] == pytest.approx((150.0 + 78 + 76 + 74 + 72) / 5 - dr.median[3])
        assert dr.ranks["W1"] == 1 and dr.ranks["S119"] == 2

    def test_spearman_and_capture(self):
        dr = bt.rank_date("2026-01-02", _rows())
        assert dr.spearman is not None and -1 <= dr.spearman <= 1
        assert {"W1", "W2"} <= dr.winners and len(dr.winners) == 10
        assert dr.capture[10] is not None and dr.capture[10] >= 0.1  # W1 is in the first 10
        assert dr.capture[30] >= dr.capture[10]

    def test_a_perfectly_ordered_list_has_spearman_one(self):
        rows = [dict(symbol=f"S{i}", score=float(i), rs=0.99, status="leader", has_setup=True, listed=True, breakout=None,
                     fwd1=float(i), fwd3=float(i)) for i in range(150)]
        dr = bt.rank_date("2026-01-02", rows)
        assert dr.spearman == pytest.approx(1.0)
        assert dr.capture[10] == 1.0 and dr.excess[(1, 3)] > 0

    def test_too_few_names_for_a_median_leaves_the_measures_empty(self):
        dr = bt.rank_date("2026-01-02", _rows(n=20, winners=()))
        assert dr.median[1] is None and dr.excess[(1, 1)] is None and dr.capture[10] is None


class TestSummaryAndLags:
    def _ranks(self, entry_step=2, steps=8):
        out = []
        for k in range(steps):
            rows = _rows(winners=())
            for r in rows:
                if r["symbol"] == "S000":
                    r.update(fwd3=500.0, fwd1=100.0, score=1000.0 if k >= entry_step else -1.0, listed=k >= entry_step)
            out.append(bt.rank_date(f"2026-0{1 + k // 4}-{(k % 4) * 7 + 2:02d}", rows))
        return out

    def test_a_late_entry_has_a_lag_in_sessions(self):
        runs = bt.capture_lags(self._ranks(entry_step=2))
        run = next(r for r in runs if r.symbol == "S000")
        assert run.run_start == "2026-01-02" and run.first_top10 == "2026-01-16" and run.sessions == 10
        summary = bt.lag_summary(runs)
        assert summary["caught"] >= 1 and summary["median_sessions"] is not None

    def test_a_name_never_in_the_top_10_is_not_caught(self):
        runs = bt.capture_lags(self._ranks(entry_step=99))
        assert next(r for r in runs if r.symbol == "S000").sessions is None

    def test_summarize_averages_the_dates_and_split_uses_the_test_start(self):
        ranks = self._ranks()
        parts = bt.split(ranks, "2026-01-16")
        assert [r.as_of for r in parts["train"]] == ["2026-01-02", "2026-01-09"] and len(parts["all"]) == 8
        s = bt.summarize(ranks)
        assert s["dates"] == 8 and s["top1_3m"] is not None and s["capture10"] is not None


class TestBreakoutBacktest:
    def _by_date(self):
        bo = {"week": "2026-01-05", "base_weeks": 5}
        dates = [f"2026-0{1 + i // 2}-{(i % 2) * 14 + 2:02d}" for i in range(8)]
        out = {}
        for i, d in enumerate(dates):
            rows = []
            for j in range(120):
                rows.append(dict(symbol=f"M{j}", score=1.0, rs=0.6, status="laggard", has_setup=False, listed=False,
                                 breakout=None, fwd1=1.0, fwd3=3.0))
            # B breaks out at date 0 (mid-pack) and is a leader from date 3 on
            rows.append(dict(symbol="B", score=1.0, rs=0.97 if i >= 3 else 0.6, status="leader" if i >= 3 else "laggard",
                             has_setup=False, listed=i >= 3, breakout=bo if i == 0 else None, fwd1=10.0, fwd3=30.0))
            out[d] = rows
        return out, dates

    def test_pick_needs_a_breakout_rs_and_an_unbroken_trend(self):
        base = dict(breakout={"week": "w"}, rs=0.6, status="laggard")
        assert bt.is_breakout_pick(base)
        assert not bt.is_breakout_pick({**base, "rs": 0.4})
        assert not bt.is_breakout_pick({**base, "status": "broken"})
        assert not bt.is_breakout_pick({**base, "breakout": None})

    def test_returns_are_versus_the_median_and_leaders_are_counted(self):
        by_date, dates = self._by_date()
        s = bt.breakout_stats(by_date)
        assert s.events == 1 and s.fwd1 == pytest.approx(9.0) and s.fwd3 == pytest.approx(27.0)
        assert s.beat_1m == 1.0 and s.became_leader == 1.0  # B led two dates later
        assert s.baseline_became_leader is not None and s.baseline_became_leader < 0.1

    def test_examples_name_the_first_breakout_and_the_first_leader_date(self):
        by_date, dates = self._by_date()
        ex = bt.breakout_examples(by_date, ["B", "M1"])
        assert ex[0].breakouts == [dates[0]] and ex[0].leader_entries == [dates[3]]
        assert ex[0].caught == [(dates[0], dates[3])] and ex[0].fwd3_after == 30.0
        assert ex[1].breakouts == [] and ex[1].leader_entries == [] and ex[1].caught == []
        assert bt.caught_leaders(by_date)[0][:2] == ("B", dates[0])

    def test_breakout_section_renders(self):
        by_date, dates = self._by_date()
        text = bt.render_breakouts(by_date, bt.breakout_examples(by_date, ["B"]), test_start=dates[4])
        assert "Recent breakouts" in text and "Became leader" in text and "| B |" in text and "Biggest winners" in text


class TestWeeklySetupsBacktest:
    def _by_date(self):
        dates = ["2026-01-02", "2026-01-16", "2026-01-30"]
        out = {}
        for d in dates:
            rows = [dict(symbol=f"M{j}", score=1.0, rs=0.5, status="laggard", has_setup=False, listed=False,
                         breakout=None, fwd1=1.0, fwd3=3.0) for j in range(10)]
            rows += [
                dict(symbol="SET", score=9.0, rs=0.95, status="leader", has_setup=True, listed=True, breakout=None, fwd1=11.0, fwd3=33.0),
                dict(symbol="NOSET", score=8.0, rs=0.96, status="leader", has_setup=False, listed=True, breakout=None, fwd1=5.0, fwd3=13.0),
                dict(symbol="BRK", score=7.0, rs=0.97, status="broken", has_setup=True, listed=False, breakout=None, fwd1=-9.0, fwd3=-9.0),
                dict(symbol="WEAK", score=1.0, rs=0.6, status="laggard", has_setup=True, listed=False, breakout=None, fwd1=-9.0, fwd3=-9.0),
            ]
            out[d] = rows
        return out, dates

    def test_pick_is_a_leader_with_a_setup_and_an_unbroken_trend(self):
        base = dict(has_setup=True, rs=0.9, status="leader")
        assert bt.is_setup_pick(base)
        assert not bt.is_setup_pick({**base, "has_setup": False})
        assert not bt.is_setup_pick({**base, "rs": 0.89})
        assert not bt.is_setup_pick({**base, "status": "broken"})
        assert not bt.is_setup_pick({**base, "rs": None})
        assert bt.is_setup_pick({**base, "rs": 0.8}, min_rs=0.8)

    def test_returns_are_versus_the_median_and_qqq(self):
        by_date, dates = self._by_date()
        bench = {d: (2.0, 4.0) for d in dates}
        s = bt.setup_stats(by_date, bench)
        assert s.names == 3 and s.per_date == 1.0
        assert s.fwd1_median == pytest.approx(10.0) and s.fwd3_median == pytest.approx(30.0)
        assert s.fwd1_qqq == pytest.approx(9.0) and s.fwd3_qqq == pytest.approx(29.0)
        assert s.beat_qqq_1m == 1.0 and s.beat_qqq_3m == 1.0

    def test_leaders_without_a_setup_are_the_comparison(self):
        by_date, dates = self._by_date()
        s = bt.setup_stats(by_date, {d: (2.0, 4.0) for d in dates}, lambda r: bt.is_leader_pick(r) and not r["has_setup"])
        assert s.names == 3 and s.fwd1_median == pytest.approx(4.0)

    def test_missing_benchmark_leaves_the_qqq_columns_empty(self):
        by_date, _ = self._by_date()
        s = bt.setup_stats(by_date, {})
        assert s.fwd1_qqq is None and s.fwd3_median is not None

    def test_benchmark_returns_cover_every_date(self):
        df = _history(1.0)
        d = df.index[100].strftime("%Y-%m-%d")
        assert bt.benchmark_returns(df, [d])[d][0] == bt.forward_return(df, df.index[100])

    def test_section_renders(self):
        by_date, dates = self._by_date()
        text = bt.render_setups(by_date, {d: (2.0, 4.0) for d in dates}, test_start=dates[1])
        assert "Weekly setups" in text and "Leaders, no setup" in text and "| Test |" in text and "| Train |" in text


class TestFailedBreakoutsBacktest:
    @staticmethod
    def _failed(sessions=3):
        return {"week": "2026-09-14", "failed_on": "2026-10-01", "sessions_below": sessions, "below_pct": -4.0}

    def _by_date(self):
        dates = ["2026-01-02", "2026-01-16", "2026-01-30"]
        out = {}
        for d in dates:
            rows = [dict(symbol=f"M{j}", score=1.0, rs=0.5, status="laggard", has_setup=False, listed=False,
                         breakout=None, failed=None, fwd1=1.0, fwd3=3.0) for j in range(10)]
            rows += [
                dict(symbol="FAIL", score=1.0, rs=0.7, status="warning", has_setup=False, listed=False, breakout=None,
                     failed=self._failed(3), fwd1=-9.0, fwd3=-19.0),
                dict(symbol="OLD", score=1.0, rs=0.6, status="broken", has_setup=False, listed=False, breakout=None,
                     failed=self._failed(30), fwd1=-5.0, fwd3=-7.0),
                dict(symbol="WEAK", score=1.0, rs=0.3, status="laggard", has_setup=False, listed=False, breakout=None,
                     failed=self._failed(3), fwd1=-30.0, fwd3=-30.0),
            ]
            out[d] = rows
        return out, dates

    def test_pick_needs_a_failed_breakout_and_rs_of_p50(self):
        base = dict(failed=self._failed(), rs=0.5)
        assert bt.is_failed_pick(base)
        assert not bt.is_failed_pick({**base, "rs": 0.49})
        assert not bt.is_failed_pick({**base, "rs": None})
        assert not bt.is_failed_pick({**base, "failed": None})
        assert bt.is_failed_pick({**base, "status": "broken"})  # any trend

    def test_fresh_failures_lost_the_level_within_ten_sessions(self):
        base = dict(rs=0.8)
        assert bt.is_fresh_failed_pick({**base, "failed": self._failed(10)})
        assert not bt.is_fresh_failed_pick({**base, "failed": self._failed(11)})
        assert not bt.is_fresh_failed_pick({**base, "failed": None})

    def test_a_failed_breakout_is_not_a_recent_breakout_pick(self):
        row = dict(breakout={"week": "w"}, rs=0.6, status="laggard")
        assert bt.is_breakout_pick(row)
        assert not bt.is_breakout_pick({**row, "failed": self._failed()})

    def test_returns_are_versus_the_median_and_qqq(self):
        by_date, dates = self._by_date()
        bench = {d: (2.0, 4.0) for d in dates}
        s = bt.setup_stats(by_date, bench, bt.is_failed_pick)
        assert s.names == 6 and s.per_date == 2.0
        assert s.fwd1_median == pytest.approx(((-9 - 1) + (-5 - 1)) / 2)
        assert s.fwd3_qqq == pytest.approx(((-19 - 4) + (-7 - 4)) / 2)
        assert s.beat_qqq_3m == 0.0
        fresh = bt.setup_stats(by_date, bench, bt.is_fresh_failed_pick)
        assert fresh.per_date == 1.0 and fresh.fwd1_median == pytest.approx(-10.0)

    def test_section_renders(self):
        by_date, dates = self._by_date()
        text = bt.render_failed(by_date, {d: (2.0, 4.0) for d in dates}, test_start=dates[1])
        assert "Failed breakouts" in text and "Fresh failures" in text and "Recent breakouts" in text
        assert "| Test |" in text and "| Train |" in text

    def test_slim_rows_keep_the_failed_breakout(self):
        df = _history(1.0)
        row = dict(symbol="X", score=1.0, rs=0.7, has_setup=False, failed_breakout=self._failed())
        slim = bt.slim_row(row, df, df.index[100], False)
        assert slim["failed"] == self._failed()


class TestReport:
    def _variants(self):
        return {"Old": bt.rank_all({"2026-01-02": _rows(), "2026-01-16": _rows()}),
                "New": bt.rank_all({"2026-01-02": _rows(), "2026-01-16": _rows()})}

    def test_report_has_train_test_tables_and_reference_ranks(self):
        v = self._variants()
        text = bt.render_report(v, None, reference=("W1", "S000"), test_start="2026-01-10")
        assert "**Train** (1 cut-off dates)" in text and "**Test** (1 cut-off dates)" in text
        assert "Top 1 forward 3M excess" in text and "Spearman" in text and "Capture in top 10" in text
        assert "| Old | New |" in text.replace("Metric | ", "") or "| Metric | Old | New |" in text
        assert "| 2026-01-16 |" in text and "**#1**" in text

    def test_reference_names_include_pltr_and_sndk_first(self):
        assert bt.REFERENCE[0] == "SNDK" and "PLTR" in bt.REFERENCE
        assert {"HPE", "DELL", "MU", "SNDK", "ARM", "NBIS", "AMD"} <= set(bt.REFERENCE)

    def test_dates_are_biweekly_and_split_before_the_test_period(self):
        members, hist = _market(24)
        dates = bt.rank_dates(hist, "2026-05-01")
        assert dates[0] == "2026-05-01" and dates[1] == "2026-05-15"
        assert bt.TEST_START > bt.RANK_START and bt.SNDK_RUN_START >= "2025-11-01"

    def test_collect_scans_every_date_with_only_data_up_to_it(self):
        members, hist = _market()
        dates = ["2026-06-12", "2026-06-26"]
        by_date = bt.collect(hist, members, None, dates)
        rows = {r["symbol"]: r for r in by_date["2026-06-12"]}
        assert rows["S39"]["listed"] and not rows["S00"]["listed"] and rows["S39"]["fwd3"] is not None
        late = {k: v.copy() for k, v in hist.items()}
        for df in late.values():  # a crash after the cut-off must not change that day's picks
            df.iloc[-40:, :4] *= 0.3
        again = {r["symbol"]: r for r in bt.collect(late, members, None, dates[:1])["2026-06-12"]}
        assert {k for k, r in again.items() if r["listed"]} == {k for k, r in rows.items() if r["listed"]}

    def test_the_old_list_is_names_with_a_weekly_setup(self):
        members, hist = _market()
        old = bt.collect(hist, members, None, ["2026-06-12"], method=bt.LEGACY)["2026-06-12"]
        assert all(r["listed"] == r["has_setup"] for r in old)


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
