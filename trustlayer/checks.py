"""Data checks for one staged batch. All counting happens in Exasol; Python only
compares the numbers with the learned baseline."""
from dataclasses import dataclass

from trustlayer import rules
from trustlayer.baseline import DUPLICATE_KEY, INVALID_ROW, NULL_CHECK_COLUMNS, hour_of_week

STAGE = "STAGE.YELLOW_TRIPS"
# Below this many rows, rates and averages swing naturally (a quiet 3 AM hour), so
# only clear failures count; small warnings are ignored.
SMALL_BATCH_ROWS = 1000


@dataclass
class CheckResult:
    check: str
    column: str | None
    status: str
    observed: float | None
    expected: float | None
    details: str


def profile_batch(conn, batch_id: str) -> dict:
    nulls = ", ".join(
        f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS \"NULLS:{c}\"" for c in NULL_CHECK_COLUMNS
    )
    stmt = conn.execute(f"""
        SELECT COUNT(*) AS ROW_COUNT,
               AVG(TOTAL_AMOUNT) AS AVG_TOTAL_AMOUNT,
               SUM(CASE WHEN {INVALID_ROW} THEN 1 ELSE 0 END) AS INVALID_ROWS,
               {nulls}
        FROM {STAGE} WHERE BATCH_ID = {{b}}""", {"b": batch_id})
    prof = dict(zip(stmt.column_names(), stmt.fetchone()))
    prof["DISTINCT_ROWS"] = conn.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT {', '.join(DUPLICATE_KEY)} FROM {STAGE} WHERE BATCH_ID = {{b}})""",
        {"b": batch_id}).fetchval()
    return prof


def evaluate(prof: dict, base: dict, batch_hour, level: float = 1.0) -> list[CheckResult]:
    """Turn a batch profile plus the baseline into check results. Pure function.

    level scales expected volume to current traffic (1.1 = running 10% above baseline).
    """
    how, hod = hour_of_week(batch_hour), batch_hour.hour
    n = int(prof["ROW_COUNT"] or 0)
    results = []

    # Only a 25%+ (warn) or 50%+ (fail) change in volume counts.
    center, scale = base.get(("ROW_COUNT", how), (None, None))
    if center is not None:
        center, scale = center * level, scale * level
    status, z = rules.classify_deviation(n, center, scale, min_rel=0.5)
    if n == 0:
        status = rules.FAIL
    results.append(CheckResult(
        "volume", None, status, n, center,
        f"{n:,} rows vs usual {center:,.0f} for this hour of week (z={z:+.1f})" if center else f"{n:,} rows, no baseline",
    ))
    if n == 0:
        return results  # nothing else to measure on an empty batch

    avg_total = prof["AVG_TOTAL_AMOUNT"]
    center, scale = base.get(("AVG_TOTAL_AMOUNT", how), (None, None))
    min_rel = 1.0 if n < SMALL_BATCH_ROWS else 0.5
    status, z = rules.classify_deviation(avg_total, center, scale, min_rel=min_rel)
    results.append(CheckResult(
        "distribution", "TOTAL_AMOUNT", status, avg_total, center,
        "no amounts to average (completeness reports it)" if avg_total is None
        else f"average total ${avg_total:,.2f} vs usual ${center:,.2f} (z={z:+.1f})" if center else "no baseline",
    ))

    for col in NULL_CHECK_COLUMNS:
        rate = int(prof[f"NULLS:{col}"] or 0) / n
        base_rate = base.get((f"NULL_RATE:{col}", hod), (0.0, None))[0]
        if rules.is_dropped_column(rate, base_rate):
            results.append(CheckResult(
                "schema_drift", col, rules.FAIL, rate, base_rate,
                f"{col} arrived completely empty; normally {base_rate:.1%} empty. Upstream likely dropped it.",
            ))
            continue
        status = rules.classify_rate_increase(rate, base_rate, warn_delta=0.10, fail_delta=0.25)
        results.append(CheckResult(
            "completeness", col, status, rate, base_rate,
            f"{rate:.1%} empty vs usual {base_rate:.1%}",
        ))

    dup_rate = (n - int(prof["DISTINCT_ROWS"] or 0)) / n
    base_rate = base.get(("DUPLICATE_RATE", -1), (0.0, None))[0]
    status = rules.classify_rate_increase(dup_rate, base_rate, warn_delta=0.005, fail_delta=0.02)
    results.append(CheckResult(
        "uniqueness", None, status, dup_rate, base_rate,
        f"{dup_rate:.1%} duplicate trips vs usual {base_rate:.2%}",
    ))

    bad_rate = int(prof["INVALID_ROWS"] or 0) / n
    base_rate = base.get(("INVALID_RATE", hod), (0.0, None))[0]
    status = rules.classify_rate_increase(bad_rate, base_rate, warn_delta=0.03, fail_delta=0.10)
    results.append(CheckResult(
        "validity", None, status, bad_rate, base_rate,
        f"{bad_rate:.1%} impossible rows (negative amounts or dropoff before pickup) vs usual {base_rate:.1%}",
    ))

    if n < SMALL_BATCH_ROWS:
        for r in results:
            if r.status == rules.WARN and r.check != "volume":
                r.status = rules.PASS
                r.details += f" (ignored: only {n:,} rows)"
    return results
