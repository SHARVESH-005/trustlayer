"""TrustLayer command line.

    python -m trustlayer.cli setup [--reset]
    python -m trustlayer.cli backfill            # publish Jan-Feb 2024 history and learn baselines
    python -m trustlayer.cli run-batch [--chaos duplicates] [--hour "2024-03-04 09:00"] [--report]
    python -m trustlayer.cli report INC-...       # plain-English incident report
    python -m trustlayer.cli retry INC-...        # re-run the blocked hour, resolve if clean
    python -m trustlayer.cli replay --hours 24
    python -m trustlayer.cli status
    python -m trustlayer.cli affected CURATED.YELLOW_TRIPS
"""
import argparse
import json
import time
from datetime import datetime

from trustlayer import baseline, chaos, lineage, pipeline, report
from trustlayer.db import connect
from trustlayer.schema import TRIPS, create_all

ICON = {"PASS": "ok  ", "WARN": "WARN", "FAIL": "FAIL"}


def print_outcome(o: pipeline.BatchOutcome) -> None:
    tag = f" [chaos: {o.chaos}]" if o.chaos else ""
    print(f"\n{o.batch_start:%Y-%m-%d %H:00}  {o.batch_id}  {o.rows:,} rows{tag}  ->  {o.status}")
    for r in o.results:
        if r.status != "PASS":
            col = f"({r.column})" if r.column else ""
            print(f"   {ICON[r.status]} {r.check}{col}: {r.details}")
    if o.incident_id:
        print(f"   incident {o.incident_id} opened")
    if o.affected:
        names = ", ".join(f"{d['dashboard']} ({d['owner']})" for d in o.affected["dashboards"])
        print(f"   protected dashboards: {names}")


def cmd_setup(conn, args):
    create_all(conn, reset=args.reset, freshness_sla_minutes=args.sla)
    print("Schemas, control tables, marts and trust views are ready.")


def cmd_backfill(conn, args):
    t0 = time.perf_counter()
    rows = pipeline.backfill(conn, args.start, args.end)
    print(f"Published {rows:,} historical rows to {TRIPS} in {time.perf_counter() - t0:.1f}s")
    t0 = time.perf_counter()
    method = baseline.learn(conn)
    print(f"Learned baselines ({method}) in {time.perf_counter() - t0:.1f}s")


def cmd_run_batch(conn, args):
    hour = datetime.fromisoformat(args.hour) if args.hour else None
    outcome = pipeline.run_batch(conn, hour, args.chaos)
    print_outcome(outcome)
    if outcome.incident_id and args.report:
        text, source = report.generate(conn, outcome.incident_id)
        print(f"\n--- incident report ({source}) ---\n{text}")


def cmd_report(conn, args):
    text, source = report.generate(conn, args.incident, force=args.force)
    print(f"--- {args.incident} ({source}) ---\n{text}")


def cmd_retry(conn, args):
    outcome = pipeline.retry(conn, args.incident)
    print_outcome(outcome)
    print(f"\n{args.incident} {'resolved' if outcome.status == 'PROMOTED' else 'still open'}")


def cmd_replay(conn, args):
    t0 = time.perf_counter()
    outcomes = [pipeline.run_batch(conn) for _ in range(args.hours)]
    for o in outcomes:
        print_outcome(o)
    blocked = sum(o.status == "QUARANTINED" for o in outcomes)
    print(f"\n{len(outcomes)} batches in {time.perf_counter() - t0:.1f}s, {blocked} quarantined")


def cmd_status(conn, args):
    stmt = conn.execute("SELECT * FROM TRUSTLAYER.TRUST_SCORES")
    for row in stmt.fetchall():
        print(json.dumps(dict(zip(stmt.column_names(), row)), default=str, indent=2))
    print("\nRecent batches:")
    for row in conn.execute("""
        SELECT l.BATCH_START, l.BATCH_ID, l.ROW_COUNT, l.STATUS, l.CHAOS, h.HEALTH_SCORE
        FROM TRUSTLAYER.LOAD_LOG l LEFT JOIN TRUSTLAYER.BATCH_HEALTH h ON h.BATCH_ID = l.BATCH_ID
        ORDER BY l.STARTED_AT DESC LIMIT 10""").fetchall():
        print("  ", *row)


def cmd_affected(conn, args):
    print(json.dumps(lineage.affected(conn, args.table.upper()), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustLayer: data reliability on Exasol")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--reset", action="store_true", help="drop and recreate pipeline schemas (keeps RAW)")
    p.add_argument("--sla", type=int, default=15, help="freshness SLA in minutes")
    p = sub.add_parser("backfill")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-03-04")
    p = sub.add_parser("run-batch")
    p.add_argument("--hour", help='batch hour, e.g. "2024-03-04 09:00"; default: next hour')
    p.add_argument("--chaos", choices=sorted(chaos.SCENARIOS))
    p.add_argument("--report", action="store_true", help="write an incident report if the batch is blocked")
    p = sub.add_parser("report", help="incident report (Gemini, cached)")
    p.add_argument("incident")
    p.add_argument("--force", action="store_true", help="regenerate even if cached")
    p = sub.add_parser("retry", help="re-run a blocked hour from source and resolve its incident")
    p.add_argument("incident")
    p = sub.add_parser("replay")
    p.add_argument("--hours", type=int, default=24)
    sub.add_parser("status")
    p = sub.add_parser("affected")
    p.add_argument("table", nargs="?", default=TRIPS)
    args = parser.parse_args()

    conn = connect()
    try:
        globals()[f"cmd_{args.cmd.replace('-', '_')}"](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
