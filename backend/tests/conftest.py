"""Keep the test process off the live fetcher.

The scheduler starts from the API's startup hook. Setting this before any test
imports the app means TestClient never opens a Yahoo connection.
"""

import os

os.environ["STRAT_SCHEDULER"] = "0"
os.environ.setdefault("STRAT_DATA_PROVIDER", "yahoo")
