"""Learn what "normal" looks like for a table from its published history.

Hourly metrics are grouped by hour of the week (Monday 09:00 is compared with past
Mondays at 09:00) and summarised by a Python UDF running inside Exasol, so the
history never leaves the database.
"""
import inspect
import statistics
from datetime import datetime, timedelta

from trustlayer import robust
from trustlayer.schema import TRIPS

HISTORY_DAYS = 42  # hour-of-week patterns: six samples of each hour
RATE_DAYS = 14  # quality rates drift faster, so use a shorter window

# Columns whose emptiness we track. Missing values here break downstream reports.
NULL_CHECK_COLUMNS = [
    "PASSENGER_COUNT", "TRIP_DISTANCE", "PULOCATIONID", "DOLOCATIONID",
    "PAYMENT_TYPE", "FARE_AMOUNT", "TIP_AMOUNT", "TOTAL_AMOUNT",
]
DUPLICATE_KEY = [
    "VENDORID", "TPEP_PICKUP_DATETIME", "TPEP_DROPOFF_DATETIME",
    "PULOCATIONID", "DOLOCATIONID", "TOTAL_AMOUNT",
]
INVALID_ROW = (
    "TOTAL_AMOUNT < 0 OR TRIP_DISTANCE < 0 OR TPEP_DROPOFF_DATETIME < TPEP_PICKUP_DATETIME"
)
# 2024-01-01 was a Monday, so this gives Monday 00:00 = 0 ... Sunday 23:00 = 167.
HOUR_OF_WEEK_SQL = (
    "MOD(DAYS_BETWEEN(TRUNC({ts}), DATE '2024-01-01'), 7) * 24 + HOUR({ts})"
)

# An emitting UDF must be alone in its SELECT, so the group keys pass through it.
UDF_TEMPLATE = """CREATE OR REPLACE PYTHON3 SET SCRIPT TRUSTLAYER.ROBUST_BASELINE(
    METRIC VARCHAR(128), HOUR_OF_WEEK DECIMAL(4,0), VAL DOUBLE)
EMITS (METRIC VARCHAR(128), HOUR_OF_WEEK DECIMAL(4,0), CENTER DOUBLE, SCALE DOUBLE, N_OBS DECIMAL(9,0)) AS
{source}

def run(ctx):
    metric, how = ctx.METRIC, ctx.HOUR_OF_WEEK
    vals = []
    while True:
        if ctx.VAL is not None:
            vals.append(ctx.VAL)
        if not ctx.next():
            break
    center, scale = robust_center_scale(vals)
    ctx.emit(metric, how, center, scale, len(vals))
/
"""


def hour_of_week(ts) -> int:
    return ts.weekday() * 24 + ts.hour


def install_udf(conn) -> bool:
    """Create the baseline UDF from trustlayer/robust.py. False if Python UDFs are unavailable."""
    try:
        conn.execute(UDF_TEMPLATE.format(source=inspect.getsource(robust)))
        conn.execute("SELECT TRUSTLAYER.ROBUST_BASELINE('probe', 0, 1) FROM DUAL")
        return True
    except Exception as exc:  # noqa: BLE001 - fall back to SQL when no Python container
        print(f"  Python UDF unavailable, using SQL fallback: {str(exc).splitlines()[0][:160]}")
        return False


def _hourly_metrics_sql(table: str, since: str) -> str:
    hr = "TRUNC(TPEP_PICKUP_DATETIME, 'HH')"
    how = HOUR_OF_WEEK_SQL.format(ts=hr)
    recent = f"FROM {table} WHERE TPEP_PICKUP_DATETIME >= '{since}' GROUP BY {hr}"
    return f"""
        SELECT METRIC, HOUR_OF_WEEK, VAL FROM (
            SELECT 'ROW_COUNT' AS METRIC, {how} AS HOUR_OF_WEEK, CAST(COUNT(*) AS DOUBLE) AS VAL {recent}
            UNION ALL
            SELECT 'AVG_TOTAL_AMOUNT', {how}, AVG(TOTAL_AMOUNT) {recent}
        )"""


def _days_before_latest(conn, table: str, days: int) -> str:
    latest = conn.execute(f"SELECT MAX(TPEP_PICKUP_DATETIME) FROM {table}").fetchval()
    return str(datetime.fromisoformat(str(latest)[:19]) - timedelta(days=days))


