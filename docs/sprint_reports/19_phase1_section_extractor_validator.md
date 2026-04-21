# Phase 1 · Sprint 4 — Section Extractor Pass 3 (validator) + batch close

**Date:** 2026-04-21
**Phase 1 Step (Parte K):** 4 — Validator
**Status:** ✅ Complete · Batch 2 closed

---

## What was done

Pass 3 closes the section-extractor loop. Python-side checks run after
Pass 2, produce `ValidationIssue`s, and roll up into the result's
`overall_status`:

- **`section_extractor/validator.py`** — new module with
  `ExtractionValidator` plus six checks:
  1. Core sections present (`income_statement` / `balance_sheet` /
     `cash_flow`). Missing any → FATAL.
  2. Fiscal-period consistency — more than 2 distinct periods → WARN.
  3. Currency consistency — IS/BS/CF must share a currency → FATAL if
     they differ.
  4. IS arithmetic (`revenue + cost_of_sales + opex + d_and_a ≈
     operating_income`, ±5 %). Missing categories → INFO (skip).
  5. BS identity (`total_assets = total_liabilities + total_equity`,
     ±0.1 %). Missing subtotals → WARN (skip).
  6. CF identity (`cfo + cfi + cff ≈ net_change_in_cash`, ±2 %).
     Missing components → INFO (skip).
- **`_sum_by_category(line_items)`** helper groups Pass 2 line items
  by the enum category defined in each statement's tool. Preserves
  Decimal precision; skips items missing either category or value.
- **`overall_status(issues)`** static method rolls severities up via
  the standard guardrail precedence (`FAIL > REVIEW > WARN > NOTA >
  PASS > SKIP`). Empty list → PASS.
- **`p1_extractor.extract()`** now runs Pass 3 at the end, populating
  `ExtractionResult.issues` and `overall_status`. No LLM calls in
  Pass 3 — no cost-cap check needed.
- **28 new unit tests** in `tests/unit/test_section_validator.py`:
  - `_sum_by_category` helper behaviour (grouping, skips, Decimal
    precision).
  - Core sections present (all / missing one / all missing).
  - Fiscal-period consistency (single, two, three distinct).
  - Currency consistency (matching, mismatched).
  - IS arithmetic (balanced, unbalanced, missing revenue).
  - BS identity (balanced, unbalanced, missing subtotal).
  - CF identity (balanced, unbalanced, within tolerance).
  - `overall_status` roll-up (empty, FAIL dominates, WARN beats INFO,
    INFO-only → NOTA).
  - End-to-end: clean Pass 1+2+3 run yields PASS; BS-identity break
    yields FAIL; TOC missing a core section yields FAIL.
  - **EuroEyes fixture end-to-end** — Pass 1 identifies 3 core
    sections, Pass 2 parses each with realistic synthetic data that
    honours the identities, Pass 3 reports PASS with zero issues.
    Cost tracker records 1 TOC + 3 Pass 2 = 4 entries.

## Decisions taken

1. **Tolerances: 5 % / 2 % / 0.1 %** for IS / CF / BS respectively.
   BS identity is tight because reports publish totals to full
   precision; CF and IS have more rounding slack because line items
   often aggregate sub-lines. All three constants live at the top of
   `validator.py` so operators can tune them without hunting.
2. **Severity → GuardrailStatus mapping is explicit.** A dict
   (`_SEVERITY_TO_STATUS`) keeps the translation honest: `FATAL →
   FAIL`, `WARN → WARN`, `INFO → NOTA`. Unknown severities default to
   PASS — defensive but never silent if you're watching the status.
3. **Missing-input behaviour: skip gracefully, not fail.** When Pass 2
   returns partial data (e.g., no `revenue` line), the arithmetic
   checks emit an `INFO` issue and return. The alternative — failing
   when revenue is merely absent — would block pipelines on noisy
   extraction runs; the pragmatic choice is to surface the gap as a
   low-severity note and let downstream modules decide.
4. **IS arithmetic sign convention: costs stored as negatives.** Tool
   definitions ask the LLM to preserve parentheses-as-negatives, so
   the check computes `revenue + costs` (not `revenue − costs`). The
   test fixtures confirm the synthetic mock data follows this rule;
   downstream extraction modules (Modules A/B/C in Sprint 6+) will
   use the same convention.
5. **CF identity uses the reported `net_change_in_cash` line**
   rather than deriving it from opening/closing cash. Reports don't
   always publish opening cash; always publish the net change. Keeps
   the check self-contained inside the CF statement.
6. **Validator is stateless.** `ExtractionValidator()` has no
   configuration arguments. Thresholds are module-level constants.
   One instance per extractor instance (cached in `_validator`);
   concurrency-safe because methods don't share mutable state.
