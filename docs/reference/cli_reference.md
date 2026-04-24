# PTE CLI Reference

**Binary**: `pte` — invoke via `uv run pte` inside the project directory.
**Source**: [`src/portfolio_thesis_engine/cli/app.py`](../../src/portfolio_thesis_engine/cli/app.py)
**Framework**: Typer (Rich-rendered help + tables).

Every subcommand supports `--help`. This reference is generated from the live `--help` output at tag `v0.9.5-phase2-sprint4a-alpha-9-polish-and-docs`. **If a flag disagrees between this doc and `--help`, trust `--help`**.

---

## Commands by use case

### Setup and health

| Command | Purpose | Flags |
|---|---|---|
| `pte setup` | Initialise data tree and validate prerequisites. | — |
| `pte health-check` | Render status table; exits 1 if any required component fails. | — |
| `pte smoke-test` | Run smoke test suite and render status table. | — |

### Ingestion

#### `pte ingest`

Register one or more document files under a ticker in the document store.

| Flag | Short | Type | Default | Notes |
|---|---|---|---|---|
| `--ticker` | `-t` | str | *(required)* | Target ticker (e.g. `1846.HK`). |
| `--files` | `-f` | str | — | Comma-separated list of file paths. |
| `--extraction` | `-e` | path | — | Shortcut: raw_extraction.yaml path. Added to `--files` automatically and stored under `doc_type='raw_extraction'`. |
| `--mode` | `-m` | str | `bulk_markdown` | Ingestion mode: `bulk_markdown` or `pre_extracted` (Phase 2). |
| `--profile` | | str | `P1` | Profile code to register with the ticker. |

### Extraction validation

| Command | Purpose | Flags |
|---|---|---|
| `pte validate-extraction <path>` | Validate a raw_extraction.yaml without running the pipeline. | `--profile` (default `P1`) |
| `pte audit-extraction <ticker>` | Validate the most recent ingested extraction for `<ticker>`. | `--profile` (default `P1`) |

### Pipeline (end-to-end)

#### `pte process <ticker>`

Runs the Phase 1.5 pipeline end-to-end: load → validate → cross-check → canonical state → guardrails → valuation → ficha.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--wacc-path` | str | auto | Path to `wacc_inputs.md`. Defaults to ingested copy or `~/data_inputs/{ticker}/wacc_inputs.md`. |
| `--extraction-path` | str | auto | Path to `raw_extraction.yaml`. Defaults to ingested copy or `~/data_inputs/{ticker}/raw_extraction.yaml`. |
| `--force` | flag | off | Bypass cached-stage checks; always re-run every stage. |
| `--skip-cross-check` | flag | off | Bypass the cross-check gate. Not recommended; prefer period-aware cross-check (Sprint 4A-alpha.7). |
| `--force-cost-override` | flag | off | Temporarily raise the per-company cost cap (emergency only). |
| `--base-period` | str | `AUTO` | Which extraction to process when multiple exist. Accepts `AUTO`, `LATEST-AUDITED`, or a specific label like `FY2024` / `FY2025-preliminary`. |

### Valuation

#### `pte valuation <ticker>`

Scenario-weighted DCF valuation with rich-table output.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--scenario` | str | — | Scenario name for detailed projection table. |
| `--detail` | flag | off | Print full year-by-year projection detail. |
| `--market-price` | float | auto | Override market price for upside calc. |
| `--export` | path | — | Write valuation markdown report to `PATH`. |

#### `pte forecast <ticker>`

Three-statement forecast across all scenarios (Sprint 4A-beta).

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--scenario` | str | all | Restrict output to a single scenario name. |
| `--export` | path | — | Write a Markdown summary to `PATH`. |
| `--years` | int | `5` | Projection horizon in years. |
| `--no-persist` | flag | off | Skip writing the JSON snapshot to `data/forecast_snapshots/`. |

#### `pte reverse <ticker>`

Reverse DCF — solve market-implied drivers against current (or target) price.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--solve-for` | str | — | Driver to solve for: `operating_margin`, `terminal_growth`, `wacc`, `revenue_growth_terminal`, `capex_intensity`. |
| `--enumerate` | flag | off | Solve all supported drivers and render the matrix. |
| `--scenario` | str | `base` | Scenario to reverse-solve against. |
| `--target` | float | market price | Target price for the reverse solve. |
| `--export` | path | — | Write markdown report to `PATH`. |

### Analytical layer

#### `pte analyze <ticker>`

Historical analytics — Economic BS, DuPont, ROIC, trends, QoE, investment signal.

| Flag | Type | Notes |
|---|---|---|
| `--export` | path | Write analytical markdown report to `PATH` (in addition to stdout). |

#### `pte peers <ticker>`

Peer-relative analysis — fundamentals, multiples, regression.

