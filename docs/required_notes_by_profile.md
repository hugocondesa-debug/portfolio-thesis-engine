# Required notes by profile

Completeness checklist consumed by the extraction validator
(`pte validate-extraction --profile Pn`). The lists below are mirrored
from
[`src/portfolio_thesis_engine/ingestion/raw_extraction_validator.py`](../src/portfolio_thesis_engine/ingestion/raw_extraction_validator.py)
(`REQUIRED_NOTES_BY_PROFILE` + `RECOMMENDED_NOTES_BY_PROFILE`).

The validator treats required-note coverage as a soft gate:

- **Required present** → `OK`.
- **Required missing** → `FAIL` under completeness (**does not block
  the pipeline**; surfaces on the audit report).
- **Recommended present** → `OK`.
- **Recommended missing** → `WARN`.

Completeness score = fraction of required + recommended notes present.
Target ≥ 90 % before shipping an extraction.

## P1 — Industrials / Services (shipped in Phase 1.5)

### Required (10)

| Note                       | Why it's required                                                                                                    |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `taxes`                    | Feeds Module A. Operating-tax rate drives NOPAT; without it the bridge falls back to WACC statutory with a flag.     |
| `leases`                   | Feeds Module C. IFRS 16 means every non-trivial company has material ROU assets and lease liabilities now.           |
| `ppe`                      | Gross / accumulated-depreciation movement table supports CapEx quality analysis and ROIC denominator sanity checks.  |
| `inventory`                | Inventory composition (raw / WIP / finished) feeds working-capital + operating-cycle analysis.                       |
| `trade_receivables`        | DSO calculation; turnover ratios; working-capital walk.                                                              |
| `trade_payables`           | DPO; capital-efficiency view on supplier financing.                                                                  |
| `employee_benefits`        | Headcount + total compensation feed revenue-per-head + productivity ratios.                                          |
| `financial_instruments`    | Credit / liquidity / market-risk narrative. Feeds scenario calibration and the Ficha's risk section.                 |
| `commitments_contingencies`| Off-balance-sheet obligations affect the equity bridge (contingent liabilities, operating-lease commitments).        |
| `provisions`               | Feeds Module B. Restructuring / impairment classifications drive the B.2.* adjustments.                              |

### Recommended (5)

| Note                         | Why it's recommended                                                                                           |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `goodwill`                   | Critical when the company has acquired growth. `impairment` field feeds `B.2.goodwill_impairment`.             |
| `intangibles`                | Amortisation split (customer relationships, software, brand) informs durability of competitive advantage.      |
| `share_based_compensation`   | SBC expense reconciliation. Feeds Module E (Phase 2) and the Ficha's dilution view.                            |
| `pensions`                   | DBO movement + plan-assets. Feeds Module D (Phase 2).                                                          |
| `acquisitions`               | One `AcquisitionItem` per material deal. Feeds capital-allocation history and goodwill reconciliation.         |

### Notes specific to P1 that are NOT required

Most P1 companies don't materially use:

- `orsa` / `sfcr` / `icaap` / `pillar_3` (insurance / banking-only)
- `ni_43_101` (mining-only)

If you're extracting a P1 filing and one of these surfaces, capture
it anyway in `notes.unknown_sections` — better to have it logged than
silently dropped.

## P2 — Banks (Phase 2)

**Status:** placeholder. The validator currently returns a `SKIP`
completeness result for P2 profiles.

Planned required set (for when P2 activates):

- `pillar_3` (Basel III RWA + capital adequacy)
- `icaap` (where public)
- `financial_instruments` (much richer for banks — credit-risk
  tables by stage, provision coverage, loan-book composition)
- `provisions` (loan-loss + credit provisions)
- `taxes` (still relevant)
- Bank-specific notes: loan book by stage, deposit composition, RWA
  by category. Requires schema additions in Phase 2.

Supporting markdown: Basel III / Pillar 3 primer to be added to the
P2 Claude.ai Project knowledge base.

## P3a — Insurance (Phase 2)

**Status:** placeholder.

Planned required set:

- `sfcr` (Solvency II public disclosure)
- `orsa` (where public)
- Insurance-specific: technical provisions, SCR / MCR, investment
  portfolio by category, premium earned / paid claims ratio.
  Schema additions required.

## P3b — REITs (Phase 2)

**Status:** placeholder.

Planned required set:

- `reit_supplement` if available as separate doc
- Property-level occupancy + WALE
- FFO / AFFO bridge
- NAV disclosure

## P4 — Natural Resources (Phase 2)

**Status:** placeholder.

Planned required set:

- `ni_43_101` (mining technical report)
- Reserves / resources by category (2P, 1P, contingent)
- Production guidance
- Commodity-price sensitivities

## P5 — Pre-revenue / Biotech (Phase 2)

**Status:** placeholder.

Planned required set:

- Pipeline assets with development stages
- Cash runway + burn rate
- Trial milestones + expected readout dates
- Partnership economics

## P6 — Holdings (Phase 2)

**Status:** placeholder.

Planned required set:

- Per-subsidiary financials
- Consolidation methodology
- NAV / sum-of-parts disclosure
- Inter-company transactions

## Completeness score interpretation

The validator computes:

```
completeness_score = notes_present / (len(required) + len(recommended))
```

For P1: `notes_present / 15`. Thresholds:

- **≥ 90 %** — ready to ship. Missing items are genuinely absent
  from the source document.
- **80 – 89 %** — acceptable for a first pass, but open the Claude.ai
  chat and verify the missing items really aren't in the PDF.
- **< 80 %** — go back. Something is being missed. Common causes:
  (a) skipped a pass during extraction; (b) looked in the wrong
  section of the PDF; (c) company genuinely uses a non-standard
  layout (flag in `extraction_notes`).

Validator output includes a per-note list (`C.R.<name>: OK/FAIL`)
so you can pinpoint what to fix.
