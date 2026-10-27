from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from strat import scheduler

ET = ZoneInfo("America/New_York")


def test_the_last_completed_session_skips_the_weekend_and_waits_for_the_close():
    sunday = datetime(2026, 10, 18, 12, 0, tzinfo=ET)
    assert scheduler.last_completed_session(sunday) == date(2026, 10, 16)
    monday_morning = datetime(2026, 10, 19, 10, 0, tzinfo=ET)
    assert scheduler.last_completed_session(monday_morning) == date(2026, 10, 16)
    monday_after = datetime(2026, 10, 19, 16, 30, tzinfo=ET)
    assert scheduler.last_completed_session(monday_after) == date(2026, 10, 19)


def test_history_is_due_until_that_session_is_cached():
    monday = datetime(2026, 10, 19, 10, 0, tzinfo=ET)
    assert scheduler.history_due(monday, None)
    assert scheduler.history_due(monday, date(2026, 10, 15))
    assert not scheduler.history_due(monday, date(2026, 10, 16))


def test_the_quote_poll_is_inside_the_session_and_at_most_every_interval():
    now = datetime(2026, 10, 19, 10, 0, tzinfo=ET)
    assert scheduler.intraday_due(now, None, interval=900)
    assert not scheduler.intraday_due(now, datetime(2026, 10, 19, 9, 50, tzinfo=ET), interval=900)
    assert scheduler.intraday_due(now, datetime(2026, 10, 19, 9, 44, tzinfo=ET), interval=900)
    assert not scheduler.intraday_due(datetime(2026, 10, 18, 12, 0, tzinfo=ET), None, interval=900)
    assert not scheduler.intraday_due(datetime(2026, 10, 19, 9, 29, tzinfo=ET), None, interval=900)
    assert not scheduler.regular_session(datetime(2026, 10, 19, 16, 0, tzinfo=ET))


def test_decide_confirms_history_before_polling_quotes():
    now = datetime(2026, 10, 19, 11, 0, tzinfo=ET)
    assert scheduler.decide(now, date(2026, 10, 15), None) == "history"
    assert scheduler.decide(now, date(2026, 10, 16), None) == "intraday"
    assert scheduler.decide(now, date(2026, 10, 16), now) is None
    assert scheduler.decide(datetime(2026, 10, 18, 12, 0, tzinfo=ET), date(2026, 10, 16), None) is None


def test_premarket_follows_eastern_time_across_daylight_saving():
    # The same UTC instant is before 04:00 in January (EST, UTC-5) and inside premarket in July (EDT, UTC-4).
    assert scheduler.session_phase(datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc)) == "closed"
    assert scheduler.session_phase(datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)) == "premarket"
    # 04:00 local is the open of premarket in both seasons; 03:59 is still closed.
    assert scheduler.session_phase(datetime(2026, 1, 15, 8, 59, tzinfo=timezone.utc)) == "closed"
    assert scheduler.session_phase(datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)) == "premarket"
    assert scheduler.session_phase(datetime(2026, 7, 15, 7, 59, tzinfo=timezone.utc)) == "closed"
    assert scheduler.session_phase(datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)) == "premarket"
    # 09:30 local opens the regular session. 13:30 UTC is 09:30 EDT and 08:30 EST.
    assert scheduler.session_phase(datetime(2026, 7, 15, 13, 29, tzinfo=timezone.utc)) == "premarket"
    assert scheduler.session_phase(datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)) == "regular"
    assert scheduler.session_phase(datetime(2026, 1, 15, 14, 29, tzinfo=timezone.utc)) == "premarket"
    assert scheduler.session_phase(datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)) == "regular"
    # 16:00 local starts after hours; 20:00 local ends it. 20:00 UTC is 16:00 EDT and 15:00 EST.
    assert scheduler.session_phase(datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)) == "after_hours"
    assert scheduler.session_phase(datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)) == "regular"
    assert scheduler.session_phase(datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)) == "closed"  # 20:00 EDT
    assert scheduler.session_phase(datetime(2026, 1, 16, 0, 59, tzinfo=timezone.utc)) == "after_hours"  # 19:59 EST
    assert scheduler.session_phase(datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)) == "closed"  # 20:00 EST
    assert scheduler.session_phase(datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)) == "closed"  # Saturday
    # A naive clock is Eastern, matching the rest of the scheduler.
    assert scheduler.session_phase(datetime(2026, 10, 20, 8, 0)) == "premarket"


