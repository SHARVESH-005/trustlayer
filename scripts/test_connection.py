"""Check that Python can reach Exasol Personal. Run: python scripts/test_connection.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trustlayer.db import connect  # noqa: E402


def main() -> int:
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 - show any connection failure plainly
        print(f"FAILED to connect: {exc}")
        print("Check EXASOL_HOST / PORT / USER / PASSWORD in .env and that Exasol is running.")
        return 1
    one = conn.execute("SELECT 1").fetchval()
    version = conn.execute(
        "SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'"
    ).fetchval()
    print(f"Connected. SELECT 1 -> {one}. Exasol version: {version}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
