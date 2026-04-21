# Phase 1 · Sprint 3 — Section Extractor Pass 2 (per-section parsing)

**Date:** 2026-04-21
**Phase 1 Step (Parte K):** 3 — Pass 2
**Status:** ✅ Complete

---

## What was done

Pass 2 now turns each identified section into structured data via one
LLM tool-use call per section, parallelised:

- **`section_extractor/tools.py`** extended with 7 tool definitions —
  `extract_income_statement`, `extract_balance_sheet`,
  `extract_cash_flow`, `extract_segments`, `extract_leases_disclosure`,
  `extract_tax_reconciliation`, `extract_mda_narrative` — each with a
  statement-specific `category` enum, a consistent `currency_unit` enum
  (`units/thousands/millions/billions`), and a shared
  `_line_item_schema(category_enum)` helper to cut repetition. Added
  `SECTION_TOOLS: dict[section_type → (tool_def, operation_name)]` as
  the dispatch table.
- **`section_extractor/prompts.py`** extended with `_FINSTMT_COMMON_RULES`
  shared preamble plus seven per-section system prompts. Each prompt
  enforces sign conventions (parentheses → negative), scale handling
  (don't rescale — capture scale in `currency_unit`), label
  normalisation hints, and tool-use exclusivity (no prose commentary).
  `SECTION_SYSTEM_PROMPTS` is the prompt-dispatch table;
  `SECTION_USER_PROMPT_TEMPLATE` wraps the section content with
  `<section title="…" fiscal_period="…">…</section>` XML fencing.
- **`section_extractor/p1_extractor.py`** now runs Pass 2 after Pass 1:
  - `_parse_sections(...)` iterates with `asyncio.gather` bounded by an
    `asyncio.Semaphore(max_concurrent)` (default 5) — preserves input
    order, respects rate limits.
  - `_extract_section_content(...)` handles a single section: builds
    the tool definition, formats the user prompt, issues the call,
    records cost under the section-specific `operation` name (e.g.
    `section_parse_is`), returns `structured_output`.
  - Sections without a `SECTION_TOOLS` entry pass through unchanged
    with `parsed_data=None`.
  - `_enforce_cost_cap(...)` raises `CostLimitExceededError` before
    Pass 1 and before Pass 2 kicks in; coarse-grained per Hugo's
    decision (stage-level, not per-call).
- **`tests/unit/test_section_parsers.py`** — 13 new tests. Dispatch
  table shape, happy-path parse of all 7 sections, parallel-call count
  (1 TOC + 7 Pass 2 = 8), per-operation cost tracking, passthrough for
  unknown section types, graceful handling of `structured_output=None`,
  bounded-concurrency semaphore enforcement, cost-cap raised before any
  LLM call, content-preservation + stable ordering after
  `asyncio.gather`.
- **Sprint 2 tests regression-fixed.** `_mock_llm` now dispatches by
  tool name (TOC → provided response; Pass 2 → empty
  `structured_output`) so the 19 Sprint 2 tests continue to pass
  unchanged after Pass 2 always runs.

## Decisions taken

1. **Dispatch table (`SECTION_TOOLS`) instead of `if/elif`.** Adding a
   new parseable section type is a one-line change in the table. Tests
   assert the table covers the 7 expected types so regressions show up
   immediately.
2. **Per-statement `category` enums**, not a shared generic one. IS,
   BS, CF each have different categories (`revenue` / `operating_income`
   for IS; `total_assets` / `lease_liabilities` for BS; `cfo` / `capex`
   for CF). Hard enum prevents the LLM from inventing categories the
   downstream extraction modules don't know how to handle.
3. **Line items require `category` in the schema.** Sprint 2's base
   schema left it optional; tightening to `required` means Sprint 4
   validators can compute checksums by filtering on categories without
   string heuristics.
4. **Bounded concurrency with `asyncio.Semaphore(max_concurrent)`**
   rather than chunking the list. Simpler (no batch bookkeeping) and
   composes naturally with `asyncio.gather`. Dedicated test records
   peak concurrency with simulated latency; asserts `peak <= 2` when
   `max_concurrent=2`.
5. **Per-section cost tracking via distinct `operation` names.** Cost
   reports can be filtered by operation (`section_parse_is`,
   `section_parse_bs`, etc). Useful for spotting which sections run
   long or expensive on real data.
6. **Passthrough for unknown section types.** A section with
   `section_type` not in `SECTION_TOOLS` (e.g. `operating_data`, `esg`,
   `other`) is returned unchanged with `parsed_data=None`. Costs
   nothing, doesn't trigger extra LLM calls. Sprint 4 validator can
   flag it as INFO.
7. **`asyncio.gather` preserves input order.** Downstream extraction
   modules (Modules A/B/C) iterate sections in document order;
   parallelisation shouldn't disturb that. Dedicated test pins this
   behaviour.
8. **Cost cap is coarse-grained — checked per stage.** Hugo decided
   this in the batch kickoff (per-stage granularity). Two checks:
   once before Pass 1, once before Pass 2. Pre-Pass-2 check is
   important because Pass 2 fans out — catching "already over budget"
   early avoids burning a bunch of concurrent calls.
9. **Shared `_FINSTMT_COMMON_RULES` in prompts.** Hugo's rule "prompts
   in separate files" rewards factoring the common rules so future
   tweaks don't require updating seven prompts. Per-section prompts
   still add their own specifics (BS subtotals, CF net-change
   requirement, etc).
10. **XML-style fencing in user prompt** (`<section title="…">…</section>`).
    Gives the LLM a stable marker to separate instructions from the
    payload content. Reduces the chance of the section content
    accidentally matching a prompt phrase.

## Spec auto-corrections

1. **Spec C.6 showed one IS tool schema.** Extended to seven tools per
   Hugo's Sprint 3 brief. Each tool has its own category enum (spec's
   IS enum was adopted verbatim; BS/CF/others built fresh).
