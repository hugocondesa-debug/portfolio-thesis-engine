# Phase 1 · Sprint 2 — Section Extractor Pass 1 (TOC identification)

**Date:** 2026-04-21
**Phase 1 Step (Parte K):** 2 — Section extractor Pass 1
**Status:** ✅ Complete

---

## What was done

First of three sprints on the section extractor — the central piece of
Phase 1. Pass 1 turns a raw markdown report into a list of located
sections with char offsets, using a single Anthropic tool-use call:

- **`section_extractor/base.py`** — `SectionExtractor` ABC plus three
  dataclasses: `IdentifiedSection` (Pass 1 intermediate), `StructuredSection`
  (final per-section record with parsed_data=None until Pass 2 fills it),
  `ExtractionResult` (aggregate). `ValidationIssue` also landed here so
  Sprint 4 doesn't need to touch this file.
- **`section_extractor/tools.py`** — `KNOWN_SECTION_TYPES` (15 canonical
  types, enum-constrained in the schema) and `REPORT_SECTIONS_TOOL`
  input schema. The LLM reports each section with a literal
  `start_marker` / `end_marker` string; Python resolves char offsets
  via `str.find`, sidestepping the "LLM can't count characters" problem.
- **`section_extractor/prompts.py`** — system + user templates in their
  own module so future prompt tweaks show up cleanly in git blame.
- **`section_extractor/p1_extractor.py`** — `P1IndustrialExtractor`
  implementing Pass 1. `extract(document)` reads the blob, invokes the
  LLM, resolves markers to char offsets, produces
  `StructuredSection`s with windowed content, and records cost via
  `CostTracker` under `operation="section_toc"`.
- **19 unit tests** covering tool shape, happy-path boundary resolution,
  cost-tracker integration, tool-choice pinning, marker edge cases
  (unresolvable, duplicate, missing end_marker, unknown end_marker, LLM
  returning text without tool_use), section-ordering guarantee, default
  confidence, dataclass immutability, and a fixture-integration test
  over the synthetic EuroEyes AR that round-trips all 8 expected P1
  sections end-to-end.

## Decisions taken

