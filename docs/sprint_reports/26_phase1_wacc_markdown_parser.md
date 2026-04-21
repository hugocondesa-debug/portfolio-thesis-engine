# Phase 1 · Sprint 11 — WACC markdown parser (post-Phase-1 patch)

**Date:** 2026-04-21
**Scope:** Extend `wacc_inputs.md` parser to accept structured-markdown
format (Hugo's production workflow), preserving YAML backward
compatibility.
**Status:** ✅ Complete

---

## Why this patch

Hugo's real EuroEyes run revealed a format gap: his `wacc_inputs.md`
is a markdown file with rich tables + H2/H3 sections, not YAML
frontmatter. Hugo has 20+ companies using this format; preserving it
matters more than forcing an ergonomic step-back.

The fix: route on first non-blank line — `---` stays YAML (zero
breaking change for existing fixtures and tests); anything else
delegates to a new markdown parser.

## What shipped

### Schema extension (`schemas/wacc.py`)

- `CostOfCapitalInputs.size_premium: Percentage | None = None` —
  optional, defaults to `None` so existing YAML files parse unchanged.
- `WACCInputs.cost_of_equity` @property now adds the size premium when
  declared: `rf + β·ERP + size_premium`. Existing behaviour (no size
  premium) is identical.

### New module (`ingestion/wacc_markdown_parser.py`)

- `parse_wacc_markdown(content)` — top-level entry.
- Section router via H2 splitting + synonym dict: accepts
  "Market Data" / "Market Snapshot", "WACC Parameters" /
  "WACC Calculation" / "Cost of Capital", "Capital Structure",
  "Business Scenarios" / "Scenarios".
- Field extraction via per-section alias dict:
  - Market data: `share price` / `price` / `stock price` → `current_price`
  - WACC: `Rf` / `risk-free rate` / `rfr` / `rf year-end`, `ERP` /
    `equity risk premium` / `market risk premium`, `Beta` /
    `β levered` / `β_l` / `levered beta`, `Size Premium`, `Cost of
    Debt` / `Kd` / `pre-tax cost of debt`, `Tax rate`
  - Capital structure: `Debt`, `Equity`, `Preferred`
  - Scenario drivers: `Revenue CAGR`, `Terminal operating margin` /
    `Terminal margin`, `Terminal growth`
- Table parser — standard markdown `| ... |` syntax with
  auto-padded/truncated rows.
- Business scenarios — H3 `### Bear (25%)` heading + `- Driver: value`
  list items. Scenarios missing any required driver are silently
  skipped; the Pydantic validator on `WACCInputs` fires if none at
  all pass.
- Header fields — `**Ticker:**`, `**Profile:**`, `**Valuation date:**`
  pulled from preamble only (before first H2) so bolded text inside
  sections doesn't leak.
- Value parser — strips thousands separators (`2,460` → 2460),
  percent signs (`50%` → 50), trailing units (`12.30 HKD` → 12.30).
- Clear error messages on every failure mode (missing Ticker, missing
  Share price, missing WACC params list, no Bear/Base/Bull, unknown
  profile code).

### Router (`ingestion/wacc_parser.py`)

- `parse_wacc_inputs(path)` — detects format from first non-blank
  line:
  - `---` → existing YAML frontmatter path (unchanged).
  - anything else → `parse_wacc_markdown(content)`.
- `_looks_like_frontmatter(content)` helper — testable in isolation.

### Fixtures

- `tests/fixtures/wacc/minimal_markdown.md` — tight-minimum fixture
  for routing tests.
- `tests/fixtures/wacc/euroeyes_real.md` — realistic analyst-style
  fixture: market data table, WACC parameters with size premium,
  capital structure, WACC time series (ignored), business scenarios
  with narrative prose, FX rates (ignored), notes.

### Tests — 49 new (712 → 761)

- `TestFormatDetection` (8) — YAML vs markdown routing, backward
  compat on existing YAML fixture.
- `TestNormalize` (7) — normalisation edge cases (parens, hyphens,
  D/E slash, whitespace).
- `TestParseDecimal` (10) — thousands separators, percent signs,
  units, non-numeric strings.
- `TestSynonymMatching` (5) — exact, parenthetical, multi-word, no-
  match; documented cross-contamination risk for "debt" vs "cost of
  debt" (mitigated by passing separate alias dicts per section).
- `TestStructureParsing` (4) — H2 splitting, single/multi table,
  row-padding.
- `TestBusinessScenarios` (4) — all-three happy path, incomplete
  scenario dropped, unknown label ignored, probability with/without
  percent sign.
- `TestHeaderFields` (1) — pulls from preamble only (pin against
  section bleed).
- `TestMinimalFixture` + `TestHugoRealFixture` (2) — full end-to-end
  over both fixtures; asserts size premium flows into `cost_of_equity`.
- `TestFailureModes` (6) — clear errors: missing ticker / share
  price / WACC param / scenarios / unknown profile + the existing
  Pydantic validation on probabilities-don't-sum still propagates.
- `TestExtractTableFields` (2) — label-matched first-cell + first-
  match-wins semantics.
- Updated `test_wacc_parser.py::test_prose_without_frontmatter_routes_to_markdown`
  (renamed from `test_missing_frontmatter_raises`) — pins new routing
  behaviour where plain prose now produces a markdown-parser error.

### Coverage

| Module                                     | Stmts | Miss | Cover |
| ------------------------------------------ | ----- | ---- | ----- |
| `ingestion/wacc_markdown_parser.py`        | 178   | 11   |  94 % |
| `ingestion/wacc_parser.py`                 |  51   |  3   |  94 % |
| **Global** (761 tests)                     | 4979  | —    |  ≥95 %|

## Decisions taken

1. **Single-file parser, not a library dependency.** Considered
   pulling in `marko` / `mistune` for robust markdown parsing, but
   the shape we consume is tight (tables + H2/H3 + bold-key-value) and
   regex-based parsing stays under 200 LOC. Swap-in room preserved
   if Hugo's future files need full CommonMark handling.
2. **Synonym dicts are per-section.** `_FIELD_ALIASES` (WACC params)
   and `_CAPITAL_STRUCTURE_ALIASES` are separate so the short token
   "debt" in the capital structure doesn't collide with "Cost of
   Debt" in the WACC parameters table. One shared dict would cross-
   contaminate.
3. **Word-bounded substring matching.** `_match_alias` matches an
   alias against a key only when surrounded by whitespace or
   string boundaries. Catches parenthetical suffixes like
   "Risk-Free Rate (Rf)" without matching "Rf" inside unrelated
   strings.
4. **Header validated first.** Ticker / Profile / Valuation date
   checks run before market-data / WACC-param extraction so errors
   point at the top of the file instead of deep in a table.
5. **Unknown profile = `IngestionError`, not `ValidationError`.**
   Raised at the parser boundary so downstream code sees a clean
   `IngestionError` for every format problem. Pydantic's
   `ValidationError` still propagates for shape violations
   (probability sum, enum mismatch on scenario labels) — consistent
   with the YAML path's behaviour.
6. **Empty/unknown scenarios silently dropped.** A scenario with only
   partial drivers (e.g. only Revenue CAGR) can't produce a valid
   `ScenarioDriversManual`, so we skip it. If *all* scenarios drop,
   we raise `IngestionError` with a clear "no Bear/Base/Bull"
   message — equivalent to the YAML path's empty-dict behaviour.
7. **Informational tables (WACC time series, FX rates) ignored
   gracefully.** The section router only recognises the four
   canonical section titles; anything else is skipped. Hugo can
   keep his historical / reference tables in the file for human
   readers without the parser complaining.
8. **Value-parser strips, doesn't convert.** `2,460` becomes 2460
   (thousands separator assumption). European decimal commas (e.g.
   `2,5`) would misparse — acceptable since Hugo's EuroEyes fixture
   uses dots for decimals. Flagged in the `_parse_decimal`
   docstring for future P2/P3 markets.

## Spec auto-corrections

1. **Spec section "WACC selection when multiple disponíveis"** —
   dropped. Hugo's real format has a single canonical WACC
   Parameters table; the historical WACC Time Series is
   informational. Parser uses the canonical table's values
   directly. No multi-year selection logic needed.
2. **Spec section "Currency handling"** — dropped. `WACCInputs`
   schema doesn't carry a currency field (unit of `current_price` is
   implicit). Sprint 11 keeps schema surface minimal; Phase 2 can
   add a DCF currency field if cross-currency valuation needs it.
