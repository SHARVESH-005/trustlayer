"""The quarantine gate: every batch lands in STAGE, is checked inside Exasol, and is
then either published to CURATED or held in QUARANTINE. Dashboards only read CURATED."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trustlayer import baseline, chaos, checks, lineage, rules
from trustlayer.schema import TRIP_COLUMN_LIST, TRIPS

RAW = "RAW.YELLOW_TRIPS"
STAGE = "STAGE.YELLOW_TRIPS"
QUARANTINE = "QUARANTINE.YELLOW_TRIPS"
REPLAY_START = datetime(2024, 3, 4)  # Monday right after the backfilled history


@dataclass
class BatchOutcome:
    batch_id: str
    batch_start: datetime
    status: str
    rows: int
    chaos: str | None
    results: list = field(default_factory=list)
    incident_id: str | None = None
    affected: dict | None = None


def backfill(conn, start: str = "2024-01-01", end: str = "2024-03-04") -> int:
    """Publish trusted history straight to CURATED so baselines have something to learn from."""
    batch_id = f"backfill-{start}-{end}"
    start, end = f"{start} 00:00:00", f"{end} 00:00:00"  # explicit time for TIMESTAMP comparison
    conn.execute(f"DELETE FROM {TRIPS} WHERE BATCH_ID = {{b}}", {"b": batch_id})
    conn.execute(f"""
        INSERT INTO {TRIPS} ({TRIP_COLUMN_LIST}, BATCH_ID, PROMOTED_AT)
        SELECT {TRIP_COLUMN_LIST}, {{b}}, CURRENT_TIMESTAMP FROM {RAW}
        WHERE TPEP_PICKUP_DATETIME >= {{s}} AND TPEP_PICKUP_DATETIME < {{e}}""",
        {"b": batch_id, "s": start, "e": end})
    rows = conn.execute(f"SELECT COUNT(*) FROM {TRIPS} WHERE BATCH_ID = {{b}}", {"b": batch_id}).fetchval()
    conn.execute("""
        INSERT INTO TRUSTLAYER.LOAD_LOG (BATCH_ID, TABLE_NAME, SOURCE_URL, BATCH_START, BATCH_END,
            ROW_COUNT, STATUS, STARTED_AT, FINISHED_AT, MESSAGE)
        VALUES ({b}, {t}, {src}, {s}, {e}, {n}, 'PROMOTED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
            'historical backfill')""",
        {"b": batch_id, "t": TRIPS, "src": RAW, "s": start, "e": end, "n": rows})
    return rows


def next_batch_hour(conn) -> datetime:
    last = conn.execute(
        "SELECT MAX(BATCH_START) FROM TRUSTLAYER.LOAD_LOG WHERE TABLE_NAME = {t} AND BATCH_ID NOT LIKE 'backfill-%'",
        {"t": TRIPS},
    ).fetchval()
    if not last:
        return REPLAY_START
    return datetime.fromisoformat(str(last)[:19]) + timedelta(hours=1)


def _db_now(conn) -> str:
    return str(conn.execute("SELECT CURRENT_TIMESTAMP").fetchval())[:19]


def run_batch(conn, batch_start: datetime | None = None, scenario: str | None = None) -> BatchOutcome:
    batch_start = batch_start or next_batch_hour(conn)
    batch_end = batch_start + timedelta(hours=1)
    batch_id = f"{batch_start:%Y%m%d%H}-{uuid.uuid4().hex[:6]}"
    params = {"b": batch_id, "t": TRIPS, "s": batch_start.isoformat(sep=" "), "e": batch_end.isoformat(sep=" ")}

    # 1. Land the batch in STAGE (the pipeline's normal hourly delivery).
    conn.execute("""
        INSERT INTO TRUSTLAYER.LOAD_LOG (BATCH_ID, TABLE_NAME, SOURCE_URL, BATCH_START, BATCH_END,
            STATUS, CHAOS, STARTED_AT)
        VALUES ({b}, {t}, 'RAW.YELLOW_TRIPS', {s}, {e}, 'STAGED', {c}, CURRENT_TIMESTAMP)""",
        {**params, "c": scenario})
    try:
        conn.execute(f"""
            INSERT INTO {STAGE} ({TRIP_COLUMN_LIST}, BATCH_ID)
            SELECT {TRIP_COLUMN_LIST}, {{b}} FROM {RAW}
            WHERE TPEP_PICKUP_DATETIME >= {{s}} AND TPEP_PICKUP_DATETIME < {{e}}""", params)
        if scenario:
            chaos.inject(conn, batch_id, scenario)

        # 2. Check it against the learned baseline.
        prof = checks.profile_batch(conn, batch_id)
        base = baseline.load(conn)
        results = checks.evaluate(prof, base, batch_start, baseline.volume_level(conn, base))
        checked_at = _db_now(conn)
        conn.import_from_iterable(
            [(batch_id, TRIPS, r.check, r.column, r.status, r.observed, r.expected, r.details[:2000], checked_at)
             for r in results],
            ("TRUSTLAYER", "CHECK_RESULTS"),
        )
    except Exception as exc:
        # A crashed run must not leave half a batch behind or look like it is still running.
        conn.execute(f"DELETE FROM {STAGE} WHERE BATCH_ID = {{b}}", params)
        conn.execute("""
            UPDATE TRUSTLAYER.LOAD_LOG SET STATUS = 'FAILED', FINISHED_AT = CURRENT_TIMESTAMP, MESSAGE = {m}
            WHERE BATCH_ID = {b}""", {**params, "m": str(exc)[:2000]})
        raise

    # 3. Gate: publish or quarantine, atomically.
    failed = [r for r in results if r.status == rules.FAIL]
    rows = int(prof["ROW_COUNT"] or 0)
    outcome = BatchOutcome(batch_id, batch_start, "QUARANTINED" if failed else "PROMOTED", rows, scenario, results)
    reason = "; ".join(f"{r.check}{'(' + r.column + ')' if r.column else ''}: {r.details}" for r in failed)
    conn.set_autocommit(False)
    try:
        if failed:
            conn.execute(f"""
                INSERT INTO {QUARANTINE} ({TRIP_COLUMN_LIST}, BATCH_ID, QUARANTINED_AT, REASON)
                SELECT {TRIP_COLUMN_LIST}, BATCH_ID, CURRENT_TIMESTAMP, {{r}} FROM {STAGE} WHERE BATCH_ID = {{b}}""",
                {**params, "r": reason[:2000]})
        else:
            conn.execute(f"""
                INSERT INTO {TRIPS} ({TRIP_COLUMN_LIST}, BATCH_ID, PROMOTED_AT)
                SELECT {TRIP_COLUMN_LIST}, BATCH_ID, CURRENT_TIMESTAMP FROM {STAGE} WHERE BATCH_ID = {{b}}""",
                params)
        conn.execute(f"DELETE FROM {STAGE} WHERE BATCH_ID = {{b}}", params)
        conn.execute("""
            UPDATE TRUSTLAYER.LOAD_LOG
            SET STATUS = {st}, ROW_COUNT = {n}, FINISHED_AT = CURRENT_TIMESTAMP, MESSAGE = {m}
            WHERE BATCH_ID = {b}""",
            {**params, "st": outcome.status, "n": rows, "m": reason[:2000] or None})
        if failed:
            outcome.incident_id = f"INC-{batch_id}"
            checks_failed = ", ".join(sorted({r.check for r in failed}))
            conn.execute("""
                INSERT INTO TRUSTLAYER.INCIDENTS (INCIDENT_ID, BATCH_ID, TABLE_NAME, SEVERITY, TITLE,
                    STATUS, ROWS_QUARANTINED, OPENED_AT)
                VALUES ({i}, {b}, {t}, {sev}, {title}, 'OPEN', {n}, CURRENT_TIMESTAMP)""",
                {**params, "i": outcome.incident_id, "n": rows,
                 "sev": "HIGH" if len(failed) > 1 else "MEDIUM",
                 "title": f"{batch_start:%Y-%m-%d %H:00} batch blocked: {checks_failed} failed"})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.set_autocommit(True)

    if failed:
        outcome.affected = lineage.affected(conn, TRIPS)
    return outcome
