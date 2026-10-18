from datetime import date, datetime
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


def test_fetch_window_stays_short_when_the_cache_is_current():
    now = datetime(2026, 10, 19, 11, 0, tzinfo=ET)
    assert scheduler.fetch_period(now, date(2026, 10, 16)) == "5d"
    assert scheduler.fetch_period(now, date(2026, 10, 1)) == "3mo"
    assert scheduler.fetch_period(now, None) == "3y"
    assert scheduler.fetch_period(now, date(2026, 10, 16), full=True) == "3y"
