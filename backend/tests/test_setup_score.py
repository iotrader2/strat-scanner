"""The setup score (tightness + short RS first), its entry parts on the alert, and the score-vs-R report."""

import json
import random
from datetime import timedelta

import pandas as pd
import pytest

from strat import alerts, alerts_live, alerts_store, score_report, setup_score as ss
from strat.alerts import Settings
from strat.candles import Candle, timeframe_state
from strat.leadership import Breakdown, trend_metrics
from strat.perf import MomentumRanks
from strat.scanner import scan_all
from strat.universe import Member

from tests.test_alerts_store import OPEN, FakeClient, _raw, _rising_history, db  # noqa: F401


def _frame(closes, spans=None, volumes=None, end="2026-10-15"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    span = pd.Series(spans if spans is not None else [2.0] * len(closes), index=idx, dtype=float)
    vol = pd.Series(volumes if volumes is not None else [1e6] * len(closes), index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close + span / 2, "low": close - span / 2, "close": close, "volume": vol})


GREEN = [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]
STATES = {tf: timeframe_state(tf, GREEN) for tf in ("M", "W", "D")}
RANKS = MomentumRanks.from_perf({"stock": {f"S{i}": {"1m": float(i), "3m": float(i), "6m": float(i)} for i in range(100)}})


class TestWeights:
    def test_groups_are_30_25_20_15_10(self):
        g = {
            "tightness": ss.STOP_ATR_POINTS + ss.ATR_CONTRACTION_POINTS + ss.CLOSE_TIGHTNESS_POINTS
            + ss.VOLUME_DRYUP_POINTS + ss.TRIGGER_VOLUME_POINTS + ss.EMA_DISTANCE_POINTS,
            "short_rs": ss.INTRADAY_RS_POINTS + ss.RS_10D_POINTS + ss.RS_20D_POINTS + ss.RS_LINE_POINTS,
            "setup": ss.TREND_POINTS + ss.CONTINUITY_POINTS + ss.LIQUIDITY_POINTS,
            "theme": ss.THEME_POINTS,
            "long_rs": ss.LONG_RS_POINTS,
        }
        assert g == {"tightness": 30, "short_rs": 25, "setup": 20, "theme": 15, "long_rs": 10}
        assert ss.STOCK_SCAN_MAX == 80 and ss.STOCK_ENTRY_MAX == 100
        assert ss.ETF_SCAN_MAX == 65 and ss.ETF_ENTRY_MAX == 85

    def test_breakdown_lines_add_up_and_carry_their_weights(self):
        s = ss.score_symbol(STATES, 105.0, 1e9, momentum=RANKS.momentum("stock", {"1m": 95.0, "3m": 95.0, "6m": 95.0}))
        assert s.max_raw == 80
        assert sum(c.weight_pct for c in s.breakdown) == pytest.approx(100, abs=0.3)
        assert {c.key for c in s.breakdown} == {
            "atr_contraction", "close_tightness", "volume_dryup", "ema_distance", "rs_10d", "rs_20d", "rs_line",
            "trend", "continuity", "liquidity", "theme_strength", "rs",
        }
        assert sum(c.points for c in s.breakdown) == pytest.approx(s.raw, abs=0.05)


class TestBase:
    def test_a_contracting_quiet_base_beats_a_loose_one(self):
        n = 80
        tight = _frame([100 + 0.05 * (i % 2) for i in range(n)], spans=[4.0] * (n - 5) + [1.5] * 5,
                       volumes=[1e6] * (n - 5) + [4e5] * 5)
        loose = _frame([100 + 3 * (i % 2) for i in range(n)], spans=[2.0] * (n - 5) + [5.0] * 5,
                       volumes=[1e6] * (n - 5) + [2e6] * 5)
        bt, bl = ss.base_metrics(tight), ss.base_metrics(loose)
        assert bt.atr_ratio < 0.6 < 1.0 < bl.atr_ratio
        assert bt.volume_dryup == pytest.approx(0.4) and bl.volume_dryup == pytest.approx(2.0)
        assert bt.close_std_pct < 0.1 < bl.close_std_pct
        pts = lambda b: sum(c.points for c in ss.tightness_components(b))  # noqa: E731
        assert pts(bt) > 17 and pts(bt) > pts(bl) + 10

    def test_inside_day_and_nr7(self):
        n = 70
        df = _frame([100.0] * n, spans=[3.0] * (n - 1) + [1.0])
        b = ss.base_metrics(df)
        assert b.inside_day and b.nr7
        c = next(c for c in ss.tightness_components(b) if c.key == "close_tightness")
        assert "inside day + NR7" in c.label and c.points == pytest.approx(ss.CLOSE_TIGHTNESS_POINTS)

    def test_distance_from_the_nearer_ema_in_atrs(self):
        n = 70
        flat = ss.base_metrics(_frame([100.0] * n))
        assert flat.ema_dist_atr == pytest.approx(0.0, abs=1e-9)
        extended = ss.base_metrics(_frame([100.0] * (n - 1) + [110.0]))
        assert extended.ema_dist_atr > 2 and extended.ema10_dist_atr > 0

    def test_too_little_history_scores_nothing(self):
        assert ss.base_metrics(_frame([100.0] * 30)) is None
        assert all(c.points == 0 for c in ss.tightness_components(None))


