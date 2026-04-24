# New Ticker Onboarding Workflow

**Target audience**: analyst onboarding a new company into PTE.
**Estimated time**: 3–6 hours depending on complexity, not counting Claude.ai generation turnarounds.
**Prerequisites**: audited annual report, investor-relations materials, access to the shared Claude.ai Project.

This is the full playbook from *raw PDF* to *published ficha with forward projections*. For quick-start CLI syntax see [`docs/reference/cli_reference.md`](../reference/cli_reference.md).

---

## Overview

Phase 0 gathers documents (manual). Phases 1–2 are PTE automation. Phases 3–6 are analyst-driven scenario design. Phase 7 produces the full valuation. Phase 8 writes up the thesis.

```
Phase 0  →  Phase 1  →  Phase 2  →  Phase 3  →  Phase 4  →  Phase 5  →  Phase 6  →  Phase 7  →  Phase 8
Gather      Extract     Process     Briefing    Scenarios  Capital     Indicators  Valuation   Thesis
docs        yaml        baseline                            allocation                          writeup
```

---

## Phase 0 — Document gathering (30–60 min)

Collect:

1. **Audited annual reports** — most recent 3–5 years, PDF.
2. **Interim reports** (H1, quarterly) — optional but useful for trend validation.
3. **Investor presentations** — management guidance for scenario seeding.
4. **Sustainability / ESG reports** — when relevant.
5. **Bond prospectuses** — for debt structure when the company uses leverage.

Save under `~/data_inputs/<ticker>/`. Prefix filenames with the period label (`ar_2024.pdf`, `interim_h1_2025.pdf`) for easy downstream matching.

---

## Phase 1 — Extraction (60–120 min)

Purpose: convert PDFs into structured `raw_extraction.yaml`. See [`docs/claude_ai_extraction_guide.md`](../claude_ai_extraction_guide.md) for the Claude.ai prompt flow.

Steps:

1. Upload documents to the Claude.ai Project.
2. Run the extraction prompt for the primary period (typically latest audited year).
3. Download the generated yaml; review for completeness (especially notes / footnotes needed for Module D decomposition).
4. Save as `~/data_inputs/<ticker>/raw_extraction_<period>.yaml`.
5. Also assemble `wacc_inputs.md` (geographic mix table, credit-rating inputs, current_price, tax rates) under `~/data_inputs/<ticker>/wacc_inputs/wacc_inputs.md`.

**Sanity check**:

```bash
uv run pte validate-extraction ~/data_inputs/<ticker>/raw_extraction_<period>.yaml --profile P1
```

Fix any strict-validator issues before moving on.

---

## Phase 2 — Initial processing (10–30 min)

Register documents and run the pipeline end-to-end:

```bash
uv run pte ingest -t <TICKER> -e ~/data_inputs/<TICKER>/raw_extraction_<period>.yaml
uv run pte process <TICKER> --base-period <period>
```

Expected output:

- All 12 stages complete with status `ok` (guardrails may emit `warn`).
- Canonical state persisted under `data/yamls/companies/<ticker>/extraction/`.
- Cross-check: `PASS` / `WARN` for the latest audited year. If `FAIL`, review `data/logs/cross_check/<ticker>_<timestamp>.json` and decide whether it's a legitimate discrepancy or an extraction error.

**Historical years** (FY2021, FY2022, ...) now work without `--skip-cross-check` — Sprint 4A-alpha.7's period-aware fix routes providers by fiscal year.

---

## Phase 3 — Analytical briefing (15–30 min)

Generate the analyst brief to understand the business:

```bash
uv run pte briefing <TICKER> --purpose full --output-stdout
```

Review:

- Cost structure decomposition.
- Margin trajectory across years.
- Working capital dynamics.
- M&A history and goodwill progression.
- Leading indicators resolved against current sector environment.

This is the input to the next two phases — the briefing is what you feed into the Claude.ai Project to seed scenario generation.

---

## Phase 4 — Scenario design (45–90 min)

**Highest-value analyst work.** Produce `scenarios.yaml` with 4–7 scenarios:

- **Base** — management guidance or analyst mid-case.
- **1–2 Bull** — operational upside, re-rating, M&A acceleration.
- **1–2 Bear** — structural compression, cyclical delay.
- **1 Tail** — takeover floor, fire sale, black swan.

Schema reference: [`docs/schemas/scenarios_schema.md`](../schemas/scenarios_schema.md). Two recent conveniences (v1.1):

- **Explicit bucket** — `bucket: BASE / BULL / BEAR / TAIL` is optional; inference handles `base*` / `bull*` / `bear*` / `takeover_*` / `m_and_a_accelerated` automatically. Override only when the name doesn't disambiguate.
- **Input aliases** (v1.1.1) — `target:` as shorthand for `target_terminal:`, `fade_to_terminal_over_years: int` as shorthand for the explicit `fade_pattern` shape field. Both are input-only; serialisation remains canonical.

Steps:

1. Use the Claude.ai Project `scenarios_generate` prompt with the Phase 3 briefing.
2. Review the generated yaml against the schema doc.
3. Validate probabilities sum to 1.00 ± 0.01 (plus a separate `terminal_multiple_scenarios` block if you use that cross-check layer).
4. Copy to `data/yamls/companies/<TICKER>/scenarios.yaml`.

**Common pitfalls**:

- `m_and_a_accelerated` defaults to `BULL` bucket — verify that's what you intend.
- Unknown name prefix also defaults to `BULL` with a warning in the cross-reference validator; add an explicit `bucket:` to silence.

---

## Phase 5 — Capital allocation (30–45 min)