1. **Markers instead of char offsets.** The tool asks the LLM to report
   a `start_marker` (exact heading text) and optional `end_marker`
   (next heading). The extractor resolves these to char indices with
   `content.find()`. Alternatives considered: asking the LLM to count
   characters (impossible reliably), numeric page ranges (our markdown
   doesn't have reliable page markers). Literal-string markers degrade
   gracefully — a wrong marker gets dropped rather than silently
   pointing at the wrong bytes.
2. **Enum-constrained `section_type` via `KNOWN_SECTION_TYPES`.** 15
   allowed values including `other` as a catch-all. Hard-enforces the
   downstream contract — downstream modules never see a surprise
   section_type because Anthropic's tool runtime rejects out-of-enum
   values.
3. **Sorting returned sections by `start_char` ascending.** LLM may
   emit them out of order; canonical ordering in the result avoids
   every downstream consumer needing to sort.
4. **De-duplicating by `start_marker`.** If the LLM emits the same
   section twice, the extractor keeps the first occurrence and drops
   the rest. Prevents upstream weirdness from cascading.
5. **`confidence` coerced to 0.8 on missing/bad values.** Pragmatic
   default; downstream (Sprint 4 validator) can downgrade status if a
   whole document is mostly low-confidence sections.
6. **`primary_fiscal_period` promoted to document-level.** The tool
   schema includes it alongside per-section `fiscal_period`; when a
   section's own period is absent, the document-level primary fills in.
   The `ExtractionResult.fiscal_period` falls back to
   `primary_fiscal_period` → first section's period → `"unknown"`.
7. **Injected `AnthropicProvider` + `CostTracker`** through the
   constructor. No global singletons — tests build real `CostTracker`s
   on `tmp_path` and `MagicMock` LLM providers returning canned
   `LLMResponse` shapes. Same pattern Fase 0 established.
8. **`extraction_method="llm_section_detection"`** hard-coded on every
   Pass 1 section so a future Phase 2 Modo A extractor (pre-separated
   raw files) can use a different value for distinguishability.
9. **Response-shape defensiveness.** If the LLM returns text without a
   tool_use block, `structured_output is None` — the extractor returns
   an empty section list and `fiscal_period="unknown"` rather than
   crashing. Explicit test pins this behaviour.

## Spec auto-corrections

1. **Spec C.4 mentioned `{section_type: (start_page, end_page)}` output.**
   Our markdowns don't carry reliable page numbers, so we return
   `{section_type: (start_char, end_char)}` instead. Drop-in for all
   downstream consumers — Pass 2 just slices `content[start_char:end_char]`.
2. **Spec C.6 tool `extract_income_statement`** — reserved for Sprint 3.
   Sprint 2 only ships the `report_sections_found` tool.
3. **Spec C.9 cost note: "Pass 1 can use Haiku for cheaper".** Default
   is Sonnet (quality first); `model_toc` constructor arg parameterises
   this, so operators can switch to Haiku with one line when they
   validate quality stays acceptable on a given document type.

## Files created / modified

```
A  src/portfolio_thesis_engine/section_extractor/__init__.py
A  src/portfolio_thesis_engine/section_extractor/base.py
A  src/portfolio_thesis_engine/section_extractor/tools.py
A  src/portfolio_thesis_engine/section_extractor/prompts.py
A  src/portfolio_thesis_engine/section_extractor/p1_extractor.py
A  tests/unit/test_section_toc.py                               (19 tests)
A  docs/sprint_reports/17_phase1_section_extractor_toc.md        (this file)
```

## Verification

```bash
$ uv run pytest
# 451 passed, 4 skipped in 12.02s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 59 source files
```

Smoke on the EuroEyes fixture (mocked LLM) identifies all 8 P1 sections:

```
fiscal_period = FY2024
sections = 8
  [income_statement    ] Consolidated Income Statement                (842 chars)
  [balance_sheet       ] Consolidated Balance Sheet                  (1130 chars)
  [cash_flow           ] Consolidated Cash Flow Statement             (680 chars)
  [segments            ] Segment Information                          (388 chars)
  [notes_taxes         ] Note 7 — Income Tax Reconciliation           (737 chars)
  [notes_leases        ] Note 8 — Leases (IFRS 16)                    (851 chars)
  [notes_provisions    ] Note 9 — Provisions                          (…)
  [mda                 ] Management Discussion & Analysis             (381 chars)
cost_tracker session = $0.01875
```

## Tests passing / failing + coverage

All 451 unit tests pass; 4 integration tests skipped (gated).

| Phase 1 new module                         | Stmts | Miss | Cover |
| ------------------------------------------ | ----- | ---- | ----- |
| `section_extractor/__init__.py`            |   3   |  0   | 100 % |
| `section_extractor/base.py`                |  36   |  0   | 100 % |
| `section_extractor/tools.py`               |   3   |  0   | 100 % |
| `section_extractor/prompts.py`             |   2   |  0   | 100 % |
| `section_extractor/p1_extractor.py`        |  46   |  1   |  98 % |
| **Sprint 2 subtotal**                      |  90   |  1   | **99 %** |

Comfortably above the 80% target. Uncovered line is a defensive
confidence fallback path that's hard to hit without a malformed enum
response.

## Cost estimate

LLM cost this sprint: **$0** real-API. All tests mock the provider.
The integration test with real APIs (`PTE_SMOKE_HIT_REAL_APIS=true`)
still targets `pte smoke-test` via Fase 0 paths; Phase 1 end-to-end
real-API smoke lands in Sprint 10 per the plan.

## Problems encountered

1. **`B017 pytest.raises(Exception)` too broad** in the frozen-dataclass
   test. Replaced with the specific `dataclasses.FrozenInstanceError`.
2. **Two rounds of `ruff check --fix` + `ruff format`** needed to settle
   imports. Auto-sort moved `dataclasses` into the stdlib group with
   the other top-level stdlib imports.
3. **No design blockers.** The markers-not-char-offsets decision felt
   non-obvious beforehand but tested cleanly; happy Sprint.

## Next step

**Sprint 3 — Pass 2 per-section parsing.** Expand `tools.py` with seven
tool definitions (IS, BS, CF, segments, leases, tax reconciliation,
MD&A), matching prompts, and `_extract_section_content` dispatch in
`p1_extractor.py`. Parallelise per-section extraction with
`asyncio.gather` bounded to 5 concurrent calls. Check cost-cap before
Pass 2 launches.
