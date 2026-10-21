# TrustLayer

**Stop broken data before it reaches a dashboard, show exactly who would have been
affected, and explain it in plain English: with every check running inside Exasol.**

Built on **Exasol Personal** for ExaThon India 2026, Track 04: *The Work Behind the Work*.

## Problem

Data teams usually learn a pipeline failed overnight when a business user complains
about a wrong number. By then the bad data is already in every report built on it, and
trust is gone. Typical monitoring only *alerts* after the fact; it does not stop the
damage, and it cannot say which dashboards were hit.

## Solution

Every hourly batch lands in a **staging** area first. TrustLayer checks it **inside
Exasol** against what normal looks like for that hour, then either **publishes** it to
the curated tables that dashboards read, or **quarantines** it and opens an incident.

| Problem on the track card | What TrustLayer does |
|---|---|
| Pipelines that fail overnight without warning | Learned-baseline checks on every batch; incidents opened automatically |
| Dashboards the business no longer trusts | Bad batches are blocked before dashboards see them; a live 0–100 trust score per table |
| Data requests that queue for weeks | Incident reports explain problems in plain English; *(planned)* plain-English questions answered with SQL on Exasol |
| Platform cost growing faster than usage | *(planned)* waste report from Exasol's own statistics |

### What makes it different

- **Quarantine gate, not just alerts.** Dashboards only read `CURATED`, so a bad batch never reaches them.
- **Learned, adaptive baselines.** A Python UDF *inside Exasol* learns each hour of the week
  with robust statistics (median and MAD), so one holiday or outage in the history does not skew it.
  Expected volume follows the recent traffic level, so seasonal growth is absorbed while a sudden
  collapse still fails.
- **Alerts need two kinds of evidence:** a change must be statistically unusual *and* large enough to matter.
- **Blast radius from Exasol's dependency catalog** (`EXA_DBA_DEPENDENCIES`): every incident names
  the downstream views and dashboards (and owners) that were protected.
- **Honest trust score.** Blocking bad data keeps dashboards correct but makes them fall behind;
  the score says so (quality of the last published batch minus a staleness/missing-hours penalty).
- **Plain-English incident reports (Gemini).** Gemini receives only aggregate evidence computed in
  Exasol, never raw rows, and is *not told* which failure happened. In testing it identified
  "dollars switched to cents" and "column dropped upstream" from the numbers alone. Reports are cached
  (one call per incident), fall back across models, and degrade to a template report offline.
- **Close the loop.** `retry` re-runs a blocked hour after the upstream fix and resolves the incident.
- **Trust badge** any BI tool can embed as an image: `<img src="http://localhost:8765/badge.svg">`.

## Architecture

```
NYC TLC open data (Parquet)
  └─ ingest/load_nyc_taxi.py ──────────────► RAW.YELLOW_TRIPS        (9.5M rows, Jan–Mar 2024)
                                                  │ hourly batch (+ optional failure injection)
                                                  ▼
                                            STAGE.YELLOW_TRIPS
                                                  │ checks in Exasol: volume, distribution,
                                                  │ completeness, schema drift, uniqueness, validity
                                                  │ vs TRUSTLAYER.BASELINE (Python UDF)
                                    pass ┌────────┴────────┐ fail
                                         ▼                 ▼
                              CURATED.YELLOW_TRIPS   QUARANTINE.YELLOW_TRIPS + TRUSTLAYER.INCIDENTS
                                         │
                       MART views ───────┴──► dashboards (Executive KPIs, Daily Revenue, ...)
                       TRUSTLAYER.TRUST_SCORES, BATCH_HEALTH, CHECK_RESULTS, LOAD_LOG
```

## Setup

