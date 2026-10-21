"""Exasol connection helper shared by ingest, checks and the dashboard."""
import os
import ssl
from pathlib import Path

import pyexasol
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def connect(**kwargs) -> pyexasol.ExaConnection:
    host = os.getenv("EXASOL_HOST", "localhost")
    port = os.getenv("EXASOL_PORT", "8563")
    sslopt = None
    if not _flag("EXASOL_VERIFY_CERT", "false"):
        sslopt = {"cert_reqs": ssl.CERT_NONE}
    return pyexasol.connect(
        dsn=f"{host}:{port}",
        user=os.getenv("EXASOL_USER", "sys"),
        password=os.getenv("EXASOL_PASSWORD", ""),
        encryption=_flag("EXASOL_ENCRYPTION", "true"),
        websocket_sslopt=sslopt,
        compression=True,
        **kwargs,
    )


def run_sql_file(conn: pyexasol.ExaConnection, path: Path) -> None:
    """Run a file of ';'-separated statements, skipping '--' comment lines."""
    text = "\n".join(
        line for line in path.read_text().splitlines() if not line.strip().startswith("--")
    )
    for stmt in text.split(";"):
        if stmt.strip():
            conn.execute(stmt)