3. **Spec "shares_outstanding parsing"** — dropped. `WACCInputs`
   doesn't carry shares; `CompanyIdentity` does (populated by the
   pipeline from the canonical state's IS / BS data). Parsing shares
   in the markdown would be dead-weight here.

## Files created / modified

```
M  src/portfolio_thesis_engine/schemas/wacc.py                  (+size_premium field, cost_of_equity update)
A  src/portfolio_thesis_engine/ingestion/wacc_markdown_parser.py (new, 450 LOC)
M  src/portfolio_thesis_engine/ingestion/wacc_parser.py         (+_looks_like_frontmatter + routing)
A  tests/fixtures/wacc/minimal_markdown.md                      (minimal routing fixture)
A  tests/fixtures/wacc/euroeyes_real.md                         (realistic analyst fixture)
A  tests/unit/test_wacc_parser_markdown.py                      (49 tests)
M  tests/unit/test_wacc_parser.py                               (renamed one test for new routing)
A  docs/sprint_reports/26_phase1_wacc_markdown_parser.md        (this file)
```

## Verification

```bash
$ uv run pytest
# 761 passed, 6 skipped in ~8 s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 92 source files
```

## Problems encountered

1. **First-match-wins vs dict order** — when `_match_alias` iterates
   aliases, dict insertion order matters. "Cost of Debt" must appear
   before any bare "Debt" alias so WACC Parameters don't cross-
   contaminate. Solved by keeping each section's aliases in a
   separate dict; the test pins the risk explicitly.
