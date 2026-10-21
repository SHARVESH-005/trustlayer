# TrustLayer

**Catch broken data pipelines before the business sees a wrong dashboard.**
Built on **Exasol Personal** for ExaThon India 2026 — Track 04: *The Work Behind the Work*.

## Problem

Data teams usually learn a pipeline failed overnight when a business user complains
about a dashboard. By then trust in the data is already lost. Checks live in scattered
scripts, alerts are missing, and nobody can say whether a table is safe to use.

## Solution

TrustLayer runs data-reliability checks **inside Exasol** and turns them into:

- **Alerts** — stale tables, missing/duplicate loads, null spikes, schema drift
- **Trust scores** — a 0–100 score per table, shown next to dashboards
- **Cost & usage view** — from Exasol's own statistics tables

## Architecture

```
NYC TLC open data → Python ingest (pyexasol, with failure injection)
  → Exasol Personal: RAW / CURATED / TRUSTLAYER schemas
      ├─ SQL + Python UDF checks → TRUSTLAYER.CHECK_RESULTS
      └─ EXA_STATISTICS → usage / cost
  → Scheduler → webhook alerts
  → Streamlit dashboard
```

## Setup

1. Install **Exasol Personal**: <https://www.exasol.com/developers/>
   (or on AWS/Azure: <https://github.com/exasol/exasol-personal>).
2. Install Python deps:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Linux/WSL: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your Exasol connection details.
4. Test the connection:
   ```bash
   python scripts/test_connection.py
   ```
5. Create schemas and load data:
   ```bash
   python ingest/load_nyc_taxi.py --months 2024-01 2024-02 2024-03
   ```

## Usage

_Coming in Day 2–3: checks, scheduler, alerts, dashboard._

## Data sources & licences

| Source | Use | Terms |
|---|---|---|
| [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) | Sample pipeline data | NYC Open Data terms of use |

## Third-party tools

| Tool | Licence |
|---|---|
| Exasol Personal | Exasol Personal licence |
| pyexasol | MIT |
| pandas | BSD-3-Clause |
| pyarrow | Apache-2.0 |
| python-dotenv | BSD-3-Clause |
| requests | Apache-2.0 |

## Licence

MIT — see [LICENSE](LICENSE).
