# Phase 1.5.1 — Knowledge base reinforcement

**Date:** 2026-04-22
**Scope:** 9 new markdown docs + updates to
`claude_ai_extraction_guide.md`, to strengthen extraction quality
before the first real EuroEyes end-to-end run.

## Motivation

Phase 1.5 closed clean. But when extraction of the real EuroEyes AR
started running in the Claude.ai Project, observed behaviour
contradicted the intended catch-all principle: the model produced
analytical judgements during extraction (e.g. "meaningful tax
inefficiency", "+30 % YoY depreciation", "multi-currency exposure
EUR 89.7 % — FX risk").

The Phase 1.5 knowledge base (`claude_ai_extraction_guide.md`,
`raw_extraction_schema.md`, etc.) was adequate for the schema
mechanics, but did not explicitly separate *extraction facts* from
*analytical judgements*. Phase 1.5.1 fixes that, plus adds depth on
the operational bugs that appear during real extractions.

## Deliverables

### Camada 2 — Operational guides (`docs/guides/`)

- **`sign_convention_guide.md`** (~2 pp.) — explicit sign rules for
  IS / BS / CF / notes; parentheses decoding; identity walks as
  verification.
- **`unit_scale_guide.md`** (~2 pp.) — the single most common
  extraction bug. EuroEyes "580 bug" as the case study. Exception
  list for per-share + share-count + rate fields. Mid-document
  scale detection.
- **`multi_currency_guide.md`** (~2 pp.) — reporting vs functional vs
  subsidiary currencies. Cash-by-currency as a common extension
  pattern. CTA handling. Pegged-currency nuances.
- **`schema_evolution_guide.md`** (~2 pp.) — preserve-as-reported
  principle. IFRS 16 adoption transitions. Segment reorganisations.
  Restatements. When to use extensions vs typed fields.
- **`unknown_sections_protocol.md`** (~1 p.) — decision order:
  typed field → extensions → `unknown_sections`. Format rules.
  When it is appropriate vs lazy. Sample entry for an EuroEyes
  sensitivity-analysis note.

### Camada 3 — Reference library (`docs/reference/`)

- **`operational_kpis_by_sector.md`** (~4 pp.) — **critical
  non-prescriptive disclaimer at the top**. Healthcare, retail,
  banking, software, insurance, REITs, commodity/energy KPI
  recall lists. Naming conventions (snake_case + units in key
  name).
- **`cross_statement_validation_checklist.md`** (~1 p.) — 9-section
  pre-submit checklist: arithmetic identities, cross-statement
  walks, completeness, unit-scale sanity, sign conventions,
  external sanity, metadata, final review.
- **`common_pitfalls_library.md`** (~3 pp.) — 20 catalogued
  antipatterns in 6 groups (sign / unit-scale / currency /
  classification / schema / interpretation creep). Each with bad
  example, good counter-example, detection heuristic. Includes
  EuroEyes case studies (the "580 bug", the fabricated director-
  comp pattern from v2 extraction).
- **`catch_all_philosophy.md`** (~2 pp.) — the core doc. Reinforced
  from observed Phase 1.5 extraction behaviour. Three rules:
  **do not calculate / do not interpret / do not classify beyond
  schema**. Bad-vs-good examples derived from what was actually
  produced ("meaningful inefficiency" → factual tax-rate number).
  Extraction-vs-downstream boundary diagram. Mental test: *"Is
  this on the page, or am I adding it?"*

### Updates to existing docs

- **`claude_ai_extraction_guide.md`**:
  - Added section 1a — "The catch-all principle" — inserted right
    after the context intro so it hits every session.
  - Updated section 2.2 knowledge-base contents to list all 13
    docs (4 Phase 1.5 + 9 Phase 1.5.1) + both few-shot fixtures,
    grouped by role (core contract / guides / reference / fixtures).
  - Added section 4a — "When in doubt — quick reference" — a
    dispatch table from situation → relevant guide.
- **README.md**: unchanged (Phase 1.5.1 is purely knowledge-base;
  doesn't add features or change CLI).

## Page totals

| Doc                                           | Pages (est.) |
| --------------------------------------------- | ------------ |
| `guides/sign_convention_guide.md`             | 2            |
| `guides/unit_scale_guide.md`                  | 2            |
| `guides/multi_currency_guide.md`              | 2            |
| `guides/schema_evolution_guide.md`            | 2            |
| `guides/unknown_sections_protocol.md`         | 1            |
| `reference/operational_kpis_by_sector.md`     | 4            |
| `reference/cross_statement_validation_checklist.md` | 1      |
| `reference/common_pitfalls_library.md`        | 3            |
| `reference/catch_all_philosophy.md`           | 2            |
| **Total new**                                 | **~19**      |

## Validation

- **ruff + mypy**: unchanged (no code edits this sprint).
- **Test suite**: unchanged, 832 passing.
- **Docs self-check**: every new doc cross-links to the relevant
  guide/reference where appropriate. Cross-references use relative
  paths so they resolve in both the repo and when uploaded to
  Claude.ai Projects.
- **Guide consistency**: tone matched to `claude_ai_extraction_guide.md`
  (operational voice, "do X / don't do Y", concrete examples,
  EuroEyes fixture as the recurring reference).

## How Hugo uses this

1. **Re-upload the Claude.ai Project knowledge base** with all 13
   docs + both fixtures. Order of upload doesn't matter — the
   Project indexes them all.
2. **In the Project's system prompt**, add a reference to
   `catch_all_philosophy.md`: *"Before producing any extraction
   output, confirm you're copying a fact from the PDF — not
   calculating, interpreting, or classifying. See
   catch_all_philosophy.md."*
3. **Re-run EuroEyes extraction** with the updated knowledge base;
   observe whether analytical-language generation reduces.
4. **If the model still editorialises**, add a preamble to each Pass
   2–6 prompt: *"Output facts only. No words like meaningful /
   material / elevated / significant. See catch_all_philosophy.md."*

## Known limitations

- **These are operator aids, not enforcement mechanisms.** Nothing in
  the app checks for analytical language in `extraction_notes` or
  `content_summary` strings. The validator catches structural and
  arithmetic problems, not tone.
- **Phase 2** could add a post-extraction lint that flags
  judgement-keyword occurrences in free-form strings — out of scope
  for 1.5.1.

## Next

The real EuroEyes end-to-end run is the first test of whether the
reinforced knowledge base is enough. If extraction quality is
acceptable, Phase 2 starts from here. If Pass 2–6 still produce
analytical output, iterate: add stronger system-prompt preamble,
fewer "few-shot" examples with editorial language, possibly a
review checklist before Pass 7 assembly.
