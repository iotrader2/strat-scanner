"""Completed weeks and months only: the open period must not set a trigger."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from strat.candles import timeframe_state
from strat.data import resample
from strat.periods import completed_week_high_labels, final_session, is_trading_day, period_complete
from strat.scanner import chart_payload, scan_symbol, to_candles
from strat.universe import Member

ET = ZoneInfo("America/New_York")


def _at(day: str, hour: int) -> datetime:
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hour, tzinfo=ET)


def _frame(rows: list[tuple]) -> pd.DataFrame:
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": 1_000_000.0,
        },
        index=idx,
    )


def _fill(start: str, end: str, ohlc: tuple[float, float, float, float]) -> list[tuple]:
    o, h, low, c = ohlc
    return [(ts.strftime("%Y-%m-%d"), o, h, low, c) for ts in pd.bdate_range(start, end)]


def _ctva_like(*, monday: bool) -> pd.DataFrame:
    """July-September history, an inside week ending Fri Oct 16 (high 18), and an optional Monday.

    Monday Oct 19 is an inside day of that week with high 13.01 — the level a partial
    week leaks into the trigger. The completed week's own high is 18.
    """
    rows = _fill("2026-07-01", "2026-07-31", (30, 38, 28, 34))
    rows += _fill("2026-08-03", "2026-08-31", (40, 45, 35, 42))
    rows += _fill("2026-09-01", "2026-09-30", (44, 48, 40, 47))
    rows += _fill("2026-10-01", "2026-10-02", (44, 48, 40, 47))
    rows += _fill("2026-10-05", "2026-10-09", (15, 20, 10, 19))  # 2D vs September's range
    rows += _fill("2026-10-12", "2026-10-16", (17, 18, 12, 14))  # inside, red, trigger 18
    if monday:
        rows.append(("2026-10-19", 12.40, 13.01, 12.50, 12.80))  # inside the open week, green
    return _frame(rows)


class TestCalendar:
    @pytest.mark.parametrize(
        "day",
        ["2024-03-29", "2025-04-18", "2026-04-03", "2027-03-26", "2026-07-03", "2026-12-25", "2026-01-01"],
    )
    def test_full_day_closes_are_not_trading_days(self, day):
        assert not is_trading_day(date.fromisoformat(day))

    def test_a_normal_friday_and_the_thursday_before_good_friday_are_sessions(self):
        assert is_trading_day(date(2026, 10, 16))
        assert is_trading_day(date(2026, 4, 2))
        assert final_session("W", date(2026, 10, 19)) == date(2026, 10, 23)
        assert final_session("W", date(2026, 4, 2)) == date(2026, 4, 2)
        assert final_session("M", date(2026, 10, 19)) == date(2026, 10, 30)
        assert final_session("M", date(2026, 1, 15)) == date(2026, 1, 30)

    def test_completion_follows_the_close_not_the_calendar_week_alone(self):
        monday = date(2026, 10, 19)
        friday = date(2026, 10, 16)
        assert not period_complete("W", monday, _at("2026-10-19", 17))
        assert not period_complete("W", friday, _at("2026-10-16", 11))
        assert period_complete("W", friday, _at("2026-10-16", 16))
        assert period_complete("W", friday, _at("2026-10-17", 12))
        assert period_complete("W", friday, _at("2026-10-18", 12))
        # Monday before the open, the prior Friday is still the completed week.
        assert period_complete("W", friday, _at("2026-10-19", 8))
        # Good Friday 2026-04-03: Thursday's close finishes the week.
        assert not period_complete("W", date(2026, 4, 2), _at("2026-04-02", 11))
        assert period_complete("W", date(2026, 4, 2), _at("2026-04-02", 17))
        assert period_complete("W", date(2026, 4, 2), _at("2026-04-04", 12))
        # Mid-month October is open; the last Friday of a month that ends on Saturday is the close.
        assert not period_complete("M", date(2026, 10, 19), _at("2026-10-19", 17))
        assert not period_complete("M", date(2026, 1, 30), _at("2026-01-30", 11))
        assert period_complete("M", date(2026, 1, 30), _at("2026-01-30", 17))
        assert period_complete("M", date(2026, 1, 30), _at("2026-01-31", 12))


class TestLabels:
    def test_labels_name_the_completed_week(self):
        assert completed_week_high_labels(date(2026, 10, 19), _at("2026-10-19", 17)) == (
            "last week's high",
            "prior week's high",
        )
        assert completed_week_high_labels(date(2026, 10, 16), _at("2026-10-16", 11))[0] == "last week's high"
        assert completed_week_high_labels(date(2026, 10, 16), _at("2026-10-16", 17)) == (
            "this week's high",
            "last week's high",
        )
        assert completed_week_high_labels(date(2026, 10, 16), _at("2026-10-17", 12))[0] == "this week's high"
        assert completed_week_high_labels(date(2026, 10, 18), _at("2026-10-18", 12))[0] == "this week's high"
        # Monday morning, Friday's bar is in and the new week has not printed yet.
        assert completed_week_high_labels(date(2026, 10, 16), _at("2026-10-19", 8))[0] == "last week's high"
        assert completed_week_high_labels(date(2026, 4, 2), _at("2026-04-04", 12))[0] == "this week's high"
        assert completed_week_high_labels(date(2026, 4, 2), _at("2026-04-06", 17))[0] == "last week's high"


class TestResample:
    def test_monday_is_its_own_bin_and_is_dropped_until_the_week_closes(self):
        df = _ctva_like(monday=True)
        forming = resample(df, "W", completed_only=False)
        assert float(forming.iloc[-2].high) == 18
        assert float(forming.iloc[-1].high) == 13.01
        assert pd.Timestamp(forming.index[-1]) == pd.Timestamp("2026-10-19")

        done = resample(df, "W", now=_at("2026-10-19", 17))
        assert pd.Timestamp(done.index[-1]) == pd.Timestamp("2026-10-12")
        assert float(done.iloc[-1].high) == 18
        assert 13.01 not in set(done.high.round(2))

    def test_friday_before_the_close_drops_the_week_and_after_the_close_keeps_it(self):
        df = _ctva_like(monday=False)
        early = resample(df, "W", now=_at("2026-10-16", 11))
        assert float(early.iloc[-1].high) == 20  # week of Oct 5, the prior completed week
        late = resample(df, "W", now=_at("2026-10-16", 16))
        assert pd.Timestamp(late.index[-1]) == pd.Timestamp("2026-10-12")
        assert float(late.iloc[-1].high) == 18
        weekend = resample(df, "W", now=_at("2026-10-18", 12))
        assert float(weekend.iloc[-1].high) == 18

    def test_good_friday_week_is_complete_on_thursday_evening(self):
        rows = _fill("2026-03-16", "2026-03-20", (20, 30, 18, 25))
        rows += _fill("2026-03-23", "2026-03-27", (24, 28, 22, 26))
        rows += _fill("2026-03-30", "2026-04-02", (25, 27, 23, 26))  # no Friday bar; Friday is Good Friday
        df = _frame(rows)
        assert float(resample(df, "W", now=_at("2026-04-02", 11)).iloc[-1].high) == 28
        kept = resample(df, "W", now=_at("2026-04-02", 17))
        assert float(kept.iloc[-1].high) == 27
        assert float(resample(df, "W", now=_at("2026-04-04", 12)).iloc[-1].high) == 27
        df = _frame(rows + [("2026-04-06", 26, 13.01, 25, 26.5)])
        after = resample(df, "W", now=_at("2026-04-06", 17))
        assert float(after.iloc[-1].high) == 27
        assert 13.01 not in set(after.high.round(2))

    def test_open_month_quarter_and_half_are_dropped(self):
        idx = pd.bdate_range("2025-01-02", "2026-10-19")
        df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
        now = _at("2026-10-19", 17)
        assert pd.Timestamp(resample(df, "M", now=now).index[-1]) == pd.Timestamp("2026-09-01")
        assert pd.Timestamp(resample(df, "3M", now=now).index[-1]) == pd.Timestamp("2026-07-01")
        assert pd.Timestamp(resample(df, "6M", now=now).index[-1]) == pd.Timestamp("2026-01-01")

    def test_a_month_that_ends_on_saturday_completes_friday_after_the_close(self):
        early = _frame(_fill("2025-12-01", "2026-01-30", (10, 11, 9, 10)))
        assert pd.Timestamp(resample(early, "M", now=_at("2026-01-30", 11)).index[-1]) == pd.Timestamp("2025-12-01")
        assert pd.Timestamp(resample(early, "M", now=_at("2026-01-30", 17)).index[-1]) == pd.Timestamp("2026-01-01")
        assert pd.Timestamp(resample(early, "M", now=_at("2026-01-31", 12)).index[-1]) == pd.Timestamp("2026-01-01")
        missing_friday = _frame(_fill("2025-12-01", "2026-01-29", (10, 11, 9, 10)))
        assert pd.Timestamp(resample(missing_friday, "M", now=_at("2026-01-30", 17)).index[-1]) == pd.Timestamp("2025-12-01")


class TestCtvaTrigger:
    def test_weekly_trigger_setup_continuity_and_chips_ignore_mondays_high(self):
        df = _ctva_like(monday=True)
        row = scan_symbol(Member("CTVA", "Corteva", "Materials", "stock", "SP500"), df)
        assert row["trigger"] == 18
        assert row["trigger"] != 13.01
        assert "2-1-2" in row["setup"]
        assert row["triggered"] is False
        assert row["trigger_distance_pct"] == pytest.approx((18 - 12.80) / 12.80 * 100, abs=0.01)
        assert "13.01" not in row["reason"] and "18.00" in row["reason"]
        weekly = row["tf"]["W"]
        assert weekly["strat"] == "1" and weekly["color"] == "red"
        assert weekly["high"] == 18 and weekly["open"] == 17 and weekly["close"] == 14
        monthly = row["tf"]["M"]
        assert monthly["strat"] == "2U" and monthly["color"] == "green" and monthly["high"] == 48
        assert row["monthly_2u"] is True and row["mw_green"] is False
        detail = next(c["detail"] for c in row["score_breakdown"] if c["key"] == "continuity")
        assert detail == "M +4 · D +1 (W not green)"  # the setup and Monthly 2U add nothing
        assert "13.01" not in detail

        # The weekly chart shows the week in progress (Monday's bar), like the daily chart shows today;
        # the completed week before it is still the inside week the setup reads.
        candles = chart_payload(df, "W", 8)
        assert candles[-1]["time"] == "2026-10-19" and candles[-1]["high"] == 13.01
        assert candles[-2]["time"] == "2026-10-12"
        assert candles[-2]["high"] == 18 and candles[-2]["strat"] == "1"
        daily = chart_payload(df, "D", 3)
        assert daily[-1]["time"] == "2026-10-19" and daily[-1]["high"] == 13.01

    def test_a_name_with_no_setup_does_not_use_the_open_weeks_high_as_the_nearest_trigger(self):
        rows = _fill("2026-07-01", "2026-10-02", (10, 11, 9, 10))
        rows += _fill("2026-10-05", "2026-10-09", (10, 12, 9, 11))
        rows += _fill("2026-10-12", "2026-10-16", (11, 14, 10.5, 13))  # 2U, not an inside bar or a hammer
        rows.append(("2026-10-19", 12.4, 13.01, 10.0, 12.8))  # 2D, high 13.01 sits closer to price than 14
        row = scan_symbol(Member("CTVA", "Corteva", "Materials", "stock", "SP500"), _frame(rows))
        assert row["trigger"] is None and row["has_setup"] is False
        assert row["nearest_trigger"] == 14
        assert row["nearest_trigger_label"] == "last week's high"
        assert row["nearest_trigger"] != 13.01
        state = timeframe_state("W", to_candles(resample(_frame(rows), "W")))
        assert state.high == 14 and state.strat == "2U"

    def test_friday_morning_still_uses_the_prior_completed_week(self, monkeypatch):
        monkeypatch.setattr("strat.periods.clock", lambda: _at("2026-10-16", 11))
        row = scan_symbol(Member("CTVA", "Corteva", "Materials", "stock", "SP500"), _ctva_like(monday=False))
        assert row["tf"]["W"]["high"] == 20
        assert row["trigger"] != 18

    def test_friday_after_the_close_uses_the_week_that_just_finished(self, monkeypatch):
        monkeypatch.setattr("strat.periods.clock", lambda: _at("2026-10-16", 17))
        row = scan_symbol(Member("CTVA", "Corteva", "Materials", "stock", "SP500"), _ctva_like(monday=False))
        assert row["trigger"] == 18 and row["tf"]["W"]["high"] == 18 and row["tf"]["W"]["strat"] == "1"
