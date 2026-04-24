# PTE API Deployment

**Service**: FastAPI backend exposing PTE artefacts.
**Source**: [`api/`](../../api/) — additive to the PTE Python codebase.
**Bind**: Tailscale interface (`100.70.51.18:8000`) — no public exposure.
**Authentication**: HTTP Basic Auth (`PTE_API_USER` / `PTE_API_PASSWORD`).

---

## Prerequisites

- Hetzner VPS with Tailscale enrolled (server `dataflow @ 100.70.51.18`).
- Repo cloned at `/home/portfolio/workspace/portfolio-thesis-engine/`.
- Python 3.12 + `uv` installed (already true on the dev VPS).
- A user in the `sudo` group (Docker installation requires sudo).

---

## Initial setup (one-time)

### 1. Install Docker

```bash
cd ~/workspace/portfolio-thesis-engine
sudo bash scripts/install_docker.sh
```

The script is idempotent — re-running on a host that already has Docker is a no-op. After install, **the user must log out and log back in** (or `newgrp docker`) for the docker group membership to take effect. Verify:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

### 2. Configure credentials

```bash
cp api/.env.example api/.env
nano api/.env   # set PTE_API_USER + PTE_API_PASSWORD to strong values
```

`api/.env` is gitignored. The file is read by `pydantic-settings` and by `docker compose` (via the `environment:` interpolation in `docker-compose.yml`).

### 3. Build + start the service

```bash
cd ~/workspace/portfolio-thesis-engine
docker compose up -d --build
```

First build downloads the Python base image and `uv sync`s the project — expect ~3-5 min on a clean host. Subsequent rebuilds are incremental.

### 4. Verify

```bash
# From the server
curl -fsS http://localhost:8000/api/health

# From your laptop on the tailnet
curl -fsS http://100.70.51.18:8000/api/health
# Or via MagicDNS
curl -fsS http://dataflow:8000/api/health
```

Expected:
```json
{"status":"ok","version":"0.10.0","timestamp":"..."}
```

---

## Operations

### Logs

```bash
# Follow service logs
docker compose logs -f pte-api

# Last 200 lines
docker compose logs --tail=200 pte-api
```

### Restart after a code change

```bash
git pull
docker compose up -d --build
```

The build cache is layered: only the changed files trigger a rebuild step. PTE code changes are picked up because the `.:/workspace/portfolio-thesis-engine` bind mount is read-write — but the `pte` CLI inside the container reads from the mount, so a `git pull` on the host is enough; no rebuild needed unless you change `api/` or `pyproject.toml`.

### Stop / start / restart

```bash
docker compose stop          # graceful stop
docker compose start         # resume
docker compose restart       # reload (e.g. after editing api/.env)
docker compose down          # stop + remove container
```

---

## Authentication usage

```bash
# curl
curl -u hugo:yourpassword http://100.70.51.18:8000/api/tickers

# httpie
http --auth hugo:yourpassword http://100.70.51.18:8000/api/tickers
```

Browser usage: visit `http://100.70.51.18:8000/api/tickers` — the browser prompts for Basic Auth credentials.

---

## Tailscale-specific notes

- The container binds **inside** to `0.0.0.0:8000`; the host-side bind in `docker-compose.yml` is constrained to `100.70.51.18:8000` (Tailscale interface IP). Public internet traffic cannot reach the API.
- All Tailscale clients (laptop, phone) on the same tailnet can access via the IP or the MagicDNS hostname `dataflow`.
- No SSL setup required — Tailscale provides WireGuard transport encryption.
- If Tailscale assigns a different IP after an upgrade, override at deploy time:
  ```bash
  PTE_API_BIND_HOST=<new-ip> docker compose up -d
  ```

---

## API documentation

OpenAPI spec is auto-generated and available at:

- Swagger UI: `http://100.70.51.18:8000/api/docs`
- ReDoc: `http://100.70.51.18:8000/api/redoc`
- Raw JSON: `http://100.70.51.18:8000/api/openapi.json`

---

## Endpoint inventory

All endpoints under `/api`. Health is unauthenticated; everything else requires Basic Auth.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe; no auth. |
| GET | `/tickers` | List all tickers + artefact availability. |
| GET | `/tickers/{ticker}` | Ticker detail (enriched with canonical state). |
| GET | `/tickers/{ticker}/canonical` | Latest canonical state via `current` symlink. |
| GET | `/tickers/{ticker}/valuation` | Latest valuation snapshot. |
| GET | `/tickers/{ticker}/forecast` | Latest forecast JSON snapshot. |
| GET | `/tickers/{ticker}/ficha` | Ficha (thesis, conviction). |
| GET | `/tickers/{ticker}/peers` | Peers — yaml + sqlite combined. |
| GET | `/tickers/{ticker}/cross-check` | Most recent cross-check log. |
| GET | `/tickers/{ticker}/pipeline-runs?limit=20` | Recent runs. |
| GET | `/tickers/{ticker}/yamls` | List analyst-editable yamls. |
| GET | `/tickers/{ticker}/yamls/{name}` | Download yaml as raw text. |
| POST | `/tickers/{ticker}/yamls/{name}` | Upload yaml — validates + backs up. |
| GET | `/tickers/{ticker}/yamls/{name}/versions` | Backup history. |
| POST | `/pipelines/{ticker}/run` | Spawn `pte process`. |
| POST | `/pipelines/{ticker}/forecast` | Spawn `pte forecast`. |
| POST | `/pipelines/{ticker}/valuation` | Spawn `pte valuation`. |
| GET | `/pipelines/{ticker}/runs/{run_id}?tail=30` | Status + log tail. |

