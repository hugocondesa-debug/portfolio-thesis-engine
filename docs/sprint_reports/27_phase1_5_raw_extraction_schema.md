# Phase 1.5 · Sprint 1 — RawExtraction schema + parser

**Date:** 2026-04-21
**Scope:** Establish the human/Claude.ai → system boundary as a typed
YAML schema. Sprint 2+ will gut the in-app section extractor and wire
the pipeline onto this new input.
**Status:** ✅ Complete

---

## Why this pivot

The Phase 1 real EuroEyes run (Sprint 10 / 11) exposed a hard ceiling
on in-app LLM-driven extraction: the section extractor hallucinated
numerical values (Revenue = 580 when the AR clearly says 715,682).
300+ page annual reports chunked through a TOC-then-parse LLM loop
lose line-level accuracy no matter how tight the prompts get.

Hugo's pivot: do extraction **outside** the app, with Claude.ai as a
reading co-pilot and line-by-line human validation. The app consumes
a structured, schema-validated YAML (`raw_extraction.yaml`) as the
source of truth for every numerical value. Reclassification,
valuation, ficha, and guardrails remain in-app and deterministic.

This is a win on accuracy (human in the loop catches every
hallucination), cost (one $5 Claude.ai subscription vs $5–$10 per
process-run), and replay (the YAML is the artefact of record —
pipeline re-runs are free).

## What shipped

### `schemas/common.py` — two tiny additions

```python
ISODate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Ticker  = Annotated[str, Field(min_length=1, max_length=20)]
```

Non-breaking. Existing call sites (`CompanyIdentity.ticker: str = Field(...)`
etc.) still work; future schemas can adopt the aliases. Kept
as `Annotated[str, ...]` instead of `datetime.date` / a new class so
YAML round-trip stays predictable (PyYAML's auto-date parsing is a
known sharp edge — we already worked around it in Sprint 1).

### `schemas/raw_extraction.py` — 156 statements, 100 % covered

Top-level `RawExtraction` with:

- **Identity** — `ticker`, `company_name`, `reporting_currency`,
  `unit_scale ∈ {"units", "thousands", "millions"}`,
  `extraction_date` (ISO), `source` (free text describing which
  filings were read), `extractor` (default
  `"Claude.ai + human validation"`).
- **`fiscal_periods: list[FiscalPeriodData]`** — one per period
  extracted. Each carries `period` label, `end_date`, `is_primary`.
- **`income_statement / balance_sheet / cash_flow: dict[str, *Period]`**
  keyed by period label. Every line is `Decimal | None` so partial
  disclosures (interim with no CF) parse cleanly.
- **`notes: Notes`** — `TaxNote` (with `reconciling_items` list
  classified as `operational / non_operational / one_time / unknown`),
  `LeaseNote` (full IFRS 16 movement table), `provisions:
  list[ProvisionItem]` classified as `operating / non_operating /
  restructuring / impairment / other`, plus an `extensions` dict
  for notes the Phase 1 pipeline doesn't consume (goodwill
  impairment, SBC, pensions — waiting for Phase 2 modules).
- **`segments: Segments | None`** — `by_geography` / `by_product` /
  `by_business_line`, each `dict[period, dict[segment_name, Decimal]]`.
- **`historical: HistoricalData | None`** — multi-year time series
  for revenue / NI / total_assets / total_equity + extensions,
  reserved for Phase 2 CAGR / capital-allocation views.

Validator `validate_completeness` enforces:

- At least one fiscal period.
- At most one period flagged `is_primary` (0 = use first entry).
- IS + BS present for the primary period. (CF optional — interim
  reports often omit it.)

Convenience properties `primary_period`, `primary_is`, `primary_bs`,
`primary_cf` let modules read the anchor-period data without
re-implementing the lookup.

### `ingestion/raw_extraction_parser.py` — 19 stmts, 89 % covered