7. **End-to-end EuroEyes test uses hand-crafted synthetic parsed data
   that satisfies the arithmetic identities.** This proves the full
   Pass 1+2+3 pipeline produces a clean PASS on well-formed input.
   Companion tests (`test_bs_identity_breaks_yields_fail`,
   `test_missing_core_section_yields_fail`) exercise the failure
   paths end-to-end.

## Spec auto-corrections

1. **Spec C.8 listed four checks** (core sections, fiscal period,
   currency, IS checksums). Expanded to six (added BS identity and CF
   identity) per Hugo's Sprint 4 batch brief. BS identity is the
   strongest arithmetic guardrail we have — leaving it out would
   waste a cheap, high-signal check.
2. **Spec C.8's fiscal-period check said "if len > 2".** Kept the ≤2
   tolerance (primary + prior is legitimate) but added the WARN
   details dict so callers can see which periods clashed.
3. **Spec left `ValidationIssue` shape unspecified.** Defined in
   `base.py` (Sprint 2) with `severity / message / section_type /
   details`. Aligns with the guardrails-framework `GuardrailResult`
   shape — Sprint 6's extraction engine can convert either way.

## Files created / modified

```
A  src/portfolio_thesis_engine/section_extractor/validator.py    (new, 6 checks + roll-up)
M  src/portfolio_thesis_engine/section_extractor/p1_extractor.py (Pass 3 wired in)
A  tests/unit/test_section_validator.py                          (28 tests)
A  docs/sprint_reports/19_phase1_section_extractor_validator.md  (this file)
```

## Verification

```bash
$ uv run pytest
# 492 passed, 4 skipped in 12.84s

$ uv run ruff check src tests && uv run ruff format --check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 60 source files
```

End-to-end proof (`TestEuroEyesEndToEnd::test_fixture_all_passes`):

```
Pass 1 → 3 core sections identified (IS, BS, CF)
Pass 2 → all 3 sections have parsed_data (mocked)
Pass 3 → overall_status = PASS, issues = []
Cost tracker → 4 entries (1 section_toc + 1 section_parse_{is,bs,cf})
```

## Tests passing / failing + coverage

All 492 unit tests pass; 4 integration tests skipped (gated).

| section_extractor module                   | Stmts | Miss | Cover |
| ------------------------------------------ | ----- | ---- | ----- |
| `section_extractor/__init__.py`            |   3   |  0   | 100 % |
| `section_extractor/base.py`                |  38   |  0   | 100 % |
| `section_extractor/tools.py`               |   5   |  0   | 100 % |
| `section_extractor/prompts.py`             |   3   |  0   | 100 % |
| `section_extractor/p1_extractor.py`        |  85   |  2   |  98 % |
| `section_extractor/validator.py`           |  62   |  0   | 100 % |
| **Section extractor total**                | 196   |  2   | **99 %** |

Comfortably above the 80 % target. Uncovered lines are the two
defensive confidence-coercion branches in `p1_extractor.py` that only
fire on malformed LLM output.

## Cost estimate

LLM cost this sprint: **$0** real-API. All tests use mocked providers.
Batch 2 cumulative real-API cost: **$0** — the full end-to-end real-API
smoke (Spec C.9: ~$2.55 per EuroEyes AR) runs in Phase 1 Sprint 10 per
the plan.

## Problems encountered

1. **Positional-argument test bug.** `_is_section("HKD")` passed
   "HKD" as `line_items`, which then got `.get(...)` called on it.
   Two-minute fix — rewrote the currency tests to use keyword args.
2. **`mypy` flagged `dict[str, object] | None` return on
   `_extract_section_content`.** Was already fixed in Sprint 3; re-ran
   clean.
3. **No design blockers.** The three-pass architecture factors
   cleanly: Pass 1 handles structure, Pass 2 handles content, Pass 3
   handles consistency — each with its own test file and clear
   dependency on the previous pass's output.

## Batch 2 summary

Section extractor delivered in 3 sprints as one coherent unit:

| Sprint | Deliverable                                          | Tests | Cumulative coverage |
| ------ | ---------------------------------------------------- | ----- | -------------------- |
| 2      | Pass 1 (TOC identification)                          |  19   | 99 %                 |
| 3      | Pass 2 (per-section parsing + asyncio.gather)        |  13   | 98 %                 |
| 4      | Pass 3 (validation + overall_status + E2E smoke)     |  28   | 99 %                 |
| **Σ**  | **Full three-pass pipeline over EuroEyes fixture**   | **60** | **99 %**            |

Plus regression-fix to 19 Sprint 2 tests after Pass 2 always runs
(dispatcher mock by tool name).

Real-API cost across batch: **$0** (every LLM call mocked).

## Next step

**Sprint 5 — Cross-check gate.** Build
`cross_check/{base,gate,thresholds}.py`. Input: extracted values from
`ExtractionResult.sections` + FMP + yfinance. Output: `CrossCheckReport`
with per-metric PASS/WARN/FAIL and an overall `blocking` flag. Wire
into the CLI as `pte cross-check <ticker>`.
