# Phase 1 — Top-level schemas

Every schema below lives in `src/portfolio_thesis_engine/schemas/` and
is a Pydantic v2 model with `extra="forbid"`, tab-free YAML round-trip
via `to_yaml` / `from_yaml`, and strict type validation.

## New in Phase 1

### `WACCInputs` (`schemas/wacc.py`)

Parsed from `wacc_inputs.md` via :mod:`ingestion.wacc_parser`. Carries
the identity, cost-of-capital components, capital structure, and the
three scenario drivers.

```yaml
ticker: 1846.HK
profile: P1
valuation_date: "2024-12-31"
current_price: "12.30"
cost_of_capital:
  risk_free_rate: 2.5
  equity_risk_premium: 5.5
  beta: 1.1
  cost_of_debt_pretax: 4.0
  tax_rate_for_wacc: 16.5
capital_structure:
  debt_weight: 25
  equity_weight: 75
scenarios:
  bear: { probability: 25, ... }
  base: { probability: 50, ... }
  bull: { probability: 25, ... }
```

`wacc` and `cost_of_equity` are `@property` — kept out of the
serialised form so YAML round-trip works with `extra="forbid"`.

### `IngestedDocument` (`ingestion/base.py` — dataclass, not schema)

Frozen dataclass with `doc_id`, `ticker`, `doc_type`, `source_path`,
`report_date`, `content_hash` (SHA-256), `ingested_at`, `mode`.
Written to the `DocumentRepository`'s filesystem; the SQLite metadata
repo records the company row.

### `StructuredSection` + `ExtractionResult` (`section_extractor/base.py`)

Output of the 3-pass section extractor. `StructuredSection` carries
`section_type`, `title`, `content` (raw markdown slice), and
`parsed_data` (dict from the Pass 2 tool-use call — shape specific
to the section). `ExtractionResult` holds the list plus
`overall_status` and `issues` from Pass 3 validation.

### `CrossCheckReport` (`cross_check/base.py`)

Per-ticker gate verdict with one `CrossCheckMetric` per canonical
metric (10 total: revenue, operating_income, net_income,
total_assets, total_equity, cash, operating_cash_flow, capex,
shares_outstanding, market_cap). Each carries
`extracted_value`, `fmp_value`, `yfinance_value`, `max_delta_pct`,
and a `CrossCheckStatus` ∈ {PASS, WARN, FAIL, SOURCES_DISAGREE,
UNAVAILABLE}. Overall status precedence: FAIL > SOURCES_DISAGREE >
WARN > PASS; UNAVAILABLE is neutral.

### Extraction output (`extraction/base.py`)

`ExtractionResult` — ticker + fiscal period + list of
:class:`ModuleAdjustment` + decision/estimate logs + optional
`canonical_state` (set when `extract_canonical()` is used).

### `ValuationSnapshot` (`schemas/valuation.py`, re-used from Fase 0)

Immutable, versioned. New in Phase 1:
- `scenarios: list[Scenario]` populated with three entries in
  bear→base→bull order.
- `weighted: WeightedOutputs` with probability-weighted E[V], fair
  value range, upside %, asymmetry ratio.
- `conviction: Conviction` defaulted to all-MEDIUM (human edits
  later).

### `Ficha` (`schemas/ficha.py`, re-used from Fase 0)

Aggregate view. Phase 1 populates identity, current IDs (extraction +
valuation), conviction, market_contexts, snapshot_age_days, is_stale.
`thesis`, `position`, `monitorables` stay empty — Phase 2.

## Extended in Phase 1

### `NOPATBridge` (`schemas/company.py`)

Sprint 9's pre-patch renamed `ebita` → `ebitda` and added an optional
`ebita: Money | None = None`. Phase 1's P1 parser aggregates D+A under
`d_and_a`, so only `ebitda` is populated; Phase 2's parser will split
depreciation from amortisation and fill both.

```python
class NOPATBridge(BaseSchema):
    period: FiscalPeriod
    ebitda: Money                     # Op Income + |D&A total|
    ebita: Money | None = None        # Phase 2: Op Income + |Amortisation only|
    operating_taxes: Money            # anchor × op_tax_rate
    nopat: Money                      # anchor − operating_taxes
    ...
```

## Repository layout

Every schema has a matching repository in `storage/yaml_repo.py`:

| Schema                        | Repository                          | Layout                                                            |
| ----------------------------- | ----------------------------------- | ----------------------------------------------------------------- |
| `Ficha`                       | `CompanyRepository`                 | `companies/{ticker}/ficha.yaml` (single)                          |
| `CanonicalCompanyState`       | `CompanyStateRepository`            | `companies/{ticker}/extraction/{ext_id}.yaml` + `current` symlink |
| `ValuationSnapshot`           | `ValuationRepository`               | `companies/{ticker}/valuation/{snap_id}.yaml` + `current` symlink |
| `Position`                    | `PositionRepository` (Phase 2)      | `portfolio/positions/{ticker}.yaml`                               |
| `Peer`                        | `PeerRepository` (Phase 2)          | `peers/{ticker}.yaml`                                             |

Ticker normalisation (`TEST.L` → `TEST-L`) is applied on every save
and lookup, documented in `storage.base.normalise_ticker`.
