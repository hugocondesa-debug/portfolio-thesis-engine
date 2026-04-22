# Claude.ai extraction workflow guide

**Audience:** Hugo (the analyst producing every `raw_extraction.yaml`).
**Purpose:** Set up and operate the Claude.ai Projects that produce
the boundary YAML this app consumes.

This guide is the operator's manual for the extraction half of the
portfolio thesis engine. The other half — reclassification, guardrails,
valuation, ficha composition — lives in the Claude Code app and consumes
the output of this workflow deterministically.

## 1. Context — why a two-app boundary

Phase 1 tried to run the full pipeline inside one Claude Code app,
including the LLM-driven Pass 2 that mapped raw PDFs into structured
sections. It worked but was expensive, slow, and hard to control: every
re-run re-parsed the PDF, one tool call per section, latent disagreement
between parses.

Phase 1.5 splits the system along the boundary that matters:

```
┌────────────────────────────┐       ┌──────────────────────────────┐
│  Claude.ai Projects        │       │  Claude Code app             │
│  (one per profile)         │       │  (portfolio-thesis-engine)   │
│                            │       │                              │
│  • PDFs / prospectuses     │       │  • pte ingest                │
│  • Hugo drives extraction  │       │  • pte validate-extraction   │
│  • Produces the YAML       │──────►│  • pte process <ticker>      │
│  • No side effects         │       │  • Canonical state + ficha   │
└────────────────────────────┘       └──────────────────────────────┘
            ^                                       │
            │                                       │
         PDF in                               raw_extraction.yaml in
```

**The boundary is `raw_extraction.yaml`.** Every numeric value the app
consumes is extracted, classified, and validated by Hugo (with Claude.ai
as the tireless co-pilot) in a Claude.ai Project before it enters the
pipeline. Zero LLM calls inside the app. Every decision is auditable.

The three-page schema reference
([`raw_extraction_schema.md`](raw_extraction_schema.md)) is the contract
— if the YAML validates, the pipeline processes it.

## 1a. The catch-all principle (read this every session)

**Extraction captures what the company reported. Downstream decides
what it means.**

During extraction you **do not**:

- Calculate or derive values the PDF doesn't publish.
- Interpret numbers ("meaningful tax inefficiency", "+30% YoY",
  "material FX risk", "strong growth").
- Classify beyond the closed schema vocabularies.
- Guess ambiguous disclosures — flag them in
  `notes.unknown_sections` with `reviewer_flag: true`.

If you catch yourself writing words like _meaningful, material,
elevated, concerning, strong, weak, signals, indicates, inefficient_
in the YAML — stop. Rewrite as a fact, or delete.

Full rationale + bad-vs-good examples in
[`reference/catch_all_philosophy.md`](reference/catch_all_philosophy.md).
**Upload that doc to every Claude.ai Project; re-read it when the
model starts editorialising.**

## 2. Setup — one Project per profile

The extraction methodology and the required note-set differ by profile,
so each profile gets its own Claude.ai Project. Same system prompt, same
output schema, different knowledge-base contents.

| Profile | Name                        | Typical universe                         |
| ------- | --------------------------- | ---------------------------------------- |
| P1      | Industrials / Services      | Most listed companies with IFRS/US-GAAP  |
| P2      | Banks                       | Regulated deposit-taking institutions    |
| P3a     | Insurance                   | Life, P&C, reinsurance                   |
| P3b     | REITs                       | Listed real-estate trusts                |
| P4      | Natural Resources           | Upstream oil/gas/mining; NI 43-101       |
| P5      | Pre-revenue / Biotech       | Clinical-stage biotech, early SaaS      |
| P6      | Holdings                    | Multi-entity conglomerates               |

**Phase 1.5 ships P1 only.** P2–P6 profiles activate in Phase 2; create
the Projects now with minimal knowledge bases so they exist when Hugo
starts populating them.

### 2.1 Creating a Project

1. In Claude.ai, click `+ New Project`.
2. Name it `Portfolio Thesis — <Profile code> <Profile name>` (e.g.
   `Portfolio Thesis — P1 Industrials`).
