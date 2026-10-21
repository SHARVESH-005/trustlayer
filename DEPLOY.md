# Deploying and running TrustLayer

TrustLayer needs two things: an **Exasol Personal** database and a **Python 3.12+** environment
that can reach it. Everything else (schemas, data, baselines, UDF) is created by the project.

| Requirement | Notes |
|---|---|
| Exasol Personal | local (macOS, Linux, Windows via WSL) or your own AWS / Azure / Exoscale / STACKIT account |
| Python | 3.12 or newer, with `pip` |
| Disk | ~3 GB for the Exasol image and Python runtime, ~150 MB of taxi data |
| Memory | 8 GB machine works (tested: 7.7 GB laptop, WSL limited to 3.7 GB) |
| Network | first run downloads the Exasol images (~2.8 GB) and the NYC data (~150 MB) |
| Optional | free Gemini API key for AI incident reports |

## 1. Install Exasol Personal

### Windows (WSL 2, tested)

Open **Ubuntu** (`wsl -d Ubuntu` from PowerShell), then:

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
sudo apt update && sudo apt install -y podman
exasol install local
exasol slc install PYTHON3       # Python runtime for the in-database baseline UDF (~2.1 GB)
exasol status                    # wait for: Status: database_ready
exasol info                      # host, port, user; password is in the deployment's secrets.json
```

WSL forwards the database port to Windows, so Python on Windows connects to `127.0.0.1:8563`.

### macOS / Linux

Same commands without WSL. On Linux, `exasol install local` uses Podman; on macOS it uses a lightweight VM.

### AWS or Azure

```bash
exasol install aws      # or: exasol install azure
exasol info
```
See <https://github.com/exasol/exasol-personal> for credentials and options. Then set
`EXASOL_HOST` in `.env` to the address `exasol info` prints. Run `exasol slc install PYTHON3` there too.

## 2. Install TrustLayer

```bash
git clone https://github.com/SHARVESH-005/trustlayer.git
cd trustlayer
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux/WSL: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # Windows: copy .env.example .env
```

Fill in `.env`:

| Key | Value |
|---|---|
| `EXASOL_HOST`, `EXASOL_PORT`, `EXASOL_USER` | from `exasol info` (local default `127.0.0.1`, `8563`, `sys`) |
| `EXASOL_PASSWORD` | `dbPassword` in `~/.exasol/personal/deployments/default/secrets.json` |
| `EXASOL_ENCRYPTION` / `EXASOL_VERIFY_CERT` | `true` / `false` (Exasol Personal uses a self-signed certificate) |
| `GEMINI_API_KEY` | optional, from <https://aistudio.google.com/apikey> |

Check the connection:

```bash
python scripts/test_connection.py
# Connected. SELECT 1 -> 1. Exasol version: 2026.2.0-nano.3
```

## 3. Run

```bash
python demo.py
```

This loads the data if needed (first run ~6 min), rebuilds the pipeline, publishes history, learns
baselines, replays 12 clean hours and opens the dashboard at <http://localhost:8501>.

| Option | Effect |
|---|---|
| `--break unit_change` | inject one failure before opening the dashboard (any scenario from the README) |
| `--hours 24` | replay more clean hours |
| `--no-dashboard` | prepare only |
| `--reload-data` | re-download and reload RAW |

Individual steps, the CLI and the badge server are listed in the [README](README.md#usage).

### Run guide for the dashboard

1. **Run next hour** publishes the next hourly batch; the trust score stays green.
2. **Break it** → pick a failure → **Inject into next hour**. The batch is quarantined, the trust
   score drops, the blast radius turns amber, and an incident with a Gemini report appears.
3. Open the incident and click **Retry hour** to re-run it cleanly; the incident resolves and the score recovers.
4. **Reset demo** rebuilds everything in about a minute.

### Tests

```bash
pytest          # unit tests, no database needed; also run by GitHub Actions on every push
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ConnectionRefusedError` / `WinError 10061` | database not running: `exasol status`, then `exasol start` |
| `Status: database_connection_failed` right after start | still booting; wait 1–2 minutes and check `exasol status` again |
| `exasol start` fails with "connection reset by peer" | the first boot after `slc install` can exceed the launcher's wait; run `exasol start` again |
| `slc install` seems stuck | it downloads a ~2.1 GB image; on slow links this takes 20–30 min |
| Authentication fails after a restart | the launcher can rotate the password; copy the new `dbPassword` from `secrets.json` into `.env` |
| `'podman' is required` | `sudo apt install -y podman` inside WSL/Linux |
| `sudo` password forgotten in WSL | from PowerShell: `wsl -d Ubuntu -u root`, then `passwd <your-user>` |
| `malloc ... failed` while loading | low memory; the loader already streams 500k-row chunks, so close other apps or raise the WSL memory limit in `%UserProfile%\.wslconfig` (`[wsl2]` `memory=6GB`) |
| `Python UDF unavailable, using SQL fallback` | `exasol slc install PYTHON3`; TrustLayer still works with SQL baselines without it |
| `Gemini unavailable ... used template report` | missing key, quota or a busy model; reports fall back to a template and the pipeline is unaffected |
| Port 8563 already in use | `exasol config set --ports db:<free-port>` and update `EXASOL_PORT` |

## Stopping and cleaning up

```bash
exasol stop            # stop the database, keep data
exasol destroy         # delete the deployment
```