The complete inventory is in [`docs/reference/cli_reference.md`](../reference/cli_reference.md) (host-side CLI) and the OpenAPI spec.

---

## Yaml workflow contract

Allowed yaml names for upload (whitelist):

- `scenarios`
- `capital_allocation`
- `leading_indicators`
- `peers`
- `revenue_geography`
- `valuation_profile`

Upload pipeline:

1. **YAML parse** — `yaml.safe_load`. Syntax errors → 422 with `validation_errors[*].type == "yaml_syntax"`.
2. **Pydantic validate** — lazy-imports the relevant PTE schema (`ScenarioSet`, `ParsedCapitalAllocation`, `LeadingIndicatorsSet`). Missing schemas (peers / revenue_geography / valuation_profile) skip semantic validation. Failures → 422 with `validation_errors[*].type == "pydantic_validation"`.
3. **Backup** — prior file copied to `<ticker_dir>/.versions/<name>_<YYYYMMDDTHHMMSS_microsecondsZ>.yaml.bak`.
4. **Atomic-ish write** — single `Path.write_text` call.
5. **Cleanup** — `.versions/` pruned to the last `PTE_API_YAML_VERSIONS_KEEP` entries (default 10).

---

## Pipeline runner contract

`POST /pipelines/{ticker}/run` returns immediately with a `run_id`:

```json
{
  "run_id": "a1b2c3d4e5f6",
  "ticker": "1846.HK",
  "command": "uv run pte process 1846.HK --base-period FY2024",
  "status": "queued",
  "started_at": "2026-04-24T22:50:00Z"
}
```

Poll `GET /pipelines/{ticker}/runs/{run_id}` for status (`queued` → `running` → `done` / `failed` / `timeout`). Hard timeout: `PTE_API_PIPELINE_TIMEOUT_SECONDS` (default 1800 = 30 min). Status payload includes `output_tail` with the last `tail` lines of the log file (default 30).

Log files: `data/logs/api_runs/<run_id>.log` + `<run_id>.meta.json`.

The runner uses `asyncio.create_subprocess_exec` with the configured `pte_command` (default `uv run pte`) inside `pte_workdir` (default `/workspace/portfolio-thesis-engine`). It **does not import PTE Python modules** — keeps the API process light and isolates pipeline crashes from the API event loop.

---

## Troubleshooting

### Service won't start

```bash
docker compose logs pte-api
```

Common causes:
- `PTE_API_USER` or `PTE_API_PASSWORD` not set in `.env` — `${PTE_API_USER:?}` syntax in `docker-compose.yml` fails the start with a clear error.
- Port `8000` already bound on the Tailscale IP — `ss -tlnp | grep 8000` to find the offender.
- Volume mount `./data` doesn't exist — create the directory or fix the path.

### 401 errors

Verify the Basic Auth credentials match `api/.env`. After editing `.env`:

```bash
docker compose restart pte-api
```

### CORS errors from the frontend

The middleware accepts `localhost`, `127.0.0.1`, `100.x.x.x` (Tailscale subnet) and the MagicDNS host `dataflow`. Anything else is rejected. If your frontend serves from a different origin, add it to the regex in `api/main.py::add_middleware(CORSMiddleware, allow_origin_regex=...)`.

### Pipeline runs fail immediately

The container needs read-write access to `data/yamls/`, `data/forecast_snapshots/`, `data/logs/`, etc. The default volume mount (`.:/workspace/portfolio-thesis-engine`) gives the subprocess access. Verify:

```bash
docker compose exec pte-api ls -la /workspace/portfolio-thesis-engine/data/yamls
```

### SQLite write contention

The API only **reads** SQLite. The pipeline subprocess writes to it. SQLite supports concurrent reads + serialised writes — no manual locking required at the API layer.

---

## Backup recommendations

The host's `data/` directory holds:

- Analyst-edited yamls (high-value: `scenarios`, `capital_allocation`, `leading_indicators`).
- Forecast snapshots (regenerable from yamls + canonical state).
- Cross-check + pipeline run logs (regenerable).

Daily snapshot of `data/yamls/companies/*/.versions/` is sufficient to recover from accidental yaml overwrites; the in-place yamls themselves are continuously committed to git when the analyst chooses to publish.

---

## Tests

API integration tests live alongside the service:

```bash
uv run pytest api/tests/ -v
```

The test suite uses `fastapi.testclient.TestClient` against the live `data/` fixture for read endpoints; pipeline tests monkeypatch `pipeline_runner._run_subprocess` to avoid the 10-minute `pte` cost. Total: 34 tests.

Full suite (PTE + API): `uv run pytest -q`. Current count: **1496 passing**, 6 skipped.

---

## Related references

- [`docs/phase2_architecture.md`](../phase2_architecture.md) — overall valuation engine architecture.
- [`docs/reference/cli_reference.md`](../reference/cli_reference.md) — host-side `pte` CLI.
- [`docs/schemas/scenarios_schema.md`](../schemas/scenarios_schema.md) — yaml upload contract.
- [`docs/schemas/forecast_snapshots_schema.md`](../schemas/forecast_snapshots_schema.md) — `/api/tickers/{ticker}/forecast` payload.
- [`api/.env.example`](../../api/.env.example) — credential template.
