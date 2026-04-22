# Unknown / catch-all notes — protocol (Phase 1.5.3)

**When to use this guide:** whenever you're tempted to drop
information because it doesn't fit any obvious shape.

## Phase 1.5.3 change

In Phase 1.5 the schema had a dedicated `notes.unknown_sections`
bucket with `UnknownSectionItem` entries. Phase 1.5.3 eliminated
typed notes altogether: **every note is a `Note` entry** in the flat
`notes: list[Note]`. There's no "unknown" bucket — there's just "a
Note with whatever title the PDF uses."

The protocol in this guide now applies to **any Note that doesn't fit
the standard list in [`required_notes_by_profile.md`](../required_notes_by_profile.md)**.
Such notes still belong in the YAML — just capture them as `Note`
entries like any other.

`Note` is a **reviewer-flagged catchall**. It keeps information in the
YAML instead of silently losing it. It is not a lazy dumping ground.

## Decision order — where does a disclosure go?

1. **Is there a typed field that matches?** Use it. Don't invent.
2. **Is there an `extensions` dict on the relevant parent?** Use it
   for sector-specific lines that don't fit a typed field but belong
   on the IS / BS / CF / a specific note.
3. **Is the disclosure a whole section that doesn't fit anywhere?**
   Use `notes.unknown_sections`.

```
Disclosure observed in PDF
        │
        ▼
   Typed field exists? ──Yes──► Use typed field. Done.
        │
        No
        │
        ▼
   Fits extensions dict
   of IS / BS / CF / a note? ──Yes──► Use extensions. Done.
        │
        No
        │
        ▼
   Whole-section disclosure? ──Yes──► notes.unknown_sections.
```

## `UnknownSectionItem` schema

Five fields:

```yaml
notes:
  unknown_sections:
    - title: "<verbatim PDF section title>"          # required, ≥1 char
      page_range: "p.84-87"                          # optional, human-readable
      content_summary: >                             # required — 2-3 sentences
        Brief description of what the section is and why it didn't fit
        a typed field. No analysis; describe the disclosure, not the
        implication.
      extracted_values:                              # optional dict[str, Decimal]
        key_metric_a_hkd_millions: "42.0"
        key_metric_b_units: "1500"
      reviewer_flag: true                            # default true; always leave true
```

## When to use it

### ✅ Good uses

- **Sector-specific disclosure that's not in the current schema.**
  EuroEyes' "number of surgical procedures by type" table would go in
  `operational_kpis.metrics` (it's a KPI), not here. But a gold
  miner's "mine-by-mine reserve table" with 15 rows and an unusual
  structure → `unknown_sections` with `extracted_values` of the
  headline reserves. Flag for schema-field request.

- **Aggregated summary the company publishes but the schema doesn't
  cover.** E.g., a "value chain impact" disclosure per IFRS Sustainability
  S2. Capture the headline numbers + summary; leave the rest for
  Phase 2.

- **Footnote disclosures that are financially meaningful but too
  niche.** E.g., "Effect of hypothetical hyperinflation adjustment in
  Argentina operation" — interesting for specific analytics; no
  typed home.

- **Whole sections of a prospectus that don't match any of the
  standard financial-statement shapes** — e.g., the "Use of
  proceeds" section of an IPO prospectus.

### ❌ Bad uses

- **"I didn't want to figure out if this fits."** That's laziness.
  Re-read the schema first.

- **Raw paste of the narrative.** `content_summary` is a 2-3 sentence
  description, not a verbatim transcript. Narrative text goes in
  `narrative.*` sections when `extraction_type: "narrative"` — not
  here.

- **Expected disclosures that were missing.** If an AR doesn't
  disclose a tax reconciliation, that's an `extraction_notes`
  observation, not an `unknown_sections` entry.

- **Things that have a typed home.** Goodwill movement → `notes.goodwill`.
  Lease disclosure → `notes.leases`. Don't route these through
  `unknown_sections`.

- **Your judgement about the number.** `content_summary` describes
  WHAT the disclosure is. It doesn't say "shows FX risk" or
  "indicates margin pressure". Keep it descriptive, not analytical.

## Format rules

- `reviewer_flag` is **always `true`**. Its purpose is to trigger
  human re-review. Default of the schema is `true`; don't override.

- `title` is the **literal section title from the PDF**, not a
  paraphrase. If the PDF says "Note 42 — Information under Section
  6(4) of the Hong Kong Listing Rules", copy that.

- `page_range` is helpful for Hugo when he audits the extraction.
  Use `"p.84"` for a single page, `"p.84-87"` for a range,
  `"p.84, 92"` for scattered pages.

- `extracted_values` keys are **snake_case with units in the name**:
  `"reserve_gold_oz_thousands"`, not `"Reserves"`. This avoids unit
  ambiguity when someone reads the YAML months later.

- `extracted_values` is **optional**. A section that's purely
  narrative (e.g., a governance disclosure) has `extracted_values: {}`
  or omits the key entirely.

## A concrete example

EuroEyes' AR has a "Sensitivity analysis — patient default rates"
note in FY2024 that simulates revenue loss under three default
scenarios. This isn't a standard disclosure, and there's no typed
home:

```yaml
notes:
  unknown_sections:
    - title: "Note 38 — Sensitivity analysis: patient default rates"
      page_range: "p.124"
      content_summary: >
        Three-scenario sensitivity on credit-loss provisions against the
        trade-receivables book. Based on hypothetical elevated default
        rates (2x, 3x, 5x baseline). The note discloses revenue impact
        under each scenario.
      extracted_values:
        baseline_default_rate_pct: "0.8"
        scenario_2x_revenue_impact_hkd_millions: "-4.5"
        scenario_3x_revenue_impact_hkd_millions: "-11.0"
        scenario_5x_revenue_impact_hkd_millions: "-28.0"
      reviewer_flag: true
```

This keeps the disclosure in the YAML for Phase 2, flags it for
Hugo's review, and doesn't try to force it into a typed field that
doesn't exist.

## How downstream uses it

The pipeline **does not process** `unknown_sections` in Phase 1.5. The
bucket exists so information is not lost; downstream tools (audit
reports, Phase 2 analytics) may surface it.

`pte audit-extraction <ticker>` lists every `unknown_sections` entry
in the audit report so Hugo can review and either:

- **Promote to a typed field** — if the pattern recurs across issuers,
  add a schema field in a future sprint.
- **Accept as-is** — it's genuinely niche; stays in the bucket.
- **Correct the extraction** — sometimes re-reading reveals the
  disclosure does fit a typed field after all.

## Rule of thumb

**When in doubt: capture in `unknown_sections` with a clear
`content_summary`, rather than dropping information.** The cost of a
flagged-for-review entry is low; the cost of silently losing data is
high and invisible.