Define the company's capital-deployment policy. Schema: [`docs/schemas/capital_allocation_schema.md`](../schemas/capital_allocation_schema.md).

Decide:

- **Dividend** — `ZERO`, `FIXED_AMOUNT`, `PAYOUT_RATIO`, `GROWTH_PATTERN`, `CONDITIONAL`.
- **Buyback** — `NONE`, `FIXED_ANNUAL`, `PROGRAMMATIC`, `CONDITIONAL`.
- **Debt** — `MAINTAIN_ZERO`, `MAINTAIN_CURRENT`, `REPAY`, `TARGET_RATIO` (4B.2), `LEVER_UP` (4B.2 wiring; `alternative_for_ma` hook available today).
- **M&A** — `NONE`, `OPPORTUNISTIC`, `PROGRAMMATIC`, `ACQUIRE_ONLY` / `SELL_ONLY`.
- **Funding source** — `CASH`, `DEBT`, `MIXED` (governs `LEVER_UP` firing — cash-funded M&A does **not** trigger leverage).
- **Share issuance** — `ZERO`, `OPPORTUNISTIC`, `DILUTIVE_PROGRAM`.

Save to `data/yamls/companies/<TICKER>/capital_allocation.yaml`.

---

## Phase 6 — Leading indicators (15–30 min)

Define 5–10 sector-specific leading indicators. Schema: [`docs/schemas/leading_indicators_schema_reference.md`](../schemas/leading_indicators_schema_reference.md) and the v1.1 updates in [`scenarios_schema.md`](../schemas/scenarios_schema.md#scenario_relevance-semantics-v11).

Use **generic buckets** (`scenario_relevance: [BULL, BEAR]`) wherever possible — avoids manual sync when scenarios are added or renamed later. Specific names still work for precise mapping.

Save to `data/yamls/companies/<TICKER>/leading_indicators.yaml`.

---

## Phase 7 — Full valuation (5–10 min)

Re-run the pipeline plus the Phase 2 outputs:

```bash
uv run pte process <TICKER>
uv run pte valuation <TICKER>
uv run pte forecast <TICKER>
```

Review:

- `pte valuation` — table of scenarios, methodology, fair value / share, expected value, P25 / P75, implied upside.
- `pte forecast` — per-scenario three-statement projection + forward ratios (PER, FCF yield, ROIC, ROE, WACC).
- Solver convergence — every scenario should report `converged: true` in `solver_convergence`. Non-converged scenarios still return (last-iteration values + warning) but warrant a review.

Persisted artefacts:

- Valuation snapshot: `data/yamls/companies/<ticker>/valuation/<ticker>_<timestamp>.yaml`.
- Forecast snapshot: `data/forecast_snapshots/<ticker>/<ticker>_<timestamp>.json`. Schema: [`forecast_snapshots_schema.md`](../schemas/forecast_snapshots_schema.md).
- Cross-check log: `data/logs/cross_check/<ticker>_<timestamp>.json`.

---

## Phase 8 — Thesis writeup (15–30 min)

Consume the ficha:

```bash
uv run pte show <TICKER> --narrative --detail
```

Cross-check:

- Expected value vs market price — implied upside plausible vs the narrative?
- P25 / P75 range — reasonable given scenario probabilities?
- WACC evolution per scenario — does leverage-up scenario actually lower WACC?

Export markdown for archival / portfolio review:

```bash
uv run pte valuation <TICKER> --export ~/thesis_notes/<TICKER>_valuation.md
uv run pte forecast <TICKER> --export ~/thesis_notes/<TICKER>_forecast.md
```

---

## Common pitfalls

- **Period mismatch on cross-check**. Post Sprint 4A-alpha.7 you should not need `--skip-cross-check` for FY2021+ historical extractions. If you see the old "FY2024 override" behaviour, confirm you're on tag `v0.9.3+`.
- **Bucket default surprises**. `m_and_a_accelerated` → `BULL`; any unrecognised name → `BULL`. Always inspect `pte show <ticker> --detail` before trusting the cross-reference expansion.
- **Funding source left at `CASH` when scenario intends debt-funded M&A**. `LEVER_UP` only fires when `ma_policy.funding_source ∈ {DEBT, MIXED}` — a common Phase 5 oversight.
- **Decimal precision in hand-edited yamls**. PyYAML parses `0.23` as `float`; PTE coerces to `Decimal(str(x))`. If you need exact string Decimal, quote it: `target_terminal: "0.2325"`.
- **Solver non-convergence on stressed bears**. When a bear scenario produces deep negative free cash, the solver may not settle in 20 iterations. Inspect `projection.warnings[]`; adjust `fade_to_terminal_over_years` or re-seed `current` / `target_terminal` to smooth the path.

---

## Related references

- Architecture: [`../phase2_architecture.md`](../phase2_architecture.md)
- CLI reference: [`../reference/cli_reference.md`](../reference/cli_reference.md)
- Scenarios schema: [`../schemas/scenarios_schema.md`](../schemas/scenarios_schema.md)
- Capital allocation schema: [`../schemas/capital_allocation_schema.md`](../schemas/capital_allocation_schema.md)
- Leading indicators schema: [`../schemas/leading_indicators_schema_reference.md`](../schemas/leading_indicators_schema_reference.md)
- Forecast snapshot schema: [`../schemas/forecast_snapshots_schema.md`](../schemas/forecast_snapshots_schema.md)
- Phase 1 architecture: [`../phase1_architecture.md`](../phase1_architecture.md)
- Raw extraction schema: [`../raw_extraction_schema.md`](../raw_extraction_schema.md)
- Claude.ai extraction prompt guide: [`../claude_ai_extraction_guide.md`](../claude_ai_extraction_guide.md)
