"""data/setups.yaml is the source of every setup number: the code reads it, and a change there changes detection."""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from strat import ariel_setups as a

YAML = Path(a.SETUPS_YAML)


def test_every_documented_number_is_what_the_code_uses():
    c = yaml.safe_load(YAML.read_text())
    ep, hvc, fb = c["episodic_pivot"]["params"], c["delayed_hvc"]["params"], c["flat_base"]["params"]
    ur, ma, htf = c["undercut_rally"]["params"], c["ma_undercut_rally"]["params"], c["high_tight_flag"]["params"]
    assert a.ENTRY_TF == f"{c['general']['entry_chart_minutes']}m"
    assert a.MIN_HISTORY_DAYS == c["general"]["min_history_days"]
    assert (a.EP_MIN_GAP_PCT, a.EP_MIN_VOLUME_X, a.EP_VOLUME_AVG_DAYS, a.EP_MIN_SESSION_FRACTION) == (
        ep["min_gap_pct"] / 100, ep["min_volume_x"], ep["volume_avg_days"], ep["min_session_pct"] / 100)
    assert (a.HVC_LOOKBACK_DAYS, a.HVC_GAP_MIN_PCT, a.HVC_GAP_MIN_VOLUME_X, a.HVC_GAP_CLOSE_POSITION) == (
        hvc["lookback_days"], hvc["gap_day_min_gap_pct"] / 100, hvc["gap_day_min_volume_x"],
        hvc["gap_day_close_position_pct"] / 100)
    assert a.HVC_MAX_BELOW_PCT == hvc["max_below_pct"] / 100
    assert (a.FLAT_BASE_MIN_BARS, a.FLAT_BASE_MAX_DEPTH_PCT, a.FLAT_BASE_PRIOR_TREND_BARS, a.FLAT_BASE_PRIOR_RUN_PCT,
            a.FLAT_BASE_MA_SPREAD_PCT, a.FLAT_BASE_RESISTANCE_PCT, a.FLAT_BASE_TIGHT_RANGE_PCT) == (
        fb["base_days"], fb["max_depth_pct"] / 100, fb["prior_trend_days"], fb["prior_rise_pct"] / 100,
        fb["ma_spread_pct"] / 100, fb["resistance_pct"] / 100, fb["tight_candle_pct"] / 100)
    assert a.UR_LOOKBACK_BARS == ur["swing_lookback_days"]
    assert (list(a.MA_UR_PERIODS), a.MA_UR_MIN_HISTORY, a.MA_UR_PENDING_MAX_BELOW) == (
        ma["ma_periods"], ma["min_history_days"], ma["pending_max_below_pct"] / 100)
    assert (a.HTF_MIN_RUNUP_PCT, a.HTF_RUN_MAX_BARS, a.HTF_FLAG_MIN_BARS, a.HTF_FLAG_MAX_BARS,
            a.HTF_FLAG_MAX_DEPTH_PCT, a.HTF_MAX_GIVEBACK) == (
        htf["min_runup_pct"] / 100, htf["run_max_days"], htf["flag_min_days"], htf["flag_max_days"],
        htf["max_flag_depth_pct"] / 100, htf["max_giveback_pct"] / 100)
    xb, wp = c["ema_crossback"]["params"], c["wedge_pop"]["params"]
    assert (a.XB_RISING_DAYS, a.XB_PUSH_LOOKBACK, a.XB_MIN_PUSH, a.XB_TOUCH, a.XB_HOLD, a.XB_MAX_PULLBACK) == (
        xb["rising_days"], xb["push_lookback_days"], xb["min_push_pct"] / 100, xb["touch_pct"] / 100,
        xb["hold_pct"] / 100, xb["max_pullback_pct"] / 100)
    assert (a.WP_DECLINE_LOOKBACK, a.WP_MIN_DECLINE, a.WP_WEDGE_DAYS, a.WP_MAX_RANGE, a.WP_EMA_NEAR) == (
        wp["decline_lookback_days"], wp["min_decline_pct"] / 100, wp["wedge_days"], wp["max_wedge_range_pct"] / 100,
        wp["ema_near_pct"] / 100)


def test_every_parameter_is_explained_in_its_rules():
    """A number nobody can find in the plain-words text is a number nobody can adjust."""
    c = yaml.safe_load(YAML.read_text())
    for section, body in c.items():
        if not isinstance(body, dict) or "params" not in body:
            continue
        text = " ".join(str(body.get(k, "")) for k in ("rules", "entry", "stop"))
        for key in body["params"]:
            if key == "min_history_days":
                continue
            assert re.search(rf"\b{key}\b", text), f"{section}.{key} is not mentioned in its rules"


def test_names_come_from_the_file():
    c = yaml.safe_load(YAML.read_text())
    assert a.SETUP_LABELS["flat-base-breakout"] == c["flat_base"]["name"]
    assert dict(a.SHORT_MIRROR.values())["low-tight-flag"] == c["high_tight_flag"]["short_name"]
    assert {d["kind"] for d in a.describe()} == set(a.SETUP_LABELS)


def test_changing_a_number_in_the_file_changes_detection(tmp_path):
    """Same 3% gap: found with min_gap_pct 2, not found once the file says 5."""
    raw = YAML.read_text()
    stricter = raw.replace("    min_gap_pct: 2\n", "    min_gap_pct: 5\n", 1)
    assert stricter != raw
    alt = tmp_path / "setups.yaml"
    alt.write_text(stricter)
    script = (
        "import pandas as pd; from strat.ariel_setups import find_ariel_setups;"
        "idx = pd.bdate_range('2026-01-05', periods=22);"
        "df = pd.DataFrame({'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0, 'volume': 1e6}, index=idx);"
        "t = {'open': 103.0, 'high': 106.0, 'low': 102.0, 'close': 105.0, 'volume': 0.0};"
        "print(any(s.kind == 'episodic-pivot' for s in find_ariel_setups(df, today=t, opening_high=104.0)))"
    )
    cwd = Path(__file__).resolve().parent.parent

    def run(path):
        env = {**os.environ, "STRAT_SETUPS_YAML": str(path)}
        return subprocess.run([sys.executable, "-c", script], cwd=cwd, env=env, capture_output=True, text=True).stdout.strip()

    assert run(YAML) == "True"
    assert run(alt) == "False"
