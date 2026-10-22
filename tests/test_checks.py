from datetime import datetime

from trustlayer import chaos
from trustlayer.baseline import NULL_CHECK_COLUMNS
from trustlayer.checks import evaluate
from trustlayer.lineage import walk

HOUR = datetime(2024, 3, 4, 9)  # Monday 09:00 -> hour of week 9, hour of day 9
BASE = {
    ("ROW_COUNT", 9): (4000.0, 300.0),
    ("AVG_TOTAL_AMOUNT", 9): (27.0, 1.5),
    ("DUPLICATE_RATE", -1): (0.0005, None),
    ("INVALID_RATE", 9): (0.015, None),
    **{(f"NULL_RATE:{c}", 9): (0.04, None) for c in NULL_CHECK_COLUMNS},
}


def profile(n=4000, avg=27.0, nulls=None, distinct=None, invalid=None):
    prof = {"ROW_COUNT": n, "AVG_TOTAL_AMOUNT": avg,
            "DISTINCT_ROWS": n if distinct is None else distinct,
            "INVALID_ROWS": int(n * 0.015) if invalid is None else invalid}
    for c in NULL_CHECK_COLUMNS:
        prof[f"NULLS:{c}"] = int(n * 0.04)
    prof.update(nulls or {})
    return prof


def failed(results):
    return {(r.check, r.column) for r in results if r.status == "FAIL"}


def test_healthy_batch_passes():
    assert failed(evaluate(profile(), BASE, HOUR)) == set()


def test_duplicates_fail_uniqueness():
    assert ("uniqueness", None) in failed(evaluate(profile(n=5200, distinct=4000), BASE, HOUR))


def test_seasonal_growth_is_absorbed_by_volume_level():
    busy = profile(n=5600)  # 40% above the hour-of-week baseline

    def volume(level):
        return next(r.status for r in evaluate(busy, BASE, HOUR, level=level) if r.check == "volume")

    assert volume(1.0) == "WARN"
    assert volume(1.35) == "PASS"


def test_sudden_collapse_fails_even_at_high_level():
    assert ("volume", None) in failed(evaluate(profile(n=900), BASE, HOUR, level=1.35))


def test_empty_batch_fails_volume_only():
    results = evaluate(profile(n=0), BASE, HOUR)
    assert [(r.check, r.status) for r in results] == [("volume", "FAIL")]


def test_dropped_column_is_schema_drift():
    results = evaluate(profile(nulls={"NULLS:TIP_AMOUNT": 4000}), BASE, HOUR)
    assert ("schema_drift", "TIP_AMOUNT") in failed(results)


def test_dropped_amount_column_is_quarantined_not_crashed():
    results = evaluate(profile(avg=None, nulls={"NULLS:TOTAL_AMOUNT": 4000}), BASE, HOUR)
    assert ("schema_drift", "TOTAL_AMOUNT") in failed(results)


def test_cents_instead_of_dollars_fails_distribution():
    assert ("distribution", "TOTAL_AMOUNT") in failed(evaluate(profile(avg=2700.0), BASE, HOUR))


def test_every_chaos_scenario_targets_one_batch():
    for name, (description, statements) in chaos.SCENARIOS.items():
        assert description, name
        assert all("BATCH_ID = {b}" in s for s in statements), name


def test_lineage_walk_follows_view_chains():
    edges = {
        "CURATED.YELLOW_TRIPS": ["MART.DAILY_REVENUE", "MART.PAYMENT_MIX"],
        "MART.DAILY_REVENUE": ["MART.EXEC_KPIS"],
    }
    assert walk(edges, "CURATED.YELLOW_TRIPS") == [
        ("MART.DAILY_REVENUE", 1), ("MART.PAYMENT_MIX", 1), ("MART.EXEC_KPIS", 2),
    ]