`parse_raw_extraction(path) → RawExtraction`. Wraps three failure
modes as `IngestionError`: file-not-found, YAML syntax error
(`yaml.YAMLError`), schema validation (`ValidationError`). The two
uncovered lines are the OS-level read-error branch — kept as a
defensive arm.

### `tests/fixtures/euroeyes/raw_extraction.yaml`

Full realistic fixture: 2 fiscal periods (FY2024 + H1 2025), IS/BS/CF
populated (CF for FY2024 only — interim omits it), notes with 4
tax-reconciliation items + full lease disclosure + 2 provisions,
segments by geography, 5-year revenue + NI historical series. This
replaces the Phase 1 markdown fixtures for the pipeline; Sprint 2
will delete `annual_report_2024_minimal.md` /
`interim_h1_2025_minimal.md` once the section extractor is gone.

### Tests — 57 new (761 → 818)

- **`test_raw_extraction_schema.py`** (45) — happy path, Decimal
  precision round-trip (`100.123456789`), required-field enforcement
  (9 parametrised cases), completeness validator (empty periods, IS
  missing, BS missing, two primaries, no primary → first, CF
  optional), statement schemas (all optional + extensions), notes
  (tax reconciling items + classifications + bad enum), leases,
  provisions, segments, historical, convenience accessors.
- **`test_raw_extraction_parser.py`** (12) — real EuroEyes fixture
  parses (7 tests covering identity, periods, statements, notes,
  segments, historical), error paths (missing file, invalid YAML,
  schema violation, non-dict YAML), YAML round-trip.

## Decisions taken

1. **Schema-first, parser-thin.** All validation lives in Pydantic;
   the parser is a 19-line wrapper that translates three exception
   types into `IngestionError`. Adding a new field in the future
   means editing one file, not two.
2. **Every numerical field is `Decimal | None`.** Partial reports
   (interim with no CF, notes missing) parse without errors; the
   guardrails in the pipeline raise WARN when a specific field is
   `None` downstream. Schema validation only catches *wrong* data,
   not *missing* data.
