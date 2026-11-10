"""Keep the test process off the live fetcher.

The scheduler starts from the API's startup hook. Setting this before any test
imports the app means TestClient never opens a Yahoo connection.
"""

import os

import pytest

os.environ["STRAT_SCHEDULER"] = "0"
os.environ.setdefault("STRAT_DATA_PROVIDER", "yahoo")

# User data goes to SQLite in tests; the Postgres path is exercised only by test_userdb_postgres.py when
# TEST_DATABASE_URL is set.
os.environ.pop("DATABASE_URL", None)


@pytest.fixture(autouse=True)
def _no_live_yahoo_15m(monkeypatch):
    """Alert polls must not hit Yahoo during tests. A test that needs bars passes them in."""
    monkeypatch.setattr("strat.alerts_live.fetch_yahoo_15m", lambda *a, **k: ({}, set()))
    monkeypatch.setattr("strat.yahoo_15m.fetch_yahoo_15m", lambda *a, **k: ({}, set()))