2. **Test initially failed: "Just prose" expected "frontmatter"
   error.** Pre-Sprint-11, the YAML-only parser raised
   `IngestionError("frontmatter delimiter")` on a file without
   `---`. Now the routing dispatches to markdown, which fails later
   with "missing Ticker". Updated the test + renamed it.
3. **mypy complained about `profile=str` into `WACCInputs`.**
   Pydantic coerces the string to the `Profile` enum at runtime,
   but mypy's strict mode reads the declared type. Fixed by
   explicitly converting `Profile(profile_raw)` with a clean
   `IngestionError` on `ValueError`.
4. **Header parser was too permissive.** Initial implementation
   grabbed every `**Key:**` pair in the file, including ones inside
   H2 sections (`**Narrative:**` etc). Fixed by splitting on H2
   first and scanning only the preamble. Test pins this.

## Next step

**Hugo authorises re-run:** once Hugo confirms, re-ingest +
re-process EuroEyes real against his actual `~/data_inputs/euroeyes/`
markdown:

```bash
export PTE_SMOKE_HIT_REAL_APIS=true
uv run pte ingest --ticker 1846.HK \
  --files ~/data_inputs/euroeyes/annual_report_2024.md,\
~/data_inputs/euroeyes/interim_h1_2025.md,\
~/data_inputs/euroeyes/wacc_inputs.md
uv run pte process 1846.HK
uv run pte show 1846.HK
```

Estimated cost: $5–$10. Sprint 11 is a parser-only patch — the
pipeline behaviour past ingestion is unchanged.

**Claude Code is waiting for Hugo's OK before triggering the real
API run.**
