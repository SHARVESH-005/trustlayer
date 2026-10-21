"""Live trust badge any dashboard can embed as an image.

    python -m trustlayer.badge            # http://localhost:8765/badge.svg
    <img src="http://localhost:8765/badge.svg?table=CURATED.YELLOW_TRIPS">
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

from trustlayer.db import connect
from trustlayer.schema import TRIPS


def render(score: float | None, detail: str) -> str:
    if score is None:
        color, value = "#8c959f", "unknown"
    else:
        color = "#1a7f37" if score >= 90 else "#bf8700" if score >= 60 else "#cf222e"
        value = f"{score:.0f}/100"
    label, value, detail = "data trust", escape(value), escape(detail)
    lw, vw = 74, 8 * len(value) + 14
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img"
     aria-label="{label}: {value}"><title>{label}: {value} ({detail})</title>
  <rect width="{lw}" height="20" rx="3" fill="#555"/>
  <rect x="{lw}" width="{vw}" height="20" rx="3" fill="{color}"/>
  <rect x="{lw}" width="4" height="20" fill="{color}"/>
  <g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{value}</text>
  </g></svg>"""


def lookup(table: str) -> tuple[float | None, str]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT TRUST_SCORE, MISSING_HOURS, OPEN_INCIDENTS FROM TRUSTLAYER.TRUST_SCORES WHERE TABLE_NAME = {t}",
            {"t": table}).fetchone()
    finally:
        conn.close()
    if not row:
        return None, f"{table} not monitored"
    return float(row[0]), f"{int(row[1])} missing hours, {int(row[2])} open incidents"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server naming
        url = urlparse(self.path)
        if url.path != "/badge.svg":
            self.send_error(404)
            return
        table = parse_qs(url.query).get("table", [TRIPS])[0].upper()
        try:
            body = render(*lookup(table))
        except Exception as exc:  # noqa: BLE001 - a badge should degrade, not crash
            body = render(None, f"error: {str(exc)[:80]}")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the TrustLayer trust badge")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Trust badge at http://localhost:{args.port}/badge.svg")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