1. **Install Exasol Personal** (<https://www.exasol.com/developers/>). On Windows use WSL (Ubuntu):
   ```bash
   curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
   sudo apt install -y podman
   exasol install local
   exasol slc install PYTHON3     # Python runtime for the in-database baseline UDF
   exasol info                    # connection details
   ```
   AWS/Azure deployment: <https://github.com/exasol/exasol-personal>.
2. **Python environment** (3.12+):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Linux/WSL: source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
3. **Connection:** copy `.env.example` to `.env` and fill in host, port and password from `exasol info`.
   Optionally add a free Gemini API key (<https://aistudio.google.com/apikey>) as `GEMINI_API_KEY`.
   Then check it:
   ```bash
   python scripts/test_connection.py
   ```

## Quick start

```bash
python demo.py                      # loads data if needed, rebuilds, replays 12 h, opens the dashboard
python demo.py --break unit_change  # same, plus one injected failure with its incident report
```

Full install, run guide and troubleshooting: **[DEPLOY.md](DEPLOY.md)**.
Demo video script: [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md).

## Usage

```bash
# Land Jan–Mar 2024 NYC taxi trips in RAW (~150 MB download, ~6 min load)
python ingest/load_nyc_taxi.py --reset-raw

# Create pipeline schemas, publish history up to 2024-03-04, learn baselines
python -m trustlayer.cli setup --reset
python -m trustlayer.cli backfill

# Run the pipeline hour by hour
python -m trustlayer.cli replay --hours 24
python -m trustlayer.cli run-batch --chaos duplicates    # inject a failure
python -m trustlayer.cli status                          # trust score + recent batches
python -m trustlayer.cli affected                        # downstream views and dashboards
python -m trustlayer.cli report INC-...                  # plain-English incident report
python -m trustlayer.cli retry INC-...                   # re-run the blocked hour, resolve if clean

# Dashboard: trust score, Break-it controls, blast radius, incidents, timeline
streamlit run app/dashboard.py

# Embeddable badge
python -m trustlayer.badge                               # http://localhost:8765/badge.svg
```

### Failure scenarios (`--chaos`)

| Scenario | Simulates | Caught by |
|---|---|---|
| `duplicates` | a retried job re-sends part of a batch | uniqueness |
| `volume_drop` | source export cut off partway | volume |
| `empty` | job ran but delivered nothing | volume |
| `null_spike` | partner API returns blanks | completeness |
| `column_dropped` | upstream renamed a column | schema drift |
| `bad_values` | refund logic flipped fare signs | validity, distribution |
| `unit_change` | amounts switched from dollars to cents | distribution |

## Results so far (Exasol Personal on a laptop, 3.7 GB WSL)

- 9.55M rows landed; 6.3M rows of history published in ~40 s; baselines learned by the UDF in ~10 s.
- 96 consecutive real hourly batches: **0 false quarantines**. Warnings flagged a genuine upstream
  change: missing passenger counts rose from ~5% to 20–28% on some March 2024 evenings.
- All 7 failure scenarios quarantined, each with an incident naming the 4 protected dashboards.
- 12 checks on a ~5,000-row hourly batch run inside Exasol in ~0.4 s.

## Tests

```bash
pytest
```
Unit tests cover the decision rules, robust baseline maths, every check and the lineage walk. They need no database.

## Data sources & licences

| Source | Use | Terms |
|---|---|---|
| [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) | Sample pipeline data | NYC Open Data terms of use |

## Third-party tools

| Tool | Licence |
|---|---|
| Exasol Personal (+ Python 3.12 script language container) | Exasol Personal licence |
| pyexasol | MIT |
| pandas | BSD-3-Clause |
| pyarrow | Apache-2.0 |
| python-dotenv | BSD-3-Clause |
| requests | Apache-2.0 |
| streamlit (+ altair) | Apache-2.0 (BSD-3-Clause) |
| google-genai (Gemini API, free tier) | Apache-2.0; API use under Google's Gemini API terms |
| pytest | MIT |

Gemini receives only aggregated check results and statistics, never trip-level rows.

## Licence

MIT, see [LICENSE](LICENSE).