3. System prompt (below, same across profiles):

   ```
   You are an extraction assistant for the Portfolio Thesis Engine. Your job
   is to read financial documents (annual reports, interims, earnings calls,
   SEC filings, prospectuses, etc.) and produce a single raw_extraction.yaml
   file per document that matches the RawExtraction schema.

   Rules:
   1. Every monetary value is a string, e.g. "580.0". Decimals only. No
      commas. Preserve sign exactly as reported (use "-" for negatives,
      never parentheses).
   2. unit_scale is one of {units, thousands, millions}. Whatever the source
      document uses. The app normalises — you do NOT multiply.
   3. reporting_currency is the three-letter ISO code of the consolidated
      statements (not subsidiary currencies).
   4. Ask me before guessing. If the PDF is ambiguous, reply with the
      specific question and the page number; do not fabricate.
   5. Every numeric field you populate must be cross-referenced to a page.
      Drop a reference comment in the YAML when uncertain:
        revenue: "580.0"  # AR p.42 line 2 (consolidated)
   6. Validation: run `pte validate-extraction path/to/yaml` locally and
      fix every strict FAIL before shipping.
   7. You are not the app. You produce YAML. Everything downstream
      (reclassification, guardrails, valuation) is handled separately.
   ```

4. Upload the knowledge base (section 2.2).

### 2.2 Knowledge-base contents per Project

Upload these to every Project. The Phase 1.5.1 reinforcement (guides
+ reference library) is critical for extraction quality.

**Core contract:**

- **`SPEC_PHASE_0.md`** (repo root) — the canonical spec (context only;
  most of it is app-side).
- **`docs/claude_ai_extraction_guide.md`** (this document).
- **`docs/raw_extraction_schema.md`** — field-by-field schema contract.
- **`docs/document_types.md`** — which DocumentType to use when.
- **`docs/required_notes_by_profile.md`** — completeness checklist.

**Operational guides (`docs/guides/`):**

- **`guides/sign_convention_guide.md`** — sign rules IS/BS/CF,
  parentheses decoding.
- **`guides/unit_scale_guide.md`** — the #1 bug; EPS + share-count
  exceptions; verification.
- **`guides/multi_currency_guide.md`** — reporting vs functional vs
  subsidiary; cash-by-currency; CTA.
- **`guides/schema_evolution_guide.md`** — year-to-year changes,
  restatements, IFRS adoption.
- **`guides/unknown_sections_protocol.md`** — when/how to use the
  catchall bucket vs extensions vs typed fields.

**Reference library (`docs/reference/`):**

- **`reference/catch_all_philosophy.md`** — the foundational rule.
  **Re-read each session.**
- **`reference/operational_kpis_by_sector.md`** — sector KPI recall
  list (non-prescriptive — preserve company naming).
- **`reference/cross_statement_validation_checklist.md`** —
  pre-submit checks.
- **`reference/common_pitfalls_library.md`** — 20+ antipatterns with
  bad-vs-good examples.

**Few-shot fixtures:**

- **`tests/fixtures/euroeyes/raw_extraction_ar_2024.yaml`** — realistic
  AR 2024 example (P1 few-shot).
- **`tests/fixtures/euroeyes/raw_extraction_interim_h1_2025.yaml`** —
  realistic H1 interim example (period-type demonstration).

Profile-specific additions (when the profile activates):

- **P1:** `docs/methodology/P1_industrial.md` (Phase 2).
- **P2:** Basel III / Pillar 3 primer.
- **P3a:** Solvency II / SFCR primer.
- **P3b:** FFO / AFFO methodology.
- **P4:** NI 43-101 primer; oil/gas reserve nomenclature.
- **P5:** Pre-revenue biotech valuation methodology.
- **P6:** Consolidation hierarchy + minority-interest carve-outs.

## 3. Extraction workflow — 7 passes

Each pass maps to a single, scoped Claude.ai conversation. Start a new
chat per pass; keep the chats short and focused so the model stays on
task. Concatenate the outputs into one YAML at the end.

### Pass 1 — Document structure (index)

**Goal:** enumerate what's in the PDF before reading.

**Prompt:**

```
Here is the PDF of <Company Name>'s <Document Type> for <fiscal year>.

Produce a table-of-contents summary:
- Every section with page range
- Which financial statements are present (IS, BS, CF, Equity)
- Which notes are present (taxes, leases, ppe, provisions, etc.)
- Segment disclosures (by geography? by product? by business line?)
- Historical data summary (how many years of revenue, NI, etc.)
- Operational KPIs (any that are repeated year-over-year?)
- Any unusual / hard-to-classify sections I should flag

Don't extract numbers. Just the structure. I'll work through it.
```

**Output:** a plain-text index you keep handy as the navigator.

**Time budget:** 5 min.

---

### Pass 2 — Core statements (IS, BS, CF), all periods

**Goal:** populate `income_statement`, `balance_sheet`, `cash_flow`.