3. **`is_primary` is a boolean per period, not an enum.** Alternative
   was a top-level `primary_period: str` pointer. The boolean is
   read-local (you see on the period row itself whether it's primary)
   and the validator still enforces 0-or-1 semantics.
4. **`cash_flow` dict is optional but statements dicts aren't.** IS
   and BS are required for every well-formed extraction; CF is the
   one statement that interim reports routinely omit. The
   completeness validator reflects that distinction.
5. **`extensions: dict[...]` on every statement + on Notes.** Lets
   Hugo add company-specific lines (R&D, government grants, share
   of associates profit, etc.) without schema edits. The Phase 1
   modules don't consume extensions; Phase 2 can selectively
   promote heavily-used extensions to first-class fields.
6. **Tax / provision classifications as `Literal`, not free strings.**
   Module A (taxes) + Module B (provisions) need a stable finite
   enum to branch on. If a classification is uncertain at extraction
   time, use `"unknown"` / `"other"` — the module then applies
   heuristics.
7. **`Segments` + `HistoricalData` kept on the same schema** instead
   of side files. Hugo produces one YAML per company per extraction
   date; keeping everything together makes the extraction boundary
   a single artefact.
8. **ISODate + Ticker as `Annotated[str, ...]`, not new classes.**
   Keeps them implicitly compatible with existing `str`-typed call
   sites; no migration tax elsewhere. The Pydantic validator still
   enforces format.
9. **Dead-code pruning on the parser.** Initial cut had an
   `except ValueError` branch for non-dict YAML — but BaseSchema's
   `from_yaml` routes that case through `ValidationError`, so the
   branch was unreachable. Deleted; coverage went from 81 % to 89 %
   with no behavioural change.

## Files created / modified

```
M  src/portfolio_thesis_engine/schemas/common.py              (+ISODate, +Ticker aliases)
A  src/portfolio_thesis_engine/schemas/raw_extraction.py      (new, 156 stmts, 100 % cov)
A  src/portfolio_thesis_engine/ingestion/raw_extraction_parser.py (new, 19 stmts, 89 % cov)
A  tests/fixtures/euroeyes/raw_extraction.yaml                (realistic 2-period fixture)
A  tests/unit/test_raw_extraction_schema.py                   (45 tests)
A  tests/unit/test_raw_extraction_parser.py                   (12 tests)
A  docs/sprint_reports/27_phase1_5_raw_extraction_schema.md   (this file)
```

## Verification

```bash
$ uv run pytest
# 818 passed, 6 skipped in ~8 s  (761 → 818, +57)

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 94 source files
```

## Coverage on new code

| Module                                                   | Stmts | Miss | Cover |
| -------------------------------------------------------- | ----- | ---- | ----- |
| `schemas/raw_extraction.py`                              | 156   |  0   | 100 % |
| `ingestion/raw_extraction_parser.py`                     |  19   |  2   |  89 % |
| **Sprint 1 subtotal**                                    | 175   |  2   |  99 % |

The 2 uncovered lines on the parser are the `UnicodeDecodeError /
OSError` branch on `read_text()` — defensive arm that's hard to
trigger portably. Target was ≥95 %; delivered 99 %.

## Cost estimate

$0 this sprint (schema + parser work — no LLM calls, no external
APIs). All subsequent Hugo runs will cost pure Claude.ai subscription
(flat $20/month for the editor workflow); in-app LLM cost per
company drops to near-zero since the cross-check gate is the only
remaining API consumer and it hits FMP + yfinance (flat-fee + free).

## Problems encountered

1. **YAML parser error path** — first iteration wrapped
   `yaml.safe_load` errors as `ValueError`, but PyYAML raises
   `yaml.YAMLError` (specifically `ParserError`), which isn't a
   `ValueError` subclass. Added an explicit `except yaml.YAMLError`
   branch; test coverage confirmed the wiring.
2. **Dead `except ValueError` branch.** BaseSchema's `from_yaml`
   routes non-dict YAML through `model_validate` → `ValidationError`,
   not `ValueError`. The defensive branch was unreachable; deleted
   it to keep the parser honest about what it handles.
3. **Pydantic v2 + `from __future__ import annotations`** — the
   model_validator return-type `-> RawExtraction` needed the
   `__future__` import to avoid a forward-ref warning. Added at the
   top of every new file.

## Sprint 1 close — what the new boundary looks like

```
┌──────────────────────────────────────────────────────────┐
│  OUTSIDE THE APP (Hugo + Claude.ai)                      │
│                                                          │
│   PDF Annual Report ──┐                                  │
│                       ├──► raw_extraction.yaml           │
│   PDF Interim Report ─┘   (validated Pydantic schema)    │
│                                                          │
│   wacc_inputs.md (Hugo's markdown, Sprint 11 parser)     │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  INSIDE THE APP (deterministic pipeline, Phase 1.5)      │
│                                                          │
│   pte ingest  ──►  register docs + raw_extraction.yaml  │
│   pte process ──►  load_extraction → cross_check →      │
│                    extract_canonical → persist →        │
│                    guardrails → valuate → persist_val → │
│                    compose_ficha                         │
│   pte show    ──►  FichaBundle → Rich / JSON            │
│   Streamlit UI ─►  FichaBundle → dashboard              │
└──────────────────────────────────────────────────────────┘
```

The schema + parser are the new **stable boundary**. Sprint 2 rips
out the section extractor + wires the pipeline onto
`parse_raw_extraction`; Sprint 3 refactors Modules A/B/C to consume
`RawExtraction` directly; Sprint 4 ships the
`pte validate-extraction` CLI + the Claude.ai extraction guide + the
final doc refresh.

## Next step

**Sprint 2 (Fase 1.5)** — kill `section_extractor/` package + kill
its 3 test files + kill pipeline's `SECTION_EXTRACT` stage + add
`LOAD_EXTRACTION` stage consuming `parse_raw_extraction`. Delete the
minimal markdown fixtures. Estimated 1–2h. No further schema change
needed — the boundary is set.
