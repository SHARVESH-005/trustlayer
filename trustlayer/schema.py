"""Table definitions. Trip tables share one column list so RAW, STAGE, CURATED and
QUARANTINE can never drift apart."""
from pathlib import Path

from trustlayer.db import ROOT, run_sql_file

TRIPS = "CURATED.YELLOW_TRIPS"

TRIP_COLUMNS = [
    ("VENDORID", "DECIMAL(5,0)"),
    ("TPEP_PICKUP_DATETIME", "TIMESTAMP"),
    ("TPEP_DROPOFF_DATETIME", "TIMESTAMP"),
    ("PASSENGER_COUNT", "DECIMAL(5,0)"),
    ("TRIP_DISTANCE", "DOUBLE"),
    ("RATECODEID", "DECIMAL(5,0)"),
    ("STORE_AND_FWD_FLAG", "VARCHAR(1)"),
    ("PULOCATIONID", "DECIMAL(5,0)"),
    ("DOLOCATIONID", "DECIMAL(5,0)"),
    ("PAYMENT_TYPE", "DECIMAL(5,0)"),
    ("FARE_AMOUNT", "DOUBLE"),
    ("EXTRA", "DOUBLE"),
    ("MTA_TAX", "DOUBLE"),
    ("TIP_AMOUNT", "DOUBLE"),
    ("TOLLS_AMOUNT", "DOUBLE"),
    ("IMPROVEMENT_SURCHARGE", "DOUBLE"),
    ("TOTAL_AMOUNT", "DOUBLE"),
    ("CONGESTION_SURCHARGE", "DOUBLE"),
    ("AIRPORT_FEE", "DOUBLE"),
]
TRIP_COLUMN_NAMES = [name for name, _ in TRIP_COLUMNS]
TRIP_COLUMN_LIST = ", ".join(TRIP_COLUMN_NAMES)

# Extra columns per trip table, after the shared trip columns.
TRIP_TABLES = {
    "RAW.YELLOW_TRIPS": [("LOAD_ID", "VARCHAR(64)"), ("LOADED_AT", "TIMESTAMP")],
    "STAGE.YELLOW_TRIPS": [("BATCH_ID", "VARCHAR(64)")],
    "CURATED.YELLOW_TRIPS": [("BATCH_ID", "VARCHAR(64)"), ("PROMOTED_AT", "TIMESTAMP")],
    "QUARANTINE.YELLOW_TRIPS": [
        ("BATCH_ID", "VARCHAR(64)"),
        ("QUARANTINED_AT", "TIMESTAMP"),
        ("REASON", "VARCHAR(2000)"),
    ],
}

PIPELINE_SCHEMAS = ["STAGE", "CURATED", "QUARANTINE", "MART", "TRUSTLAYER"]

