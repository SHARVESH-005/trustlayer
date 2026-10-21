"""Download NYC TLC yellow taxi months and load them into RAW.YELLOW_TRIPS.

Example:
    python ingest/load_nyc_taxi.py --months 2024-01 2024-02 --limit 500000
"""
import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trustlayer.db import connect, run_sql_file  # noqa: E402

DATA_DIR = ROOT / "data"
URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"

# Columns kept, in table order. Newer files add columns we ignore.
COLUMNS = [
    "VENDORID", "TPEP_PICKUP_DATETIME", "TPEP_DROPOFF_DATETIME", "PASSENGER_COUNT",
    "TRIP_DISTANCE", "RATECODEID", "STORE_AND_FWD_FLAG", "PULOCATIONID", "DOLOCATIONID",
    "PAYMENT_TYPE", "FARE_AMOUNT", "EXTRA", "MTA_TAX", "TIP_AMOUNT", "TOLLS_AMOUNT",
    "IMPROVEMENT_SURCHARGE", "TOTAL_AMOUNT", "CONGESTION_SURCHARGE", "AIRPORT_FEE",
]
INT_COLUMNS = ["VENDORID", "PASSENGER_COUNT", "RATECODEID", "PULOCATIONID", "DOLOCATIONID", "PAYMENT_TYPE"]


def download(month: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"yellow_tripdata_{month}.parquet"
    if path.exists():
        print(f"  cached {path.name}")
        return path
    print(f"  downloading {month} ...")
    with requests.get(URL.format(month=month), stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    return path


def prepare(path: Path, limit: int | None, load_id: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [c.upper() for c in df.columns]
    df = df.reindex(columns=COLUMNS)
    if limit:
        df = df.head(limit)
    # Nullable ints so CSV export writes "1", not "1.0", for DECIMAL(5,0) columns.
    for col in INT_COLUMNS:
        df[col] = df[col].round().astype("Int64")
    df["LOAD_ID"] = load_id
    df["LOADED_AT"] = datetime.now()
    return df


def load_month(conn, month: str, limit: int | None) -> None:
    load_id = f"{month}-{uuid.uuid4().hex[:8]}"
    started = datetime.now()
    source = URL.format(month=month)
    try:
        df = prepare(download(month), limit, load_id)
        conn.import_from_pandas(df, ("RAW", "YELLOW_TRIPS"))
        status, rows, message = "SUCCESS", len(df), ""
        print(f"  loaded {rows:,} rows as {load_id}")
    except Exception as exc:  # noqa: BLE001 - record any failure in the load log
        status, rows, message = "FAILED", 0, str(exc)[:2000]
        print(f"  FAILED: {exc}")
    conn.execute(
        "INSERT INTO TRUSTLAYER.LOAD_LOG VALUES "
        "({load_id}, 'RAW.YELLOW_TRIPS', {source}, {rows}, {status}, {started}, {finished}, {message})",
        {
            "load_id": load_id, "source": source, "rows": rows, "status": status,
            "started": started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": message,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", nargs="+", default=["2024-01", "2024-02", "2024-03"])
    parser.add_argument("--limit", type=int, default=None, help="max rows per month (for quick tests)")
    args = parser.parse_args()

    conn = connect()
    run_sql_file(conn, ROOT / "sql" / "00_schemas.sql")
    for month in args.months:
        print(f"Month {month}")
        load_month(conn, month, args.limit)
    total = conn.execute("SELECT COUNT(*) FROM RAW.YELLOW_TRIPS").fetchval()
    print(f"RAW.YELLOW_TRIPS now has {total:,} rows")
    conn.close()


if __name__ == "__main__":
    main()
