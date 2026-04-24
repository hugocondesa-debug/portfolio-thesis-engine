# Scenarios Schema — v1.1

**Schema version**: v1.1 (2026-04)
**Source of truth**: [`src/portfolio_thesis_engine/dcf/schemas.py`](../../src/portfolio_thesis_engine/dcf/schemas.py)
**Companion**: [`leading_indicators_schema_reference.md`](./leading_indicators_schema_reference.md)

## Changes vs v1.0

- **NEW**: `Scenario.bucket` — optional explicit :class:`ScenarioBucket` assignment. Absent bucket is inferred from `name` prefix.
- **NEW**: `scenario_relevance` (in `leading_indicators.yaml`) accepts generic buckets (`BASE` / `BULL` / `BEAR` / `TAIL`) alongside specific scenario names. Breaks the bootstrap circular reference for new companies.
- **ALIGN**: Documentation now matches the Pydantic model exactly. Previous drift (documented-but-absent `target`, `fade_to_terminal_over_years` in `ScenarioDriverOverride`) corrected; real fields documented; `terminal_multiple_scenarios` added.

**Backward compatibility**: every v1.0 yaml continues to validate. No migration required.

---

## File location

```
data/yamls/companies/<TICKER>/scenarios.yaml
```

## Top-level `ScenarioSet`

| Field | Type | Required | Notes |
|---|---|---|---|
| `target_ticker` | `str` | Yes | Matches company directory name (e.g. `1846.HK`). |
| `valuation_profile` | `DCFProfile` | Yes | One of `P1`, `P2`, `P3`, `P4`, `P5`, `P6`. |
| `base_year` | `str` | Yes | Period label for `base_drivers` anchoring, e.g. `FY2024`. |
| `base_drivers` | `dict[str, Any]` | Yes | Common driver block each scenario overlays (see below). |
| `scenarios` | `list[Scenario]` | Yes | Probability-weighted scenarios; probabilities must sum to 1.00 ± 0.01. |
| `terminal_multiple_scenarios` | `list[TerminalMultipleScenario] \| None` | No | Cross-check scenarios priced off a terminal EV/EBITDA multiple rather than Gordon growth. |
| `generated_at` | `datetime` | No | Auto-stamped by the Claude.ai Project workflow. |

---

## `base_drivers` block

Shared across all scenarios; each scenario's `driver_overrides` is a **sparse** overlay (only the fields that differ are restated). Recognised drivers:

- **`revenue`** — `base_year_value: int`, `growth_pattern: list[Decimal]`, `fade_to_terminal_over_years: int`, `terminal_growth: Decimal`.
- **`operating_margin`** — `current: Decimal`, `target_terminal: Decimal`, `fade_pattern: "LINEAR" | "FRONT_LOADED" | "BACK_LOADED"`.
- **`tax_rate`** — `statutory: Decimal`, `effective_current: Decimal`, `apply: "STATUTORY" | "EFFECTIVE"`.
- **`capex_intensity`** — `current: Decimal`, `target: Decimal`, `fade_pattern`.
- **`working_capital_intensity`** — `current: Decimal`, `target: Decimal`, `fade_pattern`.
- **`depreciation_rate`** — `current: Decimal`, `target: Decimal`, `source: "DERIVED_FROM_CAPEX_SCHEDULE"` (informational).

Free-form `dict[str, Any]` on the Pydantic side — analysts may carry additional annotation fields through without rejection. The DCF engine only reads the keys it recognises.

---

## `Scenario`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | `str` | Yes | Lowercase, underscored, unique per set. Examples: `base`, `bull_operational`, `bear_prc_delay`, `takeover_floor`. |
| `probability` | `Decimal` | Yes | 0 < p ≤ 1; must sum to 1.00 ± 0.01 across the set. |
| `rationale` | `str` | No | Free-form narrative (renders in `pte valuation`). |
| `bucket` | `ScenarioBucket \| None` | No (**v1.1**) | Explicit `BASE`/`BULL`/`BEAR`/`TAIL`. Omit to let `resolved_bucket` infer from `name`. |
| `methodology` | `MethodologyConfig` | No | Discriminated union — see below. Defaults to `DCF_3_STAGE` with 5/5 split. |
| `driver_overrides` | `dict[str, ScenarioDriverOverride]` | No | Sparse overlay on `base_drivers`. |
| `valuation_overrides` | `dict[str, Any]` | No | Free-form hook for engine-specific overrides (rarely used). |

### `resolved_bucket` (computed)

Returns the canonical `ScenarioBucket` for the scenario:

