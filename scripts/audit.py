"""Independent audit: recompute what the dashboard shows from base tables and check the
quarantine guarantee. Run: python scripts/audit.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trustlayer.db import connect  # noqa: E402
from trustlayer.schema import TRIPS  # noqa: E402

results = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


c = connect()
v = dict(zip(*(lambda s: (s.column_names(), s.fetchone()))(c.execute(
    "SELECT * FROM TRUSTLAYER.TRUST_SCORES WHERE TABLE_NAME = {t}", {"t": TRIPS}))))

# 1. Missing hours: blocked hours with no successful run of the same hour.
blocked = {str(h) for (h,) in c.execute(
    "SELECT BATCH_START FROM TRUSTLAYER.LOAD_LOG WHERE STATUS IN ('QUARANTINED','FAILED')").fetchall()}
ok_hours = {str(h) for (h,) in c.execute(
    "SELECT BATCH_START FROM TRUSTLAYER.LOAD_LOG WHERE STATUS = 'PROMOTED'").fetchall()}
missing = len(blocked - ok_hours)
check("missing hours", missing == int(v["MISSING_HOURS"]), f"view={v['MISSING_HOURS']} recomputed={missing}")

# 2. Every missing hour has an open incident and vice versa.
open_inc_hours = {str(h) for (h,) in c.execute("""
    SELECT l.BATCH_START FROM TRUSTLAYER.INCIDENTS i JOIN TRUSTLAYER.LOAD_LOG l ON l.BATCH_ID = i.BATCH_ID
    WHERE i.STATUS = 'OPEN'""").fetchall()}
check("open incidents match missing hours", open_inc_hours == (blocked - ok_hours),
      f"open-incident hours={sorted(open_inc_hours)} missing={sorted(blocked - ok_hours)}")

# 3. Rows held = rows actually sitting in QUARANTINE for open incidents.
held_claim = c.execute("SELECT NVL(SUM(ROWS_QUARANTINED),0) FROM TRUSTLAYER.INCIDENTS WHERE STATUS='OPEN'").fetchval()
held_real = c.execute("""SELECT COUNT(*) FROM QUARANTINE.YELLOW_TRIPS q JOIN TRUSTLAYER.INCIDENTS i
    ON i.BATCH_ID = q.BATCH_ID WHERE i.STATUS = 'OPEN'""").fetchval()
check("rows held", int(held_claim) == int(held_real), f"incidents say {held_claim}, quarantine holds {held_real}")

# 4. Trust score formula.
quality = c.execute("""SELECT NVL(MAX(h.HEALTH_SCORE),100) FROM TRUSTLAYER.BATCH_HEALTH h
    WHERE h.BATCH_ID = {b}""", {"b": v["LAST_PROMOTED_BATCH"]}).fetchval()
fresh_pen = int(v["FRESHNESS_PENALTY"])
expected = max(0, float(quality) - max(fresh_pen, min(40, 10 * missing)))
check("trust score", abs(expected - float(v["TRUST_SCORE"])) < 1e-6,
      f"view={v['TRUST_SCORE']} recomputed={expected} (quality {quality}, freshness -{fresh_pen}, missing -{min(40, 10 * missing)})")

# 5. Quarantine guarantee: no quarantined batch id ever reaches CURATED.
leaked = c.execute(f"""SELECT COUNT(*) FROM {TRIPS} WHERE BATCH_ID IN
    (SELECT BATCH_ID FROM TRUSTLAYER.LOAD_LOG WHERE STATUS = 'QUARANTINED')""").fetchval()
check("no quarantined rows in CURATED", leaked == 0, f"{leaked} leaked rows")

# 6. Marts only see curated data: blocked hours (not yet re-run) contribute nothing.
for h in sorted(blocked - ok_hours):
    n = c.execute(f"""SELECT COUNT(*) FROM {TRIPS}
        WHERE TPEP_PICKUP_DATETIME >= {{h}} AND TPEP_PICKUP_DATETIME < ADD_HOURS({{h}}, 1)
          AND BATCH_ID NOT LIKE 'backfill-%'""", {"h": h[:19]}).fetchval()
    check(f"blocked hour {h[:16]} absent from CURATED", n == 0, f"{n} rows")

# 7. Each published hour is in CURATED exactly once (no double publish after retry).
dup_hours = c.execute(f"""SELECT COUNT(*) FROM (
    SELECT BATCH_START FROM TRUSTLAYER.LOAD_LOG WHERE TABLE_NAME = {{t}} AND STATUS = 'PROMOTED'
      AND BATCH_ID NOT LIKE 'backfill-%' GROUP BY BATCH_START HAVING COUNT(*) > 1)""", {"t": TRIPS}).fetchval()
check("each hour published at most once", dup_hours == 0, f"{dup_hours} hours published twice")

# 8. Row counts in the load log match what was published.
mismatch = c.execute(f"""SELECT COUNT(*) FROM TRUSTLAYER.LOAD_LOG l
    WHERE l.STATUS = 'PROMOTED' AND l.BATCH_ID NOT LIKE 'backfill-%'
      AND l.ROW_COUNT <> (SELECT COUNT(*) FROM {TRIPS} t WHERE t.BATCH_ID = l.BATCH_ID)""").fetchval()
check("load log row counts", mismatch == 0, f"{mismatch} batches disagree with CURATED")

# 9. Published batch row counts match the source hour in RAW (nothing dropped or added).
src_mismatch = c.execute("""SELECT COUNT(*) FROM (
    SELECT l.BATCH_ID, l.ROW_COUNT, COUNT(r.VENDORID) + SUM(CASE WHEN r.VENDORID IS NULL
               AND r.TPEP_PICKUP_DATETIME IS NOT NULL THEN 1 ELSE 0 END) AS SRC
    FROM TRUSTLAYER.LOAD_LOG l
    LEFT JOIN RAW.YELLOW_TRIPS r
      ON r.TPEP_PICKUP_DATETIME >= l.BATCH_START AND r.TPEP_PICKUP_DATETIME < l.BATCH_END
    WHERE l.STATUS = 'PROMOTED' AND l.BATCH_ID NOT LIKE 'backfill-%'
    GROUP BY l.BATCH_ID, l.ROW_COUNT) WHERE ROW_COUNT <> SRC""").fetchval()
check("published hours match source", src_mismatch == 0, f"{src_mismatch} batches differ from RAW")

# 10. Mart totals equal a direct aggregate of CURATED.
mart = c.execute("SELECT SUM(TRIPS), ROUND(SUM(REVENUE),2) FROM MART.DAILY_REVENUE").fetchone()
direct = c.execute(f"SELECT COUNT(*), ROUND(SUM(TOTAL_AMOUNT),2) FROM {TRIPS}").fetchone()
check("DAILY_REVENUE matches CURATED", tuple(map(float, mart)) == tuple(map(float, direct)), f"mart={mart} direct={direct}")

# 11. Nothing left behind in STAGE.
stage = c.execute("SELECT COUNT(*) FROM STAGE.YELLOW_TRIPS").fetchval()
check("STAGE is empty between batches", stage == 0, f"{stage} rows")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