**Prompt:**

```
Extract the Income Statement for every period reported (usually current
year + prior year; interim reports may have H1 + prior H1).

Output format — raw YAML, one block per period:

income_statement:
  FY2024:
    revenue: "580.0"                   # AR p.42
    cost_of_sales: "-290.0"            # AR p.42
    gross_profit: "290.0"
    selling_marketing: "-95.0"
    general_administrative: "-65.0"
    depreciation_amortization: "-20.0"
    operating_expenses_total: "-180.0"
    operating_income: "110.0"
    finance_income: "4.0"
    finance_expenses: "-18.0"
    income_before_tax: "96.0"
    income_tax: "-21.0"
    net_income: "75.0"
    net_income_parent: "75.0"
    eps_basic: "0.375"
    eps_diluted: "0.370"
    shares_basic_weighted_avg: "200.0"
    shares_diluted_weighted_avg: "202.7"
  "FY2023":
    ...

Rules:
- Every numeric value is a string with decimal point. No commas.
- Negative values use "-", NEVER parentheses.
- unit_scale will be declared in the metadata block — do not multiply
  here; just use the number as reported in the PDF.
- If a field isn't reported, OMIT it (don't use "0" or null).
- Include a page reference as a YAML comment for every non-trivial line.
- If the IS combines multiple lines (e.g. "Selling, general and
  administrative expenses" in one line), populate
  selling_general_administrative and leave the split fields empty.

Verify the identity: revenue + cost_of_sales should roughly match
gross_profit; operating_income + finance_income + finance_expenses
+ income_tax should roughly match net_income. Flag any discrepancies
— they're usually currency-translation adjustments or share-of-
associates buried elsewhere.
```

Repeat verbatim for `balance_sheet` and `cash_flow`.

**Time budget:** 15 min.

---

### Pass 3 — Required notes (profile checklist)

**Goal:** populate `notes` per [`required_notes_by_profile.md`](required_notes_by_profile.md).

**Prompt (run once per required note, in order):**

```
Extract the <NOTE NAME> note, output as YAML under the `notes:` key.

Required shape (see raw_extraction_schema.md):
<Paste the relevant schema block for this note>

Rules:
- Every Decimal field from the PDF becomes a string.
- Required fields must be populated; optional may be omitted.
- For ProvisionItem / TaxReconciliationItem: the classification
  vocabulary is CLOSED — use the exact enum values. When uncertain,
  use "unknown" (taxes) or "other" (provisions); never invent a new
  classification.
- Cross-reference each row with a page number.
```

For P1 Industrial, required notes in order:
`taxes` → `leases` → `ppe` → `inventory` → `trade_receivables` →
`trade_payables` → `employee_benefits` → `financial_instruments` →
`commitments_contingencies` → `provisions`.

**Time budget:** 3–5 min per note ≈ 30–50 min for P1.

---

### Pass 4 — Optional notes

**Goal:** capture value-add notes that aren't always present.

Extract these when the PDF discloses them (check the Pass 1 index):

- `goodwill` — movement + by_cgu. Critical when the company has
  acquisitions; ties into Module B.
- `intangibles` — movement + by_type. Software / customer relationships
  / brand splits feed peer comparison later.
- `share_based_compensation` — SBC expense, RSUs outstanding. Feeds
  Module E (Phase 2).
- `pensions` — DBO opening/closing, plan assets. Feeds Module D.
- `acquisitions` — one `AcquisitionItem` per material deal.
- `discontinued_ops` — revenue / op-income / NI for discontinued
  segments. Feeds Module B.
- `subsequent_events` — material post-balance-sheet events.
- `related_parties` — transactions with related entities.
- `financial_instruments` — free-form credit/liquidity/market risk.

If a note exists but doesn't fit any schema bucket, drop it into
`notes.unknown_sections` with a `reviewer_flag: true` and Hugo decides
later whether to add a schema field or treat it as noise.

**Time budget:** 15–30 min depending on disclosure richness.

---

### Pass 5 — Segments

**Goal:** populate the three `segments` dicts if disclosed.

**Prompt:**

```
Extract the segment data. Output under `segments:` — three possible
keys: by_geography, by_product, by_business_line. Schema:

segments:
  by_geography:
    FY2024:
      "North America":
        revenue: "420.0"
        operating_income: "85.0"
      "Europe":
        revenue: "160.0"
        operating_income: "25.0"

Rules:
- Segment names verbatim from the PDF. Translate only if the original
  language is not English (Chinese / Japanese / Portuguese).
- Only include metrics disclosed per-segment. If the PDF only discloses
  segment revenue, don't invent segment operating_income.
- The outer key is the period label (same as in income_statement).
- Use dict-of-dict-of-dict structure (period → segment → metric).
```

