import pandas as pd
import pytest

from strat.scanner import sector_entries

ETFS = [
    ("XLK", "Technology", "Information Technology", "spdr"),
    ("XLF", "Financials", "Financials", "spdr"),
    ("XLV", "Health Care", "Health Care", "spdr"),
    ("XLE", "Energy", "Energy", "spdr"),
    ("SMH", "Semis", "Information Technology", "industry"),
]
SCORES = {"XLK": 31.0, "XLF": 55.0, "XLV": 76.0, "XLE": 55.0, "SMH": 90.0}


def _daily(seed: float) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=300)
    base = pd.Series(range(300), index=idx, dtype=float) * 0.1 + seed
    return pd.DataFrame(
        {"open": base, "high": base + 1, "low": base - 1, "close": base + 0.5, "volume": 1e6}, index=idx
    )


@pytest.fixture
def inputs():
    rows = {s: {"symbol": s, "score": sc} for s, sc in SCORES.items()}
    daily = {s: _daily(50 + i) for i, s in enumerate(SCORES)}
    return rows, daily


@pytest.mark.parametrize("tf", ["M", "W", "D"])
def test_sector_cards_sorted_by_score_descending(inputs, tf):
    rows, daily = inputs
    entries = sector_entries(ETFS, rows, daily, tf, 30)
    # ETFS lists XLK (31) first; the strongest must come first regardless of list order.
    assert [e["symbol"] for e in entries] == ["SMH", "XLV", "XLE", "XLF", "XLK"]
    scores = [e["row"]["score"] for e in entries]
    assert scores == sorted(scores, reverse=True)
    assert all(e["candles"] for e in entries)


def test_sorting_within_group_keeps_strongest_first(inputs):
    rows, daily = inputs
    spdr = [e["symbol"] for e in sector_entries(ETFS, rows, daily, "W", 30) if e["group"] == "spdr"]
    assert spdr[0] == "XLV" and spdr[-1] == "XLK"


def test_missing_data_is_skipped(inputs):
    rows, daily = inputs
    del daily["XLV"]
    assert "XLV" not in [e["symbol"] for e in sector_entries(ETFS, rows, daily, "D", 30)]