CONTROL_TABLES = """
CREATE TABLE IF NOT EXISTS TRUSTLAYER.LOAD_LOG (
    BATCH_ID     VARCHAR(64),
    TABLE_NAME   VARCHAR(128),
    SOURCE_URL   VARCHAR(256),
    BATCH_START  TIMESTAMP,
    BATCH_END    TIMESTAMP,
    ROW_COUNT    DECIMAL(18,0),
    STATUS       VARCHAR(16),
    CHAOS        VARCHAR(64),
    STARTED_AT   TIMESTAMP,
    FINISHED_AT  TIMESTAMP,
    MESSAGE      VARCHAR(2000)
);
CREATE TABLE IF NOT EXISTS TRUSTLAYER.BASELINE (
    TABLE_NAME    VARCHAR(128),
    METRIC        VARCHAR(128),
    TIME_SLOT     DECIMAL(4,0),
    CENTER        DOUBLE,
    SCALE         DOUBLE,
    N_OBS         DECIMAL(9,0),
    BASELINE_METHOD VARCHAR(32),
    COMPUTED_AT   TIMESTAMP
);
CREATE TABLE IF NOT EXISTS TRUSTLAYER.CHECK_RESULTS (
    BATCH_ID     VARCHAR(64),
    TABLE_NAME   VARCHAR(128),
    CHECK_NAME   VARCHAR(64),
    COLUMN_NAME  VARCHAR(128),
    STATUS       VARCHAR(8),
    OBSERVED     DOUBLE,
    EXPECTED     DOUBLE,
    DETAILS      VARCHAR(2000),
    CHECKED_AT   TIMESTAMP
);
CREATE TABLE IF NOT EXISTS TRUSTLAYER.INCIDENTS (
    INCIDENT_ID       VARCHAR(64),
    BATCH_ID          VARCHAR(64),
    TABLE_NAME        VARCHAR(128),
    SEVERITY          VARCHAR(16),
    TITLE             VARCHAR(500),
    STATUS            VARCHAR(16),
    ROWS_QUARANTINED  DECIMAL(18,0),
    OPENED_AT         TIMESTAMP,
    RESOLVED_AT       TIMESTAMP,
    REPORT            VARCHAR(100000),
    REPORT_SOURCE     VARCHAR(32)
);
CREATE TABLE IF NOT EXISTS TRUSTLAYER.TABLE_CONFIG (
    TABLE_NAME             VARCHAR(128),
    FRESHNESS_SLA_MINUTES  DECIMAL(9,0)
);
CREATE TABLE IF NOT EXISTS TRUSTLAYER.DASHBOARDS (
    DASHBOARD_NAME  VARCHAR(128),
    OWNER           VARCHAR(128),
    VIEW_SCHEMA     VARCHAR(128),
    VIEW_NAME       VARCHAR(128)
);
"""

# Sample BI dashboards and the mart views they read. Lineage maps a broken table to these.
DASHBOARDS = [
    ("Executive KPIs", "CFO office", "MART", "EXEC_KPIS"),
    ("Daily Revenue", "Finance", "MART", "DAILY_REVENUE"),
    ("Airport Demand", "Operations", "MART", "AIRPORT_DEMAND"),
    ("Payment Mix", "Product", "MART", "PAYMENT_MIX"),
]


def _trip_table_ddl(table: str) -> str:
    cols = TRIP_COLUMNS + TRIP_TABLES[table]
    body = ",\n    ".join(f"{name} {dtype}" for name, dtype in cols)
    return f"CREATE TABLE IF NOT EXISTS {table} (\n    {body}\n)"


def create_all(conn, reset: bool = False, reset_raw: bool = False, freshness_sla_minutes: int = 15) -> None:
    if reset:
        for schema in PIPELINE_SCHEMAS:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    if reset_raw:
        conn.execute("DROP SCHEMA IF EXISTS RAW CASCADE")
    for schema in ["RAW", *PIPELINE_SCHEMAS]:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for table in TRIP_TABLES:
        conn.execute(_trip_table_ddl(table))
    for stmt in CONTROL_TABLES.split(";"):
        if stmt.strip():
            conn.execute(stmt)

    conn.execute("DELETE FROM TRUSTLAYER.TABLE_CONFIG WHERE TABLE_NAME = {t}", {"t": TRIPS})
    conn.execute(
        "INSERT INTO TRUSTLAYER.TABLE_CONFIG VALUES ({t}, {sla})",
        {"t": TRIPS, "sla": freshness_sla_minutes},
    )
    conn.execute("TRUNCATE TABLE TRUSTLAYER.DASHBOARDS")
    for name, owner, schema, view in DASHBOARDS:
        conn.execute(
            "INSERT INTO TRUSTLAYER.DASHBOARDS VALUES ({n}, {o}, {s}, {v})",
            {"n": name, "o": owner, "s": schema, "v": view},
        )

    sql_dir = Path(ROOT) / "sql"
    run_sql_file(conn, sql_dir / "marts.sql")
    run_sql_file(conn, sql_dir / "trust.sql")