**Time budget:** 5–10 min.

---

### Pass 6 — Historical (5-year) + Operational KPIs

**Goal:** populate `historical` + `operational_kpis` from 5-year summary
tables and the "key operational metrics" section.

**Prompt:**

```
Extract the 5-year summary table into `historical`:

historical:
  revenue_by_year:
    "2020": "380.0"
    "2021": "440.0"
    ...
  net_income_by_year:
    "2020": "32.0"
    ...
  (every other field on HistoricalData where the PDF has ≥3 years)

Extract the operational KPIs into `operational_kpis.metrics`:

operational_kpis:
  metrics:
    patient_visits_thousands:
      "FY2024": "285"
      "H1 2025": "152"
    clinics_total:
      "FY2024": "38"
      "H1 2025": "40"

Rules:
- operational_kpis.metrics is FREE-FORM: use whatever metric names the
  company reports. Snake_case. Include units in the name
  (`_thousands`, `_millions`, `_hkd`, `_pct`).
- Values can be Decimal strings or plain strings (narrative KPIs).
- historical uses year keys ("2020"); operational_kpis uses period
  keys (matching the IS/BS/CF period labels).
```

**Time budget:** 10 min.

---

### Pass 7 — Assembly + validation

**Goal:** merge the 6 previous outputs + the metadata block into one
valid YAML; run the local validator; iterate until clean.

**Prompt:**

```
Here are the 6 YAML fragments I've produced across passes 2-6.
Produce a single complete raw_extraction.yaml by:

1. Prepending the metadata block:

   metadata:
     ticker: "<TICKER>"
     company_name: "<Company Name>"
     document_type: "<DocumentType from document_types.md>"
     extraction_type: "numeric"  # or "narrative"
     reporting_currency: "<ISO 4217>"
     unit_scale: "<units | thousands | millions>"
     fiscal_year: <int>
     extraction_date: "<YYYY-MM-DD>"
     extractor: "Claude.ai + human validation"
     source_file_sha256: "<sha256 of the source PDF>"
     extraction_version: 1
     extraction_notes: "<anything noteworthy: restated figures, IFRS
                        adoption year, acquisition timing, etc.>"
     fiscal_periods:
       - period: "FY2024"
         end_date: "2024-12-31"
         is_primary: true
         period_type: "FY"
       - period: "FY2023"
         end_date: "2023-12-31"
         period_type: "FY"

2. Concatenating the 6 fragments under the correct top-level keys
   (income_statement, balance_sheet, cash_flow, notes, segments,
   historical, operational_kpis).

3. Producing the FULL, valid YAML in a single fenced block.
```

**Then run locally:**

```bash
pte validate-extraction path/to/raw_extraction.yaml --profile P1
```

The validator runs three layers:

- **Strict** — identity / sign / schema checks. FAIL blocks the app's
  pipeline. Fix every one.
- **Warn** — anomalies worth a human look (e.g. debt grew 50% YoY).
  Don't have to fix, but read them.
- **Completeness** — are all P1 required notes populated? Compute a
  completeness score. Target ≥90 % before calling the extraction done.

Fix the FAILs, re-run, ship when clean.

**Time budget:** 5–15 min depending on how many FAILs surface.

---

## 4. Common pitfalls

### 4.1 Unit scale traps

The single most common bug. The fixture file had a bug in mid-2026
where a user mixed `millions` and `thousands` across statements —
validation caught it immediately but cost an hour of debugging.

**Rules:**

- `unit_scale` is **one value for the whole document**. If the IS is
  reported in thousands but the notes in millions (unusual but happens
  in Japanese filings), normalise everything to one scale BEFORE
  producing the YAML.
- When in doubt, read the cover page of the financial statements —
  "all figures in USD thousands" is typical. If the PDF is ambiguous,
  ask in the Claude.ai chat before guessing.
- The app normalises monetary Decimals by the scale factor:
  `millions → × 1_000_000`. You do not multiply.
- EPS, per-share figures, and ratios are NOT scaled. They stay as
  reported regardless of `unit_scale`.

### 4.2 Sign conventions

- Negative numbers use `-`, never `(100)`. Claude.ai has to convert
  parentheses to `-` when copying from PDF tables.