def learn(conn, table: str = TRIPS) -> str:
    """Rebuild TRUSTLAYER.BASELINE for a table from its recent history. Returns the method used.

    Slots: volume and average fare use hour of week (0-167) over the last 6 weeks;
    missing-value and invalid-row rates use hour of day (0-23) over the last 2 weeks,
    because they drift faster; the duplicate rate and volume level use slot -1.
    """
    conn.execute("DELETE FROM TRUSTLAYER.BASELINE WHERE TABLE_NAME = {t}", {"t": table})
    hourly = _hourly_metrics_sql(table, _days_before_latest(conn, table, HISTORY_DAYS))
    if install_udf(conn):
        method = "python_udf_median_mad"
        summary = f"""
            SELECT TRUSTLAYER.ROBUST_BASELINE(METRIC, HOUR_OF_WEEK, VAL)
            FROM ({hourly}) GROUP BY METRIC, HOUR_OF_WEEK"""
    else:
        method = "sql_median_stddev"
        summary = f"""
            SELECT METRIC, HOUR_OF_WEEK, MEDIAN(VAL) AS CENTER,
                   GREATEST(NVL(STDDEV(VAL), 0), 0.05 * ABS(MEDIAN(VAL)), 1e-9) AS SCALE,
                   COUNT(VAL) AS N_OBS
            FROM ({hourly}) GROUP BY METRIC, HOUR_OF_WEEK"""
    conn.execute(f"""
        INSERT INTO TRUSTLAYER.BASELINE
        SELECT {{t}}, METRIC, HOUR_OF_WEEK, CENTER, SCALE, N_OBS, {{m}}, CURRENT_TIMESTAMP
        FROM ({summary})""", {"t": table, "m": method})

    since = _days_before_latest(conn, table, RATE_DAYS)
    nulls = ", ".join(
        f"AVG(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS \"NULL_RATE:{c}\"" for c in NULL_CHECK_COLUMNS
    )
    stmt = conn.execute(f"""
        SELECT HOUR(TPEP_PICKUP_DATETIME) AS HOUR_OF_DAY, COUNT(*) AS N, {nulls},
               AVG(CASE WHEN {INVALID_ROW} THEN 1 ELSE 0 END) AS INVALID_RATE
        FROM {table} WHERE TPEP_PICKUP_DATETIME >= {{since}}
        GROUP BY HOUR(TPEP_PICKUP_DATETIME)""", {"since": since})
    rows = []
    for rec in stmt.fetchall():
        rec = dict(zip(stmt.column_names(), rec))
        hour, n = int(rec.pop("HOUR_OF_DAY")), rec.pop("N")
        rows += [(table, metric, hour, float(v or 0), None, n, "sql_rate") for metric, v in rec.items()]

    total, distinct = conn.execute(f"""
        SELECT COUNT(*), (SELECT COUNT(*) FROM (SELECT DISTINCT {', '.join(DUPLICATE_KEY)}
                          FROM {table} WHERE TPEP_PICKUP_DATETIME >= {{since}}))
        FROM {table} WHERE TPEP_PICKUP_DATETIME >= {{since}}""", {"since": since}).fetchone()
    rows.append((table, "DUPLICATE_RATE", -1, (total - distinct) / total if total else 0.0, None, total, "sql_rate"))

    # Starting traffic level: last week's volume relative to the hour-of-week baseline.
    base = load(conn, table)
    last_week = conn.execute(f"""
        SELECT TRUNC(TPEP_PICKUP_DATETIME, 'HH'), COUNT(*) FROM {table}
        WHERE TPEP_PICKUP_DATETIME >= {{since}} GROUP BY TRUNC(TPEP_PICKUP_DATETIME, 'HH')""",
        {"since": _days_before_latest(conn, table, 7)}).fetchall()
    level = _level_from(base, [(datetime.fromisoformat(str(h)[:19]), n) for h, n in last_week])
    rows.append((table, "VOLUME_LEVEL", -1, level, None, len(last_week), "median_ratio"))

    now = str(conn.execute("SELECT CURRENT_TIMESTAMP").fetchval())[:19]
    conn.import_from_iterable([(*r, now) for r in rows], ("TRUSTLAYER", "BASELINE"))
    return method


def _level_from(base: dict, hourly_counts: list[tuple[datetime, int]]) -> float:
    """Median of observed / expected volume. 1.1 means traffic is running 10% above baseline."""
    ratios = [
        n / base[("ROW_COUNT", hour_of_week(h))][0]
        for h, n in hourly_counts
        if base.get(("ROW_COUNT", hour_of_week(h)), (0,))[0]
    ]
    return statistics.median(ratios) if ratios else 1.0


def volume_level(conn, base: dict, table: str = TRIPS, window: int = 24) -> float:
    """Current traffic level from the last published hourly batches, so seasonal growth
    raises expectations gradually while a sudden collapse still stands out."""
    recent = conn.execute("""
        SELECT BATCH_START, ROW_COUNT FROM TRUSTLAYER.LOAD_LOG
        WHERE TABLE_NAME = {t} AND STATUS = 'PROMOTED' AND BATCH_ID NOT LIKE 'backfill-%'
        ORDER BY BATCH_START DESC LIMIT {w!d}""", {"t": table, "w": window}).fetchall()
    if len(recent) < 6:
        return base.get(("VOLUME_LEVEL", -1), (1.0,))[0]
    return _level_from(base, [(datetime.fromisoformat(str(h)[:19]), int(n)) for h, n in recent])


def load(conn, table: str = TRIPS) -> dict:
    """{(metric, time_slot): (center, scale)} for a table."""
    rows = conn.execute(
        "SELECT METRIC, TIME_SLOT, CENTER, SCALE FROM TRUSTLAYER.BASELINE WHERE TABLE_NAME = {t}",
        {"t": table},
    ).fetchall()
    return {(m, int(h)): (c, s) for m, h, c, s in rows}
