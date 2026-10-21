"""Plain-English incident reports.

Gemini receives only aggregate evidence computed in Exasol (check results, counts,
amount statistics, affected dashboards), never raw trip rows, and is not told which
failure was injected: it has to reason from the evidence. Reports are cached on the
incident, and a template report is used when Gemini is unavailable.
"""
import json
import os

from trustlayer import lineage
from trustlayer.baseline import NULL_CHECK_COLUMNS
from trustlayer.schema import TRIP_COLUMN_NAMES, TRIPS

QUARANTINE = "QUARANTINE.YELLOW_TRIPS"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]

PROMPT = """You are TrustLayer, a data reliability assistant. A data pipeline batch was
blocked by automated quality checks before it reached business dashboards. Using ONLY
the evidence below, write a short incident report in Markdown for a data engineer who
was just paged.

Use exactly these sections:
**Summary** - one or two sentences.
**What broke** - bullet points naming the failed checks with the key numbers.
**Likely cause** - the most probable upstream cause, reasoning from the numbers. Say how confident you are.
**Impact** - which dashboards and owners were protected, and that they now miss this hour of data.
**Recommended fix** - 2-4 concrete steps; include one Exasol SQL query that would help investigate,
  using the table QUARANTINE.YELLOW_TRIPS filtered by BATCH_ID and only the column names
  listed in quarantine_table_columns.

Keep it under 250 words. Do not invent facts that are not in the evidence.

Evidence (JSON):
{evidence}
"""


def gather_evidence(conn, incident_id: str) -> dict:
    stmt = conn.execute(
        "SELECT * FROM TRUSTLAYER.INCIDENTS WHERE INCIDENT_ID = {i}", {"i": incident_id})
    inc = dict(zip(stmt.column_names(), stmt.fetchone()))
    batch_id = inc["BATCH_ID"]
    batch = conn.execute(
        "SELECT BATCH_START, BATCH_END FROM TRUSTLAYER.LOAD_LOG WHERE BATCH_ID = {b}", {"b": batch_id}
    ).fetchone()
    checks = [
        {"check": c, "column": col, "status": s, "observed": o, "expected": e, "details": d}
        for c, col, s, o, e, d in conn.execute("""
            SELECT CHECK_NAME, COLUMN_NAME, STATUS, OBSERVED, EXPECTED, DETAILS
            FROM TRUSTLAYER.CHECK_RESULTS WHERE BATCH_ID = {b}
            ORDER BY CASE STATUS WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, CHECK_NAME""",
            {"b": batch_id}).fetchall()
    ]
    nulls = ", ".join(f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS \"{c}\"" for c in NULL_CHECK_COLUMNS)
    stmt = conn.execute(f"""
        SELECT COUNT(*) AS ROWS_HELD,
               MIN(TOTAL_AMOUNT) AS MIN_TOTAL, MEDIAN(TOTAL_AMOUNT) AS MEDIAN_TOTAL, MAX(TOTAL_AMOUNT) AS MAX_TOTAL,
               SUM(CASE WHEN TOTAL_AMOUNT < 0 THEN 1 ELSE 0 END) AS NEGATIVE_TOTALS,
               {nulls}
        FROM {QUARANTINE} WHERE BATCH_ID = {{b}}""", {"b": batch_id})
    held = dict(zip(stmt.column_names(), stmt.fetchone()))
    held_nulls = {c: held.pop(c) for c in NULL_CHECK_COLUMNS}
    recent = conn.execute("""
        SELECT BATCH_START, STATUS, ROW_COUNT FROM TRUSTLAYER.LOAD_LOG
        WHERE TABLE_NAME = {t} AND BATCH_ID NOT LIKE 'backfill-%' AND BATCH_START < {s}
        ORDER BY BATCH_START DESC LIMIT 5""", {"t": TRIPS, "s": str(batch[0])}).fetchall()
    impact = lineage.affected(conn, TRIPS)
    return {
        "incident": {"id": incident_id, "title": inc["TITLE"], "severity": inc["SEVERITY"]},
        "table": TRIPS,
        "batch": {"id": batch_id, "hour_start": str(batch[0])[:16], "hour_end": str(batch[1])[:16]},
        "checks": checks,
        "quarantined_rows_profile": {**held, "empty_values_by_column": held_nulls},
        "previous_batches": [{"hour": str(h)[:16], "status": s, "rows": n} for h, s, n in recent],
        "downstream_views": impact["views"],
        "protected_dashboards": impact["dashboards"],
        "quarantine_table_columns": [*TRIP_COLUMN_NAMES, "BATCH_ID", "QUARANTINED_AT", "REASON"],
    }


def template_report(ev: dict) -> str:
    failed = [c for c in ev["checks"] if c["status"] == "FAIL"]
    dashboards = ", ".join(f"{d['dashboard']} ({d['owner']})" for d in ev["protected_dashboards"]) or "none"
    lines = [
        "**Summary**",
        f"The {ev['batch']['hour_start']} batch for {ev['table']} was quarantined because "
        f"{len(failed)} check(s) failed. Dashboards kept showing the last good data.",
        "",
        "**What broke**",
        *[f"- {c['check']}{' (' + c['column'] + ')' if c['column'] else ''}: {c['details']}" for c in failed],
        "",
        "**Impact**",
        f"Protected dashboards: {dashboards}. They are missing this hour until it is reloaded.",
        "",
        "**Recommended fix**",
        "1. Inspect the held rows:",
        f"   `SELECT * FROM QUARANTINE.YELLOW_TRIPS WHERE BATCH_ID = '{ev['batch']['id']}' LIMIT 100;`",
        "2. Fix the upstream job, then re-run the hour: "
        f"`python -m trustlayer.cli retry {ev['incident']['id']}`",
    ]
    return "\n".join(lines)


def _gemini(prompt: str) -> tuple[str, str]:
    """Try the configured model, then lighter ones: free-tier models are often briefly overloaded."""
    from google import genai  # imported lazily so the pipeline runs without the SDK configured

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = [os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), *FALLBACK_MODELS]
    errors = []
    for model in dict.fromkeys(models):  # de-duplicate, keep order
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return resp.text.strip(), f"gemini:{model}"
        except Exception as exc:  # noqa: BLE001 - 429/503 on one model: try the next
            errors.append(f"{model}: {str(exc).splitlines()[0][:80]}")
    raise RuntimeError("; ".join(errors))


def generate(conn, incident_id: str, force: bool = False) -> tuple[str, str]:
    """Return (report_markdown, source). Cached on the incident row; one Gemini call per incident."""
    if not force:
        cached = conn.execute(
            "SELECT REPORT, REPORT_SOURCE FROM TRUSTLAYER.INCIDENTS WHERE INCIDENT_ID = {i}",
            {"i": incident_id}).fetchone()
        if cached and cached[0]:
            return cached[0], cached[1]

    evidence = gather_evidence(conn, incident_id)
    try:
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY not set")
        text, source = _gemini(PROMPT.format(evidence=json.dumps(evidence, indent=1, default=str)))
    except Exception as exc:  # noqa: BLE001 - quota, network or config: never break the pipeline
        text, source = template_report(evidence), "template"
        print(f"  Gemini unavailable ({str(exc).splitlines()[0][:120]}); used template report")

    conn.execute(
        "UPDATE TRUSTLAYER.INCIDENTS SET REPORT = {r}, REPORT_SOURCE = {s} WHERE INCIDENT_ID = {i}",
        {"r": text[:100000], "s": source, "i": incident_id})
    return text, source