class TestShortRS:
    def test_excess_and_the_rs_line_leading_price(self):
        n = 40
        bench = _frame([100 - 1.0 * i for i in range(n)]).close  # QQQ falling
        # Stock back under a high from two weeks ago, so price is not at a 20-day high but stock / QQQ is.
        stock = _frame([100.0] * 25 + [110.0] * 5 + [100.0] * (n - 30))
        r = ss.short_rs(stock, bench)
        ret = lambda c: (c.iloc[-1] / c.iloc[-11] - 1) * 100  # noqa: E731
        assert r.excess_10d == pytest.approx(ret(stock.close) - ret(bench))
        assert r.rs_line_high and not r.price_high
        line = next(c for c in ss.short_rs_components(r) if c.key == "rs_line")
        assert line.points == ss.RS_LINE_POINTS and "before price" in line.detail

    def test_percentiles_within_the_group_replace_fixed_thresholds(self):
        group = {f"S{i}": ss.ShortRS(float(i), float(i)) for i in range(10)}
        ranked = ss.rank_short_rs({"stock": group})["stock"]
        assert ranked["S9"].pct_10d == pytest.approx(0.95) and ranked["S0"].pct_20d == pytest.approx(0.05)
        top = {c.key: c.points for c in ss.short_rs_components(ranked["S9"], 10)}
        assert top["rs_10d"] == pytest.approx(4.75) and top["rs_20d"] == pytest.approx(4.75)

    def test_no_benchmark_leaves_it_empty(self):
        r = ss.short_rs(_frame([100.0] * 40), None)
        assert r == ss.ShortRS(None, None)


class TestEntry:
    ROW = {
        "kind": "stock", "score": 50.0, "score_raw": 40.0, "score_keep": 1.0, "as_of": "2026-10-15",
        "score_breakdown": [{"key": "theme_strength", "label": "Theme", "points": 15.0, "max_points": 15.0, "detail": ""},
                            {"key": "rs_10d", "label": "10-day RS", "points": 5.0, "max_points": 5.0, "detail": ""}],
        "score_inputs": {"base": {"atr14_pct": 4.0}},
    }

    def test_entry_parts_reward_a_tight_stop_and_intraday_strength(self):
        best = ss.EntryInputs(stop_pct=0.4, atr14_pct=4.0, stock_change_pct=3.0, qqq_change_pct=0.5,
                              day_volume=3e6, avg_volume=4e6, bars_elapsed=13)
        worst = ss.EntryInputs(stop_pct=1.6, atr14_pct=4.0, stock_change_pct=-1.0, qqq_change_pct=0.5,
                               day_volume=1e6, avg_volume=4e6, bars_elapsed=13)
        assert best.stop_x_atr == pytest.approx(0.1) and best.intraday_excess == pytest.approx(2.5)
        assert best.relative_volume == pytest.approx(1.5)
        assert sum(c.points for c in ss.entry_components(best)) == pytest.approx(ss.ENTRY_MAX_POINTS)
        assert sum(c.points for c in ss.entry_components(worst)) == 0

    def test_entry_score_is_out_of_100_and_keeps_the_raw_inputs(self):
        e = ss.EntryInputs(stop_pct=0.4, atr14_pct=4.0, stock_change_pct=3.0, qqq_change_pct=0.5,
                           day_volume=3e6, avg_volume=4e6, bars_elapsed=13)
        sc = ss.entry_score(self.ROW, e)
        assert sc["max_raw"] == 100 and sc["raw"] == pytest.approx(60.0) and sc["score"] == 60.0
        assert sc["components"]["stop_atr"] == 8 and sc["components"]["theme_strength"] == 15
        assert sc["groups"]["short_rs"] == {"points": 15.0, "max": 15.0}
        assert sc["inputs"]["entry"]["intraday_excess"] == pytest.approx(2.5)
        assert sc["inputs"]["base"]["atr14_pct"] == 4.0
        assert any(p.get("entry") for p in sc["breakdown"])
        json.dumps(sc)  # stored as JSON on the alert

    def test_the_scan_penalties_scale_the_entry_parts_too(self):
        e = ss.EntryInputs(stop_pct=0.4, atr14_pct=4.0, stock_change_pct=3.0, qqq_change_pct=0.5,
                           day_volume=3e6, avg_volume=4e6, bars_elapsed=13)
        sc = ss.entry_score({**self.ROW, "score_keep": 0.5}, e)
        assert sc["raw"] == pytest.approx(40 + 10)

    def test_off_scan_names_get_the_entry_parts_alone(self):
        sc = ss.entry_score(None, ss.EntryInputs(stop_pct=0.4, atr14_pct=4.0))
        assert sc["max_raw"] == ss.ENTRY_MAX_POINTS and sc["components"]["stop_atr"] == 8


