"""One command to a ready demo.

    python demo.py                      # load data if needed, rebuild, replay 12 h, open the dashboard
    python demo.py --break unit_change  # also inject one failure before opening the dashboard
    python demo.py --no-dashboard       # prepare only
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from trustlayer import baseline, chaos, pipeline, report  # noqa: E402
from trustlayer.cli import print_outcome  # noqa: E402
from trustlayer.db import connect  # noqa: E402
from trustlayer.schema import create_all  # noqa: E402

FULL_RAW_ROWS = 9_000_000  # three months of trips


def step(title: str):
    print(f"\n== {title}")
    return time.perf_counter()


def done(t0: float, note: str = "") -> None:
    print(f"   done in {time.perf_counter() - t0:.1f}s {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=12, help="clean hours to replay (default 12)")
    parser.add_argument("--break", dest="scenario", choices=sorted(chaos.SCENARIOS),
                        help="inject one failure after the replay")
    parser.add_argument("--reload-data", action="store_true", help="re-download and reload RAW")
    parser.add_argument("--sla", type=int, default=120,
                        help="freshness SLA in minutes (long by default so pauses while presenting don't count)")
    parser.add_argument("--no-dashboard", action="store_true")
    args = parser.parse_args()

    t0 = step("Connecting to Exasol Personal")
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 - explain the usual fix instead of a traceback
        print(f"   cannot connect: {str(exc).strip().splitlines()[0]}")
        print("   Start Exasol (`exasol start` in WSL/Linux) and check .env against `exasol info`.")
        return 1
    version = conn.execute(
        "SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'").fetchval()
    done(t0, f"(Exasol {version})")

    create_all(conn)
    raw_rows = conn.execute("SELECT COUNT(*) FROM RAW.YELLOW_TRIPS").fetchval()
    if args.reload_data or raw_rows < FULL_RAW_ROWS:
        t0 = step("Landing NYC taxi trips Jan-Mar 2024 in RAW (first run downloads ~150 MB)")
        conn.close()
        subprocess.run([sys.executable, str(ROOT / "ingest" / "load_nyc_taxi.py"), "--reset-raw"], check=True)
        conn = connect()
        done(t0)
    else:
        print(f"\n== RAW already holds {raw_rows:,} trips, skipping download")

    t0 = step("Rebuilding pipeline schemas, marts, dashboards registry and trust views")
    create_all(conn, reset=True, freshness_sla_minutes=args.sla)
    done(t0)

    t0 = step("Publishing history (Jan 1 - Mar 3) to CURATED")
    rows = pipeline.backfill(conn)
    done(t0, f"({rows:,} rows)")

    t0 = step("Learning baselines inside Exasol")
    method = baseline.learn(conn)
    done(t0, f"({method})")

    t0 = step(f"Replaying {args.hours} clean hourly batches through the quarantine gate")
    outcomes = [pipeline.run_batch(conn) for _ in range(args.hours)]
    blocked = sum(o.status == "QUARANTINED" for o in outcomes)
    done(t0, f"({blocked} quarantined)")

    if args.scenario:
        step(f"Injecting failure: {args.scenario} ({chaos.SCENARIOS[args.scenario][0]})")
        outcome = pipeline.run_batch(conn, scenario=args.scenario)
        print_outcome(outcome)
        if outcome.incident_id:
            text, source = report.generate(conn, outcome.incident_id)
            print(f"\n--- incident report ({source}) ---\n{text}")

    score = conn.execute("SELECT TRUST_SCORE FROM TRUSTLAYER.TRUST_SCORES").fetchval()
    print(f"\nTrust score now: {float(score):.0f}/100")
    conn.close()

    if args.no_dashboard:
        print("\nReady. Start the dashboard with: streamlit run app/dashboard.py")
        return 0
    print("\nOpening the dashboard at http://localhost:8501 (Ctrl+C to stop)")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "dashboard.py")])


if __name__ == "__main__":
    sys.exit(main())
