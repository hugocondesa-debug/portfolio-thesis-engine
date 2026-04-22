# Phase 1.5.3 — Schema migration to as-reported structured

**Date:** 2026-04-22
**Scope:** major refactor — `RawExtraction` schema, parser, validator,
extraction modules, fixtures, tests, knowledge docs. Motivated by
observed classification-drift during real EuroEyes extraction.

## Motivation

First real EuroEyes extraction under the Phase 1.5.1 knowledge-base
reinforcement surfaced a structural problem the knowledge docs
couldn't fix alone:

- The Phase 1.5 schema had fixed typed fields on
  `IncomeStatementPeriod` (`revenue`, `cost_of_sales`,
  `selling_marketing`, `depreciation_amortization`, ...).
- Each typed field forced the extractor to **map** a reported line
  onto a predefined slot.
- Claude Opus decided to populate `depreciation_amortization` from
  Note 5 while D&A was already embedded in an aggregated opex line
  on the IS. Result: D&A counted twice, strict validator flagged a
  119 % IS-identity delta.
- The bug was schema-design: ANY mapping decision during extraction
  is a coin-flip. Either you remove the mappings or you ship
  double-counting bugs.

Hugo's framing: "estamos a usar Claude Opus para extraction — queremos
philosophy catch-all pura, não mapping administrativo". And: "não
fazemos comparables cross-company, logo schema fixo não tem valor
analítico".

## Decision

Migrate to an as-reported structured schema. Capture what the company
reports; classify 100 % downstream.

## Deliverables (Sprints A + B + C in commit `3a6232e`)

### Sprint A — Schema rewrite

**New types:**

- `LineItem(order, label, value, is_subtotal, section, source_note,
  source_page, notes)` — the atomic unit. `order` preserves reading
  order; `is_subtotal` marks subtotal lines; `section` groups BS/CF
  items (`current_assets`, `non_current_assets`, `total_assets`,
  `current_liabilities`, `non_current_liabilities`,
  `total_liabilities`, `equity`; `operating`, `investing`,
  `financing`, `fx_effect`, `subtotal`).
- `ProfitAttribution(parent, non_controlling_interests, total)`.
- `EarningsPerShare(basic_value, basic_unit, diluted_value,
  diluted_unit, basic_weighted_avg_shares, diluted_weighted_avg_shares,
  shares_unit)`.
- `NoteTable(table_label, columns, rows, unit_note)` — rows are
  `list[Any]`; numeric-string cells are coerced to `Decimal` by a
  field validator.
- `Note(note_number, title, source_pages, tables, narrative_summary)`.
- `SegmentMetrics`, `SegmentReporting`, `HistoricalDataSeries` (parallel
  arrays), `OperationalKPI` (free-form values, validator-coerced).

**Restructured:** `IncomeStatementPeriod`, `BalanceSheetPeriod`,
`CashFlowPeriod`, `RawExtraction`.

**Deleted:** 17 typed note classes (`TaxNote`, `LeaseNote`,
`ProvisionItem`, `GoodwillNote`, ...). `TaxItemClassification` +
`ProvisionClassification` closed enums. `SubsequentEventItem`,
`RelatedPartyItem`, `UnknownSectionItem`, `NotesContainer`.

**Metadata:** `fiscal_year` relaxed from required to optional.

**Parser rewrite:** walks `line_items` + `notes` + `segments` +
`historical` + `operational_kpis` for unit-scale normalisation.
Numeric-looking strings coerced to `Decimal` at schema-validation
time via `field_validator`s on `NoteTable` + `OperationalKPI`.

### Sprint B — Validator rewrite

Walking-subtotals approach:

- **S.IS.SUBn** — each IS subtotal verified against running sum of
  preceding non-subtotals. Running sum resets to the subtotal's
  reported value (waterfall semantics).
- **S.BS.<section>.SUBn** — per-section walks (current_assets /
  non_current_assets / equity / ...).
- **S.BS.IDENTITY** — `total_assets = total_liabilities +
  total_equity` (by label match on `is_subtotal` lines).
- **S.CF.<section>.SUBn** — per-section walks.
- **W.CF** — sum of CF section subtotals + fx = Δcash line.
- **W.CAPEX**, **W.DIV**, **W.SHARES**, **W.YOY** — adapted to
  label-match on line_items + EPS block.

Completeness checks now match note titles by regex (e.g.
`/income tax|taxation/` for the tax note, `/leases?\b/` for leases)
instead of checking typed-field presence. A note counts as
"populated" when it has at least one table OR a non-empty
`narrative_summary`.

### Sprint C — Modules rewrite

- **Module A (taxes)** — finds tax note by title-regex; parses
  reconciliation table rows; classifies each row locally by label
  keyword (non-op keywords: goodwill, impairment, disposal,
  restructuring, one-off, prior year, acquisition, settlement,
  litigation, discontinued, gain on, loss on). A.4 cash-taxes check
  scans CF for `/cash taxes paid|income taxes paid/`.
- **Module B (provisions & non-op)** — reads goodwill note movement
  table for impairment row; provisions note rows classified by
  keyword (restructuring, litigation, impairment, disposal,
  onerous contract, site closure); IS line-level non-op labels
  produce B.2.* adjustments.