def _universe(n=20):
    members = [Member(f"S{i:02d}", f"S{i:02d}", "Information Technology", "stock", "SP500") for i in range(n)]
    members.append(Member("QQQ", "QQQ", "Other", "etf", "benchmark"))
    hist = {}
    for i in range(n):
        idx = pd.bdate_range(end="2026-10-15", periods=320)
        close = pd.Series([100 + k * (-0.1 + i * 0.05) for k in range(320)], index=idx, dtype=float)
        hist[f"S{i:02d}"] = pd.DataFrame({"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 3e6})
    idx = pd.bdate_range(end="2026-10-15", periods=320)
    q = pd.Series([100 + k * 0.12 for k in range(320)], index=idx, dtype=float)
    hist["QQQ"] = pd.DataFrame({"open": q, "high": q + 2, "low": q - 2, "close": q, "volume": 3e6})
    return members, hist


class TestScan:
    def test_rows_carry_the_setup_score_its_inputs_and_the_leadership_score(self):
        members, hist = _universe()
        result = scan_all(members, hist)
        rows = {r["symbol"]: r for r in result.rows}
        top, bottom = rows["S19"], rows["S00"]
        assert top["score_max_raw"] == 80 and "leadership_score" in top and "score_keep" in top
        assert top["score_inputs"]["short_rs"]["pct_20d"] > 0.9 > bottom["score_inputs"]["short_rs"]["pct_20d"]
        by = {c["key"]: c for c in top["score_breakdown"]}
        assert by["rs_20d"]["group"] == "short_rs" and by["atr_contraction"]["group"] == "tightness"
        assert top["score"] > bottom["score"]
        assert result.short_rs["stock"]["S19"].pct_10d is not None
        json.dumps(top["score_inputs"])

    def test_a_single_rescan_ranks_against_the_last_full_scan(self):
        from strat.scanner import short_rs_for

        members, hist = _universe()
        result = scan_all(members, hist)
        srs, peers = short_rs_for(members[19], hist["S19"], hist["QQQ"], result.short_rs)
        assert peers == 20 and srs.pct_20d == result.short_rs["stock"]["S19"].pct_20d


class TestAlert:
    def test_entry_inputs_from_the_bars(self):
        a = type("A", (), {"origin_bar": OPEN + timedelta(minutes=15), "stop_pct": 0.5, "trigger": 101.0})()
        bars = [{"t": OPEN, "o": 100.0, "c": 101.0, "v": 1000.0}, {"t": OPEN + timedelta(minutes=15), "o": 101.0, "c": 102.0, "v": 500.0}]
        qqq = [{"t": OPEN, "o": 400.0, "c": 401.0, "v": 1.0}, {"t": OPEN + timedelta(minutes=15), "o": 401.0, "c": 402.0, "v": 1.0}]
        e = alerts_live.entry_inputs(a, bars, qqq, {"atr_pct": 5.0, "avg_volume": 10_000.0})
        assert e.stock_change_pct == pytest.approx(2.0) and e.qqq_change_pct == pytest.approx(0.5)
        assert e.day_volume == 1500 and e.bars_elapsed == 2 and e.stop_x_atr == pytest.approx(0.1)

    def test_refresh_attaches_a_frozen_score(self, db):  # noqa: F811
        alerts_live.clear()
        history = _rising_history()
        ctx = alerts.context_from_closes(alerts_live.regular_closes(history, OPEN.date()))
        ma, last = ctx.ma_tail[120][-1], ctx.prev_close
        touch = _raw(OPEN, last, last + 0.3, round(ma, 2), last - 0.1, 1000)
        qqq = [_raw(OPEN, 400, 401, 399, 400.4, 1e6)]
        client = FakeClient({"AAA": history, "QQQ": []}, {"AAA": [touch], "QQQ": qqq})
        row = {"kind": "stock", "score": 70.0, "score_raw": 56.0, "score_keep": 1.0, "atr_pct": 4.0,
               "avg_volume": 1e6, "score_breakdown": [], "score_inputs": {}}
        settings = Settings(entry_trigger=0, max_stop_pct=5)
        alerts_live.refresh(["AAA"], now=OPEN + timedelta(minutes=16), client=client, settings=settings,
                            scan_rows={"AAA": row})
        stored = alerts_store.list_alerts()[0]["details"]["score"]
        assert stored["inputs"]["entry"]["qqq_change_pct"] == pytest.approx(0.1)
        assert stored["inputs"]["entry"]["stock_change_pct"] is not None
        # A later poll, with a very different scan row, does not change the score the alert fired with.
        client.iex["AAA"].append(_raw(OPEN + timedelta(minutes=15), last, last + 0.5, last - 0.05, last + 0.4, 500))
        alerts_live.refresh(["AAA"], now=OPEN + timedelta(minutes=31), client=client, settings=settings,
                            scan_rows={"AAA": {**row, "atr_pct": 1.0, "score": 10.0}})
        assert alerts_store.list_alerts()[0]["details"]["score"] == stored
        alerts_live.clear()

    def test_keep_frozen_details(self):
        old = json.dumps({"score": {"score": 60}, "x": 1})
        new = json.dumps({"score": {"score": 10}, "x": 2})
        assert json.loads(alerts_store.keep_frozen_details(old, new)) == {"score": {"score": 60}, "x": 2}
        assert alerts_store.keep_frozen_details(json.dumps({"x": 1}), new) == new


def _trades(n, seed=1):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        tight = rng.random()
        noise = rng.random()
        R = -1 + 4.5 * tight * noise + (rng.random() - 0.5)
        rows.append({
            "id": i, "symbol": "X", "session": "2026-11-01", "filled": True, "r_multiple": R,
            "details": {"score": {
                "version": 1, "score": 40 + 50 * tight, "scan_score": 50,
                "groups": {"tightness": {"points": 30 * tight, "max": 30}},
                "components": {"stop_atr": 8 * tight, "rs_10d": 5 * rng.random()},
                "inputs": {"entry": {"stop_x_atr": 0.35 - 0.25 * tight}, "short_rs": {"rs_line_high": rng.random() > 0.5}},
            }},
        })
    rows.append({"id": -1, "filled": False, "r_multiple": None, "details": {}})  # unfilled: ignored
    return rows


class TestReport:
    def test_quintiles_and_spearman_find_the_predictive_part(self):
        rep = score_report.report(_trades(250))
        assert rep["trades"] == 250 and rep["enough"]
        q = rep["quintiles"]
        assert [x["quintile"] for x in q] == [1, 2, 3, 4, 5] and sum(x["n"] for x in q) == 250
        assert q[-1]["hit_tail"] > q[0]["hit_tail"] and q[-1]["avg_r"] > q[0]["avg_r"]
        f = {x["feature"]: x for x in rep["features"]}
        assert f["pts:stop_atr"]["spearman_r"] > 0.3 and f["raw:stop % / ATR %"]["spearman_r"] < -0.3
        assert abs(f["pts:rs_10d"]["spearman_r"]) < 0.2
        assert f["pts:stop_atr"]["tail_lift"] > 1.3
        md = score_report.markdown(rep)
        assert "Score quintiles" in md and "Too few" not in md

    def test_a_small_sample_says_so(self):
        rep = score_report.report(_trades(30))
        assert not rep["enough"] and "Too few trades" in score_report.markdown(rep)
        assert score_report.report([])["overall"] is None

    def test_the_api_route(self, db):  # noqa: F811
        from fastapi.testclient import TestClient

        from strat.api import app

        body = TestClient(app).get("/api/alerts/score-report").json()
        assert body["trades"] == 0 and body["min_trades"] == 200
