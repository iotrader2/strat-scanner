import numpy as np
import pandas as pd
import pytest

from strat import themes_report as tr
from strat.themes import parse_themes


def _themes():
    return parse_themes(
        {
            "version": 1,
            "themes": {
                "chips": {"name": "Chips", "members": "C1 C2 C3 C4 ODD", "keep": "ODD"},
                "banks": {"name": "Banks", "members": "B1 B2 B3 B4"},
            },
        }
    )


def _daily(seed=7, n=140):
    """Two factors (chips, banks) on top of a market: C* follow chips, B* follow banks, ODD follows neither, X follows chips."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2026-03-02", periods=n)
    market = rng.normal(0, 0.008, n)
    chips = rng.normal(0, 0.015, n)
    banks = rng.normal(0, 0.015, n)

    def series(factor, beta=1.0, noise=0.004):
        r = beta * market + (factor if factor is not None else 0) + rng.normal(0, noise, n)
        return pd.Series(100 * np.cumprod(1 + r), index=idx)

    closes = {"SPY": pd.Series(100 * np.cumprod(1 + market), index=idx)}
    for s in ("C1", "C2", "C3", "C4", "X"):
        closes[s] = series(chips)
    for s in ("B1", "B2", "B3", "B4"):
        closes[s] = series(banks)
    closes["ODD"] = series(rng.normal(0, 0.02, n))
    return {s: pd.DataFrame({"close": c}) for s, c in closes.items()}


@pytest.fixture(scope="module")
def report():
    themes = _themes()
    daily = _daily()
    stocks = set(daily) - {"SPY"}
    return tr.build_report(themes, daily, stocks), themes


def test_window_is_about_six_months_of_sessions():
    assert tr.WINDOW == 126
    rets = tr.returns_frame(_daily())
    assert len(rets) == 126


def test_returns_frame_drops_symbols_with_too_little_history():
    daily = _daily()
    daily["NEW"] = daily["C1"].iloc[-20:]
    assert "NEW" not in tr.returns_frame(daily).columns


def test_residuals_remove_the_market_component():
    daily = _daily()
    rets = tr.returns_frame(daily)
    resid = tr.residual_returns(rets, rets["SPY"])
    raw_corr = rets["C1"].corr(rets["SPY"])
    assert abs(resid["C1"].corr(rets["SPY"])) < 0.05 < raw_corr


def test_cohesive_members_are_not_flagged_and_the_odd_one_is(report):
    rep, _ = report
    by = {c.symbol: c for c in rep.checks}
    assert not by["C1"].flagged and not by["B1"].flagged
    assert by["C1"].own > 0.5 and by["B1"].own > 0.5
    assert by["ODD"].flagged and by["ODD"].kept and not by["ODD"].to_review
    assert "low in-theme correlation" in by["ODD"].reasons[0]


def test_a_member_that_fits_another_theme_better_is_flagged_but_never_moved():
    themes = parse_themes(
        {
            "version": 1,
            "themes": {
                "chips": {"name": "Chips", "members": "C1 C2 C3 C4 B4"},
                "banks": {"name": "Banks", "members": "B1 B2 B3 C4X", "also": "C4"},
            },
        }
    )
    daily = _daily()
    daily["C4X"] = daily["B1"]
    rets = tr.returns_frame(daily)
    resid = tr.residual_returns(rets, rets["SPY"])
    stocks = set(daily) - {"SPY"}
    cols = [s for s in rets.columns if s in stocks]
    aff = tr.theme_affinity(resid[cols].corr(), themes)
    checks = {c.symbol: c for c in tr.check_members(themes, aff, aff)}
    assert checks["B4"].best_theme == "banks" and checks["B4"].to_review
    assert any("fits banks better" in r for r in checks["B4"].reasons)
    assert themes.primary["B4"] == "chips"  # the report never reassigns


def test_unassigned_stock_is_suggested_for_its_best_theme(report):
    rep, _ = report
    assert rep.candidates[0][:2] == ("X", "chips") and rep.candidates[0][2] > 0.5
    assert all(s != "SPY" for s, _, _ in rep.candidates)


def test_cohesion_table_summarizes_each_theme(report):
    rep, _ = report
    chips = rep.cohesion.loc["chips"]
    assert chips["members"] == 5 and chips["with_data"] == 5 and chips["flagged"] == 1 and chips["to_review"] == 0
    assert rep.cohesion.loc["banks"]["resid"] > chips["resid"]


def test_clustering_recovers_the_factor_groups(report):
    rep, _ = report
    biggest = [set(c["members"]) for c in rep.clusters]
    assert {"C1", "C2", "C3", "C4", "X"} <= max(biggest, key=lambda m: len(m & {"C1", "C2", "C3", "C4", "X"}))
    assert {"B1", "B2", "B3", "B4"} in [m & {"B1", "B2", "B3", "B4"} for m in biggest]


def test_average_linkage_stops_below_the_threshold():
    corr = pd.DataFrame(
        [[1, 0.9, 0.1, 0.0], [0.9, 1, 0.0, 0.1], [0.1, 0.0, 1, 0.8], [0.0, 0.1, 0.8, 1]],
        index=list("ABCD"), columns=list("ABCD"),
    )
    assert [sorted(c) for c in tr.average_linkage(corr, 0.5)] == [["A", "B"], ["C", "D"]]
    assert len(tr.average_linkage(corr, 0.0)) == 1


def test_render_is_a_markdown_report_that_lists_flags_and_clusters(report):
    rep, themes = report
    text = tr.render(rep, themes)
    assert text.startswith("# Theme validation report")
    assert "ODD" in text and "Chips" in text and "Banks" in text
    assert "kept" in text.lower()


def test_main_writes_the_report(tmp_path, monkeypatch, capsys):
    from strat.universe import Member

    daily = _daily()
    monkeypatch.setattr(tr.data, "load_all_daily", lambda: daily)
    monkeypatch.setattr(tr, "load_themes", _themes)
    monkeypatch.setattr(tr, "load_universe", lambda: [Member(s, s, "Other", "stock", "SP500") for s in daily if s != "SPY"])
    out = tmp_path / "r.md"
    assert tr.main(["--out", str(out)]) == 0
    assert out.read_text().startswith("# Theme validation report")
    assert "Chips" in capsys.readouterr().out
    out.unlink()
    assert tr.main(["--out", str(out), "--no-write"]) == 0 and not out.exists()