2. **Spec C.7 spec'd a single `INCOME_STATEMENT_EXTRACTION_PROMPT`.**
   Factored the repeated sign / scale / tool-use rules into
   `_FINSTMT_COMMON_RULES` so all seven prompts stay consistent. Saves
   ~40 lines per prompt and keeps the delta review-focused.
3. **No `value_prior` requirement on line items.** Spec made prior-year
   optional; kept that way. Sprint 4 validators will only require
   current-period values for checksums.

## Files created / modified

```
M  src/portfolio_thesis_engine/section_extractor/tools.py    (+7 Pass 2 tools + dispatch)
M  src/portfolio_thesis_engine/section_extractor/prompts.py  (+7 prompts + dispatch)
M  src/portfolio_thesis_engine/section_extractor/p1_extractor.py
                                                (+_parse_sections, +_extract_section_content,
                                                 +_enforce_cost_cap, Pass 2 wired into extract)
A  tests/unit/test_section_parsers.py                        (13 tests)
M  tests/unit/test_section_toc.py                            (dispatcher mock for Pass 2)
A  docs/sprint_reports/18_phase1_section_extractor_parsers.md  (this file)
```

## Verification

```bash
$ uv run pytest
# 464 passed, 4 skipped in 12.21s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 59 source files
```

Concurrency test evidence: with `max_concurrent=2` and simulated 20 ms
LLM latency across 7 parseable sections, observed peak in-flight calls
never exceeded 2. Pass 2 also records 7 distinct operations in the
`CostTracker.session_entries` — one per section type.

## Tests passing / failing + coverage

All 464 unit tests pass; 4 integration tests skipped (gated).

| Sprint 3 module                            | Stmts | Miss | Cover |
| ------------------------------------------ | ----- | ---- | ----- |
| `section_extractor/tools.py`               |   5   |  0   | 100 % |
| `section_extractor/prompts.py`             |   3   |  0   | 100 % |
| `section_extractor/p1_extractor.py`        |  83   |  2   |  98 % |
| **Section extractor cumulative**           | 130   |  2   |  98 % |

Uncovered lines are the `confidence` type-coercion fallback (hard to
reach without a malformed enum response) and one branch on
`response.structured_output or {}` when the LLM returns the tool_use
block but with an empty input payload.

## Cost estimate

LLM cost this sprint: **$0** real-API. Tests use mocked responses
throughout. Expected real-API cost for one EuroEyes AR (500k tokens,
~8 sections): ~$2.55 per Spec C.9 — 1 Pass 1 call plus ~7 Pass 2 calls.
Validated when Sprint 4 runs the full integration smoke against a real
API key.

## Problems encountered

1. **Sprint 2 `test_happy_path_resolves_char_ranges` broke** once Pass 2
   always ran — it asserted `parsed_data is None` on IS/BS/CF. Fixed
   by making `_mock_llm` dispatch by tool name: Pass 1 gets the
   response it was handed, Pass 2 calls get an empty
   `structured_output`. Clean separation — Sprint 2 suite stays
   Pass-1-focused; Sprint 3 suite tests Pass 2 explicitly.
2. **Duplicate `start_marker` in a test** (`operating_data` using the
   same marker as `mda`) caused the de-duplicator to drop it. Removed
   the spurious entry from the happy-path test; the passthrough
   behaviour has its own test with a unique marker.
3. **mypy strict required `dict[str, object]` return type** on
   `_extract_section_content` (plain `dict` lost the type args).
   One-line fix.

## Next step

**Sprint 4 — Pass 3 validator.** Build `section_extractor/validator.py`
with the six required checks (core sections present, fiscal-period
consistency, currency consistency, IS/BS/CF arithmetic checksums).
Integrate into `extract()` so `ExtractionResult.issues` and
`overall_status` are populated. End-to-end smoke with the EuroEyes
fixture + mocked LLM producing realistic per-section responses. Closes
Batch 2.