| Flag | Type | Notes |
|---|---|---|
| `--export` | path | Write peer-analysis markdown report to `PATH`. |

#### `pte historicals <ticker>`

Build and render the historical time-series.

| Flag | Type | Notes |
|---|---|---|
| `--export` | path | Write a markdown report to `PATH` (in addition to stdout). |

#### `pte briefing <ticker>`

Analytical briefing markdown — cost structure, leading indicators, sector context.

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--purpose` | str | `full` | One of `capital_allocation`, `scenarios_generate`, `scenarios_revise`, `full`. |
| `--export` | path | `/tmp/...` | Write briefing markdown to `PATH`. |
| `--output-stdout` | flag | off | Print briefing to terminal. |
| `--include-reverse-dcf` / `--no-reverse-dcf` | flag | auto | Include reverse-DCF section in valuation detail (default `True` for `scenarios_revise` + `full`). |

### Inspection

#### `pte show <ticker>`

Render the aggregate Ficha view.

| Flag | Type | Notes |
|---|---|---|
| `--json` | flag | Emit machine-readable JSON instead of Rich tables. |
| `--detail` | flag | Full model: economic BS, NOPAT bridge, per-scenario projection + EV bridge, sensitivity grid. |
| `--scenario` | str | Deep-dive a single scenario (`bear`, `base`, `bull`). Implies `--detail`. |
| `--narrative` | flag | Render the narrative summary (key themes, risks, guidance, capital allocation) with source attribution. |

### Maintenance

| Command | Purpose | Flags |
|---|---|---|
| `pte cross-check <ticker>` | Re-run the cross-check gate with supplied values. | `--period` / `-p`, `--values-json` / `-v`, `--override-thresholds` |
| `pte generate-overrides <ticker>` | Emit a user-editable overrides template for Module D. | `--output` / `-o` |

---

## Data file locations

```
data/
├── documents/<ticker>/                                # Phase 1 raw documents
│   └── wacc_inputs/wacc_inputs.md
├── yamls/
│   ├── companies/<ticker>/
│   │   ├── scenarios.yaml                              # see scenarios_schema.md
│   │   ├── capital_allocation.yaml                     # see capital_allocation_schema.md
│   │   ├── leading_indicators.yaml                     # see leading_indicators_schema_reference.md
│   │   ├── valuation_profile.yaml
│   │   ├── peers.yaml
│   │   ├── revenue_geography.yaml
│   │   ├── extraction/<ticker>_<period>_<timestamp>.yaml   # canonical states (versioned)
│   │   └── valuation/<ticker>_<timestamp>.yaml             # valuation snapshots
│   └── library/                                        # shared reference data
├── forecast_snapshots/<ticker>/<ticker>_<timestamp>.json   # see forecast_snapshots_schema.md
├── logs/
│   ├── cross_check/<ticker>_<timestamp>.json
│   └── runs/<ticker>_<timestamp>.jsonl
└── reference/                                          # Damodaran tables etc.
```

---

## Common flows

### New ticker (end-to-end)

See [`docs/workflows/new_ticker_onboarding.md`](../workflows/new_ticker_onboarding.md) for the full playbook. Quick version:

```bash
uv run pte ingest -t 1846.HK -e ~/data_inputs/1846-HK/raw_extraction_fy2024.yaml
uv run pte process 1846.HK --base-period FY2024
uv run pte valuation 1846.HK
uv run pte forecast 1846.HK
uv run pte briefing 1846.HK
```

### Historical period (cross-check post-4A-alpha.7)

```bash
uv run pte process 1846.HK \
  --extraction-path ~/data_inputs/1846-HK/raw_extraction_fy2021.yaml \
  --base-period FY2021
```

Cross-check is period-aware — providers return FY2021 data (or `UNAVAILABLE`) instead of the FY2024 latest-annual override that plagued pre-4A-alpha.7 runs.

### Forecast-only iteration (skip persistence)

```bash
uv run pte forecast 1846.HK --scenario base --no-persist --years 5
```

### Reverse solve against a target price

```bash
uv run pte reverse 1846.HK --target 6.00 --solve-for operating_margin
```

---

## Output formats

- **Rich tables** — default terminal output.
- **Markdown** — via `--export <path>` (supported by `valuation`, `forecast`, `reverse`, `analyze`, `peers`, `historicals`, `briefing`).
- **JSON** — `pte show --json`, and every `data/forecast_snapshots/*.json` snapshot.

## Exit codes

`pte` propagates a small set of conventional exit codes:

- `0` — success.
- `1` — validation failure (strict) or health check mismatch.
- `2` — cross-check blocking failure (use `--skip-cross-check` only in emergencies).
- Non-zero > 2 — other system errors (uncaught exceptions, I/O failures).

## Global help

- `pte --help` — top-level command list.
- `pte <command> --help` — per-command flag table (authoritative source for this reference).