1. Explicit `bucket` field wins.
2. Else inference from `name.lower()`:
   - starts with `base` → `BASE`
   - starts with `bull` → `BULL`
   - starts with `bear` → `BEAR`
   - starts with `takeover_` or `tail_` or exact `fire_sale` → `TAIL`
   - exact `m_and_a_accelerated` → `BULL` (deployment scenario is bullish)
   - anything else → `BULL` (safe optimistic default)

---

## `ScenarioDriverOverride`

**Sparse overlay on `base_drivers`** — only the fields that differ from the base block are restated. Five fields total (one added in v1.1.1 for analyst ergonomics):

| Field | Type | Notes |
|---|---|---|
| `current` | `Decimal \| None` | Override for a driver's starting value (`operating_margin.current`, `capex_intensity.current`, ...). |
| `target_terminal` | `Decimal \| None` | Override for the terminal value a driver fades toward. Accepts `target` as an input alias (v1.1.1). |
| `growth_pattern` | `list[Decimal] \| None` | Revenue-specific — one rate per explicit year. Length must match base's explicit horizon when provided. |
| `fade_pattern` | `"LINEAR" \| "FRONT_LOADED" \| "BACK_LOADED" \| None` | **Shape** of the fade curve between `current` and `target_terminal`. |
| `fade_to_terminal_over_years` | `int \| None` | **Horizon** (1–10) declaring over how many years the fade spans (v1.1.1). Orthogonal to `fade_pattern`, but mutually exclusive: setting both raises. |

### Analyst ergonomics (v1.1.1)

The canonical Pydantic fields are `target_terminal` and `fade_pattern`. Two input-side conveniences are accepted:

| Canonical field | Input convenience | Behaviour |
|---|---|---|
| `target_terminal` | `target` | `AliasChoices` — either keyword populates `target_terminal`. Serialisation always emits `target_terminal`. |
| `fade_pattern` / `fade_to_terminal_over_years` | either, not both | If both are set on the same override block, validation raises (one mechanism of fade specification at a time). |

### Rules

- Aliases are **input-only**. Round-trip serialisation always uses canonical field names.
- `fade_to_terminal_over_years` must be an integer in `[1, 10]`; out-of-range values raise.
- Combining `fade_to_terminal_over_years` with `fade_pattern` raises `ValidationError`.
- `base_drivers` entries remain free-form `dict[str, Any]` — these rules apply **only** to `ScenarioDriverOverride` inside `scenarios[i].driver_overrides`.

### Example using the aliases

```yaml
driver_overrides:
  operating_margin:
    current: 0.1756
    target: 0.23                    # alias for target_terminal
    fade_to_terminal_over_years: 3  # integer horizon (orthogonal to fade_pattern)
```

### Equivalent canonical form

```yaml
driver_overrides:
  operating_margin:
    current: 0.1756
    target_terminal: 0.23
    fade_to_terminal_over_years: 3
```

### Drift corrections from v1.0 docs

**Removed** (these fields are NOT in `ScenarioDriverOverride` — they belong to `base_drivers` entries):

- ❌ `target` (appears in `capex_intensity`/`working_capital_intensity` base blocks, not here)
- ❌ `fade_to_terminal_over_years` (belongs to `base_drivers.revenue`)
- ❌ `terminal_growth` (belongs to `base_drivers.revenue` and to `DCFMethodologyConfig`)

Sprint 4A-alpha.9 will evaluate whether to re-introduce aliases (e.g. accept `target` as a synonym of `target_terminal` at override time) once analyst feedback is gathered.

### Example — bull scenario overriding margin + growth

```yaml
driver_overrides:
  revenue:
    growth_pattern: [0.13, 0.14, 0.13, 0.10, 0.075]
  operating_margin:
    target_terminal: 0.285
```

---

## `MethodologyConfig` (discriminated union)

Each scenario declares its valuation methodology via `methodology.type`. The dispatcher routes to the correct engine.

| `type` | Engine | Sprint | Key fields |
|---|---|---|---|
| `DCF_3_STAGE` | P1 DCF | 4A-alpha | `explicit_years`, `fade_years`, `terminal_method`, `terminal_growth` (Gordon) OR `terminal_multiple_*` |
| `DCF_2_STAGE` | P1 DCF (`fade_years=0`) | 4A-alpha | Same as 3-stage but `fade_years=0`. |
| `MULTIPLE_EXIT` | MultipleExitEngine | 4A-alpha | `metric`, `metric_year`, `multiple_source`, `multiple_value`, `multiple_multiplier` |
| `TRANSACTION_PRECEDENT` | Transaction engine | 4A-alpha | `metric`, `multiple_source`, `multiple_value`, `control_premium` |
| `DDM` | DDMEngine | 4B | `terminal_growth`, `explicit_years`, `cost_of_equity_override`, `payout_ratio` |
| `RESIDUAL_INCOME` | RIEngine | 4B | `terminal_growth`, `explicit_years`, `cost_of_equity_override` |
| `FFO_BASED` | — | 4C (planned) | `terminal_growth` |
| `NORMALIZED_DCF` | — | 4C (planned) | `historical_window_years`, `terminal_growth` |
| `THROUGH_CYCLE_DCF` | — | 4C (planned) | `cycle_length_years`, `terminal_growth` |
| `ASSET_BASED` | — | 4D (planned) | `components` |