- Cost_of_sales, opex, D&A, income_tax, finance_expenses on the IS
  are typically **negative** (they subtract from revenue).
  `operating_income` is typically **positive**.
- CF: `capex`, `debt_repayment`, `dividends_paid`, `share_repurchases`
  are **negative** (cash outflows). `operating_cash_flow`,
  `debt_issuance`, `share_issuance` are **positive**.
- BS balances are always positive except `treasury_shares` and
  `accumulated_depreciation` (both reported as negatives that reduce
  their parent).

### 4.3 Currency splits

When a subsidiary reports in a different currency than the
consolidated parent, the parent's filing translates the subsidiary
into the reporting currency. The YAML carries **the reporting
currency**, not the subsidiary's.

Example: EuroEyes (HKD-reported) has German operations reporting in
EUR internally. The consolidated IS shows everything in HKD. The
fixture's `reporting_currency: "HKD"` is correct.

If the filing provides a segmented FX breakdown, capture it in the
`financial_instruments.market_risk` string or under `notes.extensions`
— don't invent a schema field.

### 4.4 Aggregated vs itemised line items

Some companies aggregate items on the face of the IS (e.g. "Selling,
general and administrative expenses" as a single line). Others
itemise (`selling_marketing` + `general_administrative` separately).

**Rule:** populate **what the PDF shows**. Don't synthesise a split.
The schema has `selling_general_administrative` for the aggregate
case and `selling_marketing` + `general_administrative` for the split
case — pick one, leave the other empty.

### 4.5 IFRS 16 adoption year handling

Companies that adopted IFRS 16 mid-year show lease-related line items
only after the adoption date. A 2019 / 2020 IS may not have
`rou_assets` or `lease_liabilities_current` populated; a 2024 IS
definitely does.

When extracting historical data (`historical.*_by_year`) for a
5-year window that crosses the adoption date:

- Populate pre-adoption years with what's reported (no IFRS 16 fields).
- Add an `extraction_notes` metadata comment explaining the
  discontinuity.
- The AnalysisDeriver copes with `None` fields; what matters is that
  the validator's completeness check doesn't FAIL on a field that
  genuinely didn't exist that year.

### 4.6 Schema evolution between fiscal years

A 2022 AR and a 2024 AR from the same issuer may report the same KPI
under different names, or move a line between "Other operating
expenses" and "G&A". When extracting multiple years:

- Align names at extraction time: use the 2024 naming retrospectively
  for 2022.
- Document the remap in `extraction_notes`.
- Never silently re-bucket figures — if you can't remap unambiguously,
  leave the older year's field empty.

### 4.7 Interim vs annual periods

Interim reports (H1 / Q1 / Q3) have fewer periods and often fewer
notes. The schema handles this:

- `period_type: "H1"` on the fiscal period tells the validator not
  to require a full-year CF.
- `extraction_type: "numeric"` stays the same — it's about whether
  the source produces statements vs narrative, not about annual vs
  interim.
- Consider running the interim extraction as a **separate YAML** from
  the annual — the pipeline supports multiple documents per ticker.

## 4a. When in doubt — quick reference

When something on the page doesn't fit cleanly, consult the relevant
guide. Each is short (1-3 pages) and example-heavy.

| Situation                                                    | Go to                                                                |
| ------------------------------------------------------------ | -------------------------------------------------------------------- |
| Parentheses in a number / unsure about sign                  | [`guides/sign_convention_guide.md`](guides/sign_convention_guide.md) |
| Suspicious magnitude / mid-document scale change             | [`guides/unit_scale_guide.md`](guides/unit_scale_guide.md)           |
| Company has operations in multiple currencies                | [`guides/multi_currency_guide.md`](guides/multi_currency_guide.md)   |
| Line names or classifications changed between years          | [`guides/schema_evolution_guide.md`](guides/schema_evolution_guide.md) |
| Disclosure doesn't fit any typed field or extensions dict    | [`guides/unknown_sections_protocol.md`](guides/unknown_sections_protocol.md) |
| Need a sector-specific KPI recall                            | [`reference/operational_kpis_by_sector.md`](reference/operational_kpis_by_sector.md) |
| Pre-submit sanity check                                      | [`reference/cross_statement_validation_checklist.md`](reference/cross_statement_validation_checklist.md) |
| The validator surfaced a warn or FAIL you don't understand   | [`reference/common_pitfalls_library.md`](reference/common_pitfalls_library.md) |
| Tempted to write "meaningful", "material", "elevated", ...   | [`reference/catch_all_philosophy.md`](reference/catch_all_philosophy.md) |

## 5. Validation commands

Run these after every extraction change, before committing the YAML to
the `~/data_inputs/<ticker>/` directory that feeds the pipeline.

### 5.1 `pte validate-extraction`

```bash
pte validate-extraction path/to/raw_extraction.yaml --profile P1
```

Runs the three-tier validator (strict / warn / completeness) and prints
a formatted report. Strict FAIL exits non-zero so you can wire it into
a pre-commit hook.

### 5.2 `pte audit-extraction`

```bash
pte audit-extraction 1846.HK
```

Assumes the YAML is already ingested (or lives at
`~/data_inputs/1846.HK/raw_extraction.yaml`). Runs validator + produces
a human-readable audit report saved alongside.

### 5.3 `pte process`

```bash
pte process 1846.HK --verbose
```

The full pipeline. Runs the 11 stages (CHECK_INGESTION → LOAD_WACC →
LOAD_EXTRACTION → VALIDATE_EXTRACTION → CROSS_CHECK → EXTRACT_CANONICAL
→ PERSIST → GUARDRAILS → VALUATE → PERSIST_VALUATION → COMPOSE_FICHA).

This is what you run when the extraction is clean and you're ready to
produce the canonical state + valuation. Strict validation FAIL blocks
the run; cross-check FAIL blocks unless you pass
`--skip-cross-check` (loudly logged).

## 6. Time estimates

| Activity                                              | First time | Subsequent updates |
| ----------------------------------------------------- | ---------- | ------------------ |
| Annual report extraction (P1, full notes)             | 45–60 min  | 20 min             |
| Interim report extraction (P1, required notes only)   | 20–30 min  | 10 min             |
| Set up a new Claude.ai Project (one-time per profile) | 15 min     | —                  |
| Validation + iteration to OK                          | 10 min     | 5 min              |

The first extraction for a new issuer is the long pole — subsequent
extractions for the same issuer reuse the naming conventions, segment
definitions, and operational-KPI glossary you already established.

## 7. Multi-document strategy

One `raw_extraction.yaml` per source document. For one ticker the
`~/data_inputs/<ticker>/` directory ends up with:

```
data_inputs/
└── 1846.HK/
    ├── raw_extraction_ar_2024.yaml
    ├── raw_extraction_interim_h1_2025.yaml
    ├── raw_extraction_ec_q3_2024.yaml         (earnings call)
    └── wacc_inputs.md
```

**Phase 1.5 ships single-document processing.** `pte process
<ticker>` consumes one YAML (the default is `raw_extraction.yaml`, but
you can point at any file via `--extraction-path`).

**Phase 2** will add multi-document merging: the pipeline combines the
annual + interim + earnings-call YAMLs into a single canonical state
with the latest available numbers per field and a full audit trail of
what came from which document.

Until then, the workflow is:

1. Extract the primary document (usually the latest AR) into
   `raw_extraction.yaml`.
2. Run the pipeline → produce the canonical state + ficha.
3. When new material comes in (interim, earnings call, SEC
   correspondence), extract it separately and re-run the pipeline
   against whichever YAML has the freshest numbers.

Phase 2 will automate the merge. For now, explicit is better than
implicit.

## 8. Quick reference — typical first-pass YAML skeleton

```yaml
metadata:
  ticker: "1846.HK"
  company_name: "EuroEyes Medical Group"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "HKD"
  unit_scale: "millions"
  fiscal_year: 2024
  extraction_date: "2026-04-22"
  source_file_sha256: "a1b2c3..."
  fiscal_periods:
    - period: "FY2024"
      end_date: "2024-12-31"
      is_primary: true
      period_type: "FY"

income_statement:
  FY2024:
    revenue: "580.0"
    # ... Pass 2 output

balance_sheet:
  FY2024:
    cash_and_equivalents: "450.0"
    # ... Pass 2 output

cash_flow:
  FY2024:
    operating_cash_flow: "135.0"
    # ... Pass 2 output

notes:
  taxes:
    effective_tax_rate_percent: "21.9"
    # ... Pass 3 output
  leases:
    # ... Pass 3 output
  # ... other required notes

segments:
  by_geography:
    FY2024:
      # ... Pass 5 output

historical:
  revenue_by_year:
    # ... Pass 6 output

operational_kpis:
  metrics:
    # ... Pass 6 output
```

That's the whole workflow. Start on an annual report, follow the 7
passes, validate, ship.