def test_extended_hours_poll_the_indexes_and_history_still_wins():
    pre = datetime(2026, 10, 20, 8, 0, tzinfo=ET)
    assert scheduler.decide(pre, date(2026, 10, 19), None, None) == "extended"
    assert scheduler.extended_due(pre, datetime(2026, 10, 20, 7, 50, tzinfo=ET), interval=900) is False
    assert scheduler.decide(pre, date(2026, 10, 19), None, datetime(2026, 10, 20, 7, 40, tzinfo=ET)) == "extended"
    assert scheduler.decide(pre, date(2026, 10, 16), None, None) == "history"
    opened = datetime(2026, 10, 20, 9, 30, tzinfo=ET)
    assert scheduler.decide(opened, date(2026, 10, 19), None, pre) == "intraday"
    after = datetime(2026, 10, 20, 16, 10, tzinfo=ET)
    assert scheduler.session_phase(after) == "after_hours"
    assert scheduler.decide(after, date(2026, 10, 19), None, None) == "extended"
    assert scheduler.decide(datetime(2026, 10, 20, 20, 0, tzinfo=ET), date(2026, 10, 20), None, None) is None


def test_alert_archive_waits_until_1605_eastern_and_follows_daylight_saving():
    # 16:04 local stays live; 16:05 local is the first minute that archives today. The same UTC
    # instant is 16:05 in July (EDT) and 15:05 in January (EST).
    july_early = datetime(2026, 7, 15, 20, 4, tzinfo=timezone.utc)  # 16:04 EDT, Wednesday
    july_due = datetime(2026, 7, 15, 20, 5, tzinfo=timezone.utc)  # 16:05 EDT
    jan_not_yet = datetime(2026, 1, 15, 20, 5, tzinfo=timezone.utc)  # 15:05 EST, Thursday
    jan_early = datetime(2026, 1, 15, 21, 4, tzinfo=timezone.utc)  # 16:04 EST
    jan_due = datetime(2026, 1, 15, 21, 5, tzinfo=timezone.utc)  # 16:05 EST
    assert scheduler.archive_through(july_early) == date(2026, 7, 14)
    assert scheduler.archive_through(july_due) == date(2026, 7, 15)
    assert scheduler.archive_through(jan_not_yet) == date(2026, 1, 14)
    assert scheduler.archive_through(jan_early) == date(2026, 1, 14)
    assert scheduler.archive_through(jan_due) == date(2026, 1, 15)
    # A weekend start catches the Friday session. Monday morning still has not closed Monday.
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=ET)
    monday_open = datetime(2026, 10, 26, 9, 30, tzinfo=ET)
    assert scheduler.archive_through(saturday) == date(2026, 10, 23)
    assert scheduler.archive_through(monday_open) == date(2026, 10, 25)
    assert scheduler.previous_weekday(monday_open) == date(2026, 10, 23)
    assert scheduler.previous_weekday(saturday) == date(2026, 10, 23)


def test_fetch_window_stays_short_when_the_cache_is_current():
    now = datetime(2026, 10, 19, 11, 0, tzinfo=ET)
    assert scheduler.fetch_period(now, date(2026, 10, 16)) == "5d"
    assert scheduler.fetch_period(now, date(2026, 10, 1)) == "3mo"
    assert scheduler.fetch_period(now, None) == "3y"
    assert scheduler.fetch_period(now, date(2026, 10, 16), full=True) == "3y"