- **Module C (leases)** — scans ROU + liability movement tables for
  additions / depreciation / interest / principal. Fallback
  identity: additions = closing − opening + |principal_payments|
  (abs to handle either sign convention).
- **AnalysisDeriver** — scans BS line_items by label + section for
  IC components; OI subtotal → NOPAT bridge anchor; non-op items
  from IS `share of associates` / `non-operating income` / etc.
- **Extraction coordinator** — passes line_items through verbatim
  to canonical `reclassified_statements`. BS subtotals filtered
  (double-count avoidance); CF subtotals filtered except Δcash
  anchor; IS subtotals preserved for display.
- **Guardrails** — extended `A.1.IS_CHECKSUM` label patterns
  (profit for the year, operating profit, profit before taxation);
  BS/CF checksums recognise new section-based categories.
- **Pipeline coordinator cross-check values** — read by label match.

### Sprint D (commit in progress)

- Rewrote `docs/raw_extraction_schema.md` for new schema.
- Updated `docs/claude_ai_extraction_guide.md` Pass 2 + Pass 3
  prompt templates for line_items + Note model; updated skeleton.
- Strengthened `docs/reference/catch_all_philosophy.md` with the
  EuroEyes D&A case study.
- Added Phase 1.5.3 pitfall groups G (`is_subtotal` flagging) and
  H (BS `section` assignment) to `common_pitfalls_library.md`.
- Updated `docs/reference/cross_statement_validation_checklist.md`
  for walking-subtotals approach.
- Updated `docs/guides/unknown_sections_protocol.md` (no dedicated
  bucket in the new schema).
- Archived Phase 1.5 fixtures as `*_legacy.yaml` with legacy marker.
- Primary fixture `tests/fixtures/euroeyes/raw_extraction.yaml`
  converted to the new schema (done in Sprint A+B+C commit).
- Updated integration test + pipeline-coordinator test for new
  methodology version (`phase1.5.3`).
- README + architecture doc reflect new schema.

## Validation

- **Test suite:** 771 passed, 6 skipped (same skip count as before).
- **Coverage:** **93 %** global (vs. 94 % pre-refactor — slight
  drop due to new validator's section-walk branches + the
  AnalysisDeriver regex paths not all hit by minimal fixtures).
- **Ruff:** clean.
- **Mypy --strict:** no issues in 91 source files.
- **Fixture validation:** `pte validate-extraction
  tests/fixtures/euroeyes/raw_extraction.yaml --profile P1` →
  `strict=OK · warn=OK · completeness=WARN` (missing `acquisitions`
  note — recommended not required; acceptable).

## Metrics before / after

| Metric                                           | Before (1.5.1) | After (1.5.3) |
| ------------------------------------------------ | -------------- | -------------- |
| `raw_extraction.py` LOC                          | ~670           | ~400           |
| Typed note classes                               | 17             | 0 (all → `Note`) |
| Closed classification enums                      | 3              | 0              |
| Schema validator                                 | Typed-field driven | Walking subtotals |
| Test count                                       | 832            | 771 (denser)   |
| Global coverage                                  | 94 %           | 93 %           |

Net LOC across all touched files (commit `3a6232e`): **−103 lines**
(+4037 / −4140) — schema + validator + modules are now simpler, and
the test files became more focused.

## Architectural wins

1. **Extraction = facts.** The schema matches what the company
   printed; no mapping decisions required.
2. **Classification = downstream.** Modules A/B/C own all the
   classification logic. Changing a classification rule means
   editing one module and re-running the pipeline — no
   re-extraction needed.
3. **Walker-agnostic validation.** The walking-subtotals validator
   doesn't care whether the company calls a line "Selling expenses"
   or "Distribution costs" or "SG&A" — it just verifies the
   printed subtotals walk from the printed leaves.
4. **Cheaper iteration on module rules.** When a new sector surfaces
   a novel label, we update the module regex without touching the
   schema or past extractions.

## Migration notes — Phase 1.5 → 1.5.3

For any existing `raw_extraction.yaml` on the Phase 1.5 schema:

1. Each typed IS field → one `LineItem` (the running walk naturally
   orders them).
2. Subtotal fields (`gross_profit`, `operating_income`, `net_income`,
   `total_assets`, `total_equity`) → `LineItem` with
   `is_subtotal: true`.
3. Each typed note (`notes.taxes`, `notes.leases`, ...) → one `Note`
   entry with `tables` carrying what used to be typed sub-fields.
4. `classification` fields on tax/provision items → gone. Capture
   the row label verbatim; module classifies.
5. `segments.by_geography` dict-of-dict → list of `SegmentReporting`
   with `segment_type: "geography"`.
6. `historical.*_by_year` dicts → `HistoricalDataSeries` parallel
   arrays.
7. `operational_kpis.metrics` dict → list of `OperationalKPI`.

Legacy fixtures archived at
`tests/fixtures/euroeyes/raw_extraction_{ar_2024,interim_h1_2025}_legacy.yaml`
for reference.

## What's next

Phase 1.5.3 closes the extraction boundary. Phase 2 starts with a
clean schema and a classification layer that can iterate
independently of extraction. First item on deck: multi-period
`AnalysisDeriver` (CAGRs, DuPont, capital allocation) — now much
simpler because every period's line_items are self-describing.
