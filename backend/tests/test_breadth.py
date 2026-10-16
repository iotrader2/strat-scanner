import json

from strat.breadth import parse_fear_greed, parse_issues, parse_nasi

NASI = """$NASI, Daily
Day       Date       Open       High        Low      Close      Volume
=== ========== ========== ========== ========== ========== ===========
Thu 10-15-2026   -742.550   -742.550   -742.550   -742.550           0
Wed 10-14-2026   -728.630   -728.630   -728.630   -728.630           0
Tue 10-13-2026    12.000     12.000     12.000     12.000           0
"""

FEAR = {
    "fear_and_greed": {
        "score": 17.94,
        "rating": "extreme fear",
        "previous_close": 31.5,
        "previous_1_week": 46.4,
        "previous_1_month": 27.3,
    }
}

DIARY = {
    "data": {
        "instrumentSets": [
            {
                "headerFields": [{"value": "name", "label": "Issues"}],
                "instruments": [
                    {"name": "Advancing", "NASDAQ": "1,289", "NYSE": "1,153"},
                    {"name": "Declining", "NASDAQ": "3,669", "NYSE": "1,570"},
                    {"name": "Unchanged", "NASDAQ": "152", "NYSE": "60"},
                    {"name": "Total", "NASDAQ": "5,110", "NYSE": "2,783"},
                ],
            },
            {
                "headerFields": [{"value": "name", "label": "Share Volume"}],
                "instruments": [
                    {"name": "Advancing", "NASDAQ": "2,933,436,857", "NYSE": "2,386,528,404"},
                    {"name": "Declining", "NASDAQ": "6,550,000,000", "NYSE": "3,000,000,000"},
                    {"name": "Unchanged", "NASDAQ": "50,000,000", "NYSE": "60,000,000"},
                ],
            },
        ]
    }
}


def test_nasi_is_chronological_with_the_latest_close_and_day_change():
    nasi = parse_nasi(NASI)
    assert [p["time"] for p in nasi["points"]] == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert nasi["points"][0]["value"] == 12.0
    assert nasi["value"] == -742.55
    assert nasi["change"] == -13.92
    assert nasi["as_of"] == "2026-10-15"


def test_nasi_keeps_only_the_recent_window():
    lines = ["$NASI, Daily"] + [
        f"Mon 01-{(i % 28) + 1:02d}-2024   {float(i):.3f}   {float(i):.3f}   {float(i):.3f}   {float(i):.3f}           0"
        for i in range(1, 301)
    ]
    assert len(parse_nasi("\n".join(lines))["points"]) == 252


def test_nasi_rejects_an_empty_table():
    assert parse_nasi("not a quote table") is None


def test_fear_and_greed_reads_the_score_rating_and_history():
    assert parse_fear_greed(FEAR) == {
        "score": 17.9,
        "rating": "extreme fear",
        "previous_close": 31.5,
        "previous_week": 46.4,
        "previous_month": 27.3,
    }
    assert parse_fear_greed({}) is None
    assert parse_fear_greed({"fear_and_greed": {"rating": "fear"}}) is None


def test_issues_parse_nasdaq_and_nyse_counts():
    assert parse_issues(DIARY) == {
        "nasdaq": {"advancing": 1289, "declining": 3669, "unchanged": 152},
        "nyse": {"advancing": 1153, "declining": 1570, "unchanged": 60},
    }
    broken = json.loads(json.dumps(DIARY))
    broken["data"]["instrumentSets"][0]["instruments"][0]["NASDAQ"] = "n/a"
    assert "nasdaq" not in parse_issues(broken)
    assert parse_issues({"data": {}}) is None