For `DCF_3_STAGE` / `DCF_2_STAGE`, when `terminal_method == "TERMINAL_MULTIPLE"` the Gordon-growth fields are ignored and the engine reads:

- `terminal_multiple_metric`: `"EV_EBITDA"` / `"EV_SALES"` / `"PE"`
- `terminal_multiple_source`: `"INDUSTRY_MEDIAN"` / `"PEER_MEDIAN"` / `"USER_SPECIFIED"`
- `terminal_multiple_value`: required when `source == "USER_SPECIFIED"`.

---

## `TerminalMultipleScenario` (optional list at `ScenarioSet.terminal_multiple_scenarios`)

Lightweight cross-check scenarios priced against a terminal EV/EBITDA multiple rather than a full DCF projection. Useful as a sanity layer on top of Gordon-growth valuations.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Display label. |
| `probability` | `Decimal` | Sums to 1.00 ± 0.01 across the list (validated independently from the main scenarios). |
| `ev_ebitda` | `Decimal` | Terminal EV/EBITDA multiple. |

---

## `scenario_relevance` semantics (v1.1)

Used in `leading_indicators.yaml` (and reserved for future `capital_allocation.yaml` use). Mixes **generic buckets** and **specific names**:

```yaml
indicators:
  - name: eur_hkd_exchange_rate
    scenario_relevance: [BASE, BULL]          # generic — v1.1

  - name: prc_consumer_confidence
    scenario_relevance: [base, bear_prc_delay] # specific — v1.0 (still OK)

  - name: german_wage_growth
    scenario_relevance: [BEAR, bull_operational]  # mixed — both allowed
```

### Runtime expansion

`portfolio_thesis_engine.validation.scenario_cross_reference.expand_scenario_relevance` converts mixed input into a deduplicated, sorted list of **specific scenario names**:

- Bucket values expand to every scenario whose `resolved_bucket` matches.
- Specific names pass through if present in `scenario_set.scenarios`; unknown names are silently dropped (but flagged by `validate_scenario_cross_reference`).

### Non-blocking warnings

`validate_scenario_cross_reference(leading_indicators, scenario_set)` returns a list of warnings for any specific name that is **not** a bucket **and** is **not** in the loaded scenario set. The orchestrator logs these but does not block — analysts may have temporarily dropped a scenario.

---

## Example — minimal `scenarios.yaml`

```yaml
target_ticker: EXAMPLE.XX
valuation_profile: P1
base_year: FY2024
base_drivers:
  revenue:
    base_year_value: 1000000000
    growth_pattern: [0.10, 0.08, 0.06, 0.04, 0.03]
    fade_to_terminal_over_years: 5
    terminal_growth: 0.025
  operating_margin:
    current: 0.20
    target_terminal: 0.22
    fade_pattern: LINEAR
  tax_rate:
    statutory: 0.21
    effective_current: 0.24
    apply: STATUTORY
  capex_intensity:
    current: 0.06
    target: 0.04
  working_capital_intensity:
    current: 0.02
    target: 0.02
  depreciation_rate:
    current: 0.08
    target: 0.07
scenarios:
  - name: base
    probability: 0.50
    bucket: BASE              # v1.1 — explicit (optional, here for illustration)
    methodology:
      type: DCF_3_STAGE
      explicit_years: 5
      fade_years: 5
      terminal_method: GORDON_GROWTH
      terminal_growth: 0.025
    driver_overrides: {}
  - name: bull_operational
    probability: 0.30
    # bucket inferred → BULL
    methodology:
      type: DCF_3_STAGE
      explicit_years: 5
      fade_years: 5
      terminal_method: GORDON_GROWTH
      terminal_growth: 0.03
    driver_overrides:
      operating_margin:
        target_terminal: 0.26
  - name: bear_structural
    probability: 0.20
    methodology:
      type: DCF_2_STAGE
      explicit_years: 2
      fade_years: 0
      terminal_method: GORDON_GROWTH
      terminal_growth: 0.01
    driver_overrides:
      revenue:
        growth_pattern: [0.02, 0.02]
      operating_margin:
        current: 0.18
        target_terminal: 0.16
```
