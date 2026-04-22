# Phase 1.5.4 — Schema rigidity fixes

**Date:** 2026-04-22
**Scope:** micro-patch. Relax Pydantic `extra="forbid"` policy on
flexible containers; change `LineItem.source_note` type; fix
`inter_segment_eliminations` None handling. Core LineItem structure
+ walking-subtotals validator + Modules A/B/C unchanged.

## Motivation

Hugo's first real EuroEyes extraction via the Claude.ai Project
produced a 4288-line YAML with all 15+ arithmetic identities
holding. `pte validate-extraction` failed with **31 Pydantic
errors** — zero were content errors; all were schema rigidity:

- 23 × `extra_forbidden` — the extractor added useful fields
  (`metadata.source_file_name`,
  `total_comprehensive_income_attribution`, per-segment
  `source_note` / `reconciliation_to_group` / `extraction_caveat`,
  per-KPI `notes`) that the schema didn't allow.
- 5 × `int_parsing` on `source_note` — the extractor reported
  composite / sub-note identifiers (`"3.3, 35"`, `"29(d)"`,
  `"32(a)"`, `"38(b)"`) but `LineItem.source_note: int | None`
  rejected strings.
- 3 × `decimal_type` — segment `inter_segment_eliminations` had
  `null` values for metrics the company didn't eliminate against
  (`gross_profit: null`, `advertising_and_marketing: null`) but the
  type was `dict[str, Decimal]` (non-nullable).

The schema contradicted the catch-all philosophy: "capture what the
company reports; classify downstream" was blocked by model
rigidity.

## Changes

### A. `FlexibleSchema` base class

`src/portfolio_thesis_engine/schemas/base.py` — new base class with
`extra="allow"`. Docstring explains when to use it vs `BaseSchema`.

### B. Seven models switched from strict to flexible

Changed from `BaseSchema` to `FlexibleSchema`:

- `DocumentMetadata`
- `IncomeStatementPeriod`
- `BalanceSheetPeriod`
- `CashFlowPeriod`
- `Note`
- `SegmentReporting`
- `OperationalKPI`

Stayed strict (typos would lose data):

- `LineItem` — core structural row.
- `NoteTable` — columns/rows structure.
- `ProfitAttribution`, `EarningsPerShare` — standard footers.
- `FiscalPeriodData`, `SegmentMetrics`, `HistoricalDataSeries`,
  `GuidanceChangeItem`, `QAItem`, `NarrativeContent`.

Extras land on `model.model_extra`; they round-trip through
`to_yaml()` / `from_yaml()`.

### C. `LineItem.source_note: int → str`

Before: `source_note: int | None = Field(default=None, ge=0)`.
After: `source_note: str | None = None` with a `field_validator`
that coerces YAML-scalar ints (`source_note: 5`) to strings for
back-compat. Composite identifiers (`"3.3, 35"`, `"29(d)"`,
`"32(a)"`, `"38(b)"`) round-trip verbatim.

### D. `SegmentReporting.inter_segment_eliminations: dict[str, Decimal | None] | None`

Allows null values for metrics the company didn't eliminate against.

### E. Parser fix

`_scale_segment_reporting` now skips None values when applying the
unit-scale factor (was crashing with `TypeError: * between NoneType
and Decimal`).

### F. Real-YAML regression fixture

Copied Hugo's real 4288-line extraction to
`tests/fixtures/euroeyes/raw_extraction_real_claude_ai_2025.yaml`.
Added `TestParseRealClaudeAIFixture` in
`test_raw_extraction_parser.py` that asserts the Pydantic parse +
unit-scale normalisation succeed. Business-logic validation
(walking subtotals, BS identity) may still flag real issues in the
extraction — that's orthogonal to schema rigidity and covered by
the existing strict-tier tests.

### G. Tests added

- `TestLineItem.test_source_note_composite_string` — the five
  composite-identifier forms round-trip verbatim.
- `TestLineItem.test_source_note_int_coerced_to_str` — back-compat.
- `TestFlexibleContainers` class — 7 tests covering extras allowed
  on each flexible model, None values on segment metrics /
  eliminations, and confirmation that LineItem / NoteTable still
  reject extras.

### H. Docs updated

- `docs/raw_extraction_schema.md` — new section 13 documenting
  strict vs flexible configurations. `LineItem.source_note` updated
  to show string-with-coercion.
- `docs/claude_ai_extraction_guide.md` — new section 1b ("Flexible
  containers") flagging that extras are OK on containers and
  `source_note` is free-form string.

## Validation

- **Tests:** 783 passed (+12 from 771), 6 skipped. 94 % coverage.
  ruff + mypy --strict clean.
- **Real EuroEyes YAML:** `pte validate-extraction` now parses the
  4288-line extraction cleanly. Pydantic-level: **0 errors**. Tier
  summary: `strict=FAIL · warn=WARN · completeness=OK` — the strict
  FAILs are real business-logic walking-subtotals discrepancies
  (IS.SUB3/4/6/7 + BS.IDENTITY) in the extracted data, not schema
  rigidity. Hugo can now iterate on those without schema blocking.

## Invariants preserved

- **LineItem structure unchanged** — `order`, `label`, `value`,
  `is_subtotal`, `section`, `source_page`, `notes` remain strict.
- **Walking-subtotals validator unchanged.**
- **Modules A/B/C unchanged.** None of them read
  `source_note` / extras / `inter_segment_eliminations`.
- **No LLM calls.** Pipeline stays deterministic.

## Lines of change

Three source files (+47 / −11), two test files (+119 / −3), two
docs (+49 / −3), one report (this doc), and one 4288-line fixture
copy.
