"""Download NYC TLC yellow taxi months and land them in RAW.YELLOW_TRIPS.

Example:
    python ingest/load_nyc_taxi.py --months 2024-01 2024-02 2024-03
"""
import argparse
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trustlayer.db import connect  # noqa: E402
from trustlayer.schema import TRIP_COLUMN_NAMES, create_all  # noqa: E402

DATA_DIR = ROOT / "data"
URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"
CHUNK_ROWS = 500_000
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


def chunks(path: Path, limit: int | None, load_id: str):
    """Yield the file in 500k-row DataFrames so a 3M-row month fits in a laptop's memory."""
    remaining = limit
    for batch in pq.ParquetFile(path).iter_batches(batch_size=CHUNK_ROWS):
        df = prepare(batch.to_pandas(), load_id)
        if remaining is not None:
            df = df.head(remaining)
            remaining -= len(df)
        yield df
        if remaining is not None and remaining <= 0:
            return


def prepare(df: pd.DataFrame, load_id: str) -> pd.DataFrame:
    df.columns = [c.upper() for c in df.columns]
    df = df.reindex(columns=TRIP_COLUMN_NAMES)  # newer files add columns we ignore
    # Nullable ints so CSV export writes "1", not "1.0", for DECIMAL(5,0) columns.
    for col in INT_COLUMNS:
        df[col] = df[col].round().astype("Int64")
    df["LOAD_ID"] = load_id
    df["LOADED_AT"] = datetime.now()
    return df


def load_month(conn, month: str, limit: int | None) -> None:
    load_id = f"raw-{month}-{uuid.uuid4().hex[:6]}"
    source = URL.format(month=month)
    t0 = time.perf_counter()
    try:
        rows = 0
        for df in chunks(download(month), limit, load_id):
            conn.import_from_pandas(df, ("RAW", "YELLOW_TRIPS"))
            rows += len(df)
        status, message = "LANDED", None
        print(f"  landed {rows:,} rows as {load_id} in {time.perf_counter() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001 - record any failure in the load log
        status, rows, message = "FAILED", 0, str(exc)[:2000]
        print(f"  FAILED: {exc}")
    conn.execute("""
        INSERT INTO TRUSTLAYER.LOAD_LOG (BATCH_ID, TABLE_NAME, SOURCE_URL, ROW_COUNT, STATUS,
            STARTED_AT, FINISHED_AT, MESSAGE)
        VALUES ({b}, 'RAW.YELLOW_TRIPS', {src}, {n}, {st}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, {m})""",
        {"b": load_id, "src": source, "n": rows, "st": status, "m": message})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", nargs="+", default=["2024-01", "2024-02", "2024-03"])
    parser.add_argument("--limit", type=int, default=None, help="max rows per month (for quick tests)")
    parser.add_argument("--reset-raw", action="store_true", help="drop RAW before loading")
    args = parser.parse_args()

    conn = connect()
    create_all(conn, reset_raw=args.reset_raw)
    for month in args.months:
        print(f"Month {month}")
        load_month(conn, month, args.limit)
    total = conn.execute("SELECT COUNT(*) FROM RAW.YELLOW_TRIPS").fetchval()
    print(f"RAW.YELLOW_TRIPS now has {total:,} rows")
    conn.close()


if __name__ == "__main__":
    main()
