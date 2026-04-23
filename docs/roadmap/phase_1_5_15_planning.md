# Phase 1.5.15 — Document-Type-Aware Pipeline (DEFERRED)

**Status**: Documented for future implementation. Deferred in favour
of Phase 2 Sprint 1 (Historical Normalization).

## Problem statement

Current pipeline (post-Phase 1.5.14) requires income_statement to be
present for primary period (with relaxation for unaudited documents
where BS/CF can be absent). This blocks ingestion of:

- Investor day decks (long-term targets, KPIs, no current period IS/BS/CF)
- Earnings call transcripts (Q&A, guidance, forward statements)
- Strategic update presentations (M&A announcements, divestitures)
- ESG / sustainability reports (carbon KPIs, no financial statements)

These documents are valuable sources of:
- Multi-year strategic plans (3-5 year guidance)
- Capital allocation framework specificity
- Operational KPI deep-dive
- Real-time guidance updates and revisions
- Q&A insights revealing analyst concerns
- Tone analysis (sentiment from CEO/CFO)

For active portfolio management, missing these sources is significant.

## Recommended architectural approach: PATH B+C hybrid

Single RawExtraction schema with optional financial_statements
section, validator behavior driven by document_type.

### Schema changes

```python
class RawExtraction(BaseModel):
    metadata: DocumentMetadata
    income_statement: dict[str, IncomeStatementBlock] | None = None  # NOW OPTIONAL
    balance_sheet: dict[str, BalanceSheetBlock] | None = None
    cash_flow: dict[str, CashFlowBlock] | None = None
    notes: list[Note] = Field(default_factory=list)
    narrative: NarrativeBlock | None = None
    segments: SegmentsBlock | None = None
    operational_kpis: OperationalKPIsBlock | None = None
```

### Document validation matrix

```python
DOCUMENT_VALIDATION_REQUIREMENTS = {
    "annual_report": {
        "required_sections": ["income_statement", "balance_sheet", "cash_flow"],
        "warn_if_missing": [],
        "audit_status_default": "audited",
    },
    "interim_report": {
        "required_sections": ["income_statement"],
        "warn_if_missing": ["balance_sheet", "cash_flow"],
        "audit_status_default": "reviewed",
    },
    "preliminary_results": {
        "required_sections": ["income_statement"],
        "warn_if_missing": [],
        "audit_status_default": "unaudited",
    },
    "investor_presentation": {
        "required_sections": [],
        "warn_if_missing": ["income_statement"],
        "audit_status_default": "unaudited",
    },
    "investor_day_deck": {
        "required_sections": ["narrative"],
        "warn_if_missing": [],
        "audit_status_default": "unaudited",
    },
    "earnings_call_transcript": {
        "required_sections": ["narrative"],
        "warn_if_missing": [],
        "audit_status_default": "unaudited",
    },
    "strategic_update": {
        "required_sections": ["narrative"],
        "warn_if_missing": [],
        "audit_status_default": "unaudited",
    },
    "esg_report": {
        "required_sections": ["operational_kpis"],
        "warn_if_missing": [],
        "audit_status_default": "audited",  # often externally assured
    },
}
```

### Pipeline stage adaptations

| Stage              | Current behavior            | Phase 1.5.15 behavior                    |
|--------------------|-----------------------------|------------------------------------------|
| load_extraction    | Loads RawExtraction         | Same                                     |
| validate_extraction| Strict IS/BS/CF             | Type-aware: per matrix above             |
| cross_check        | Runs FMP/yfinance compare   | SKIP if no income_statement              |
| decompose_notes    | Decomposes IS/BS/CF lines   | SKIP if no notes                         |
| extract_canonical  | Numeric + narrative         | Builds adaptive canonical_state shape    |
| guardrails         | Numeric checks              | SKIP financial checks if no financials   |
| valuate            | DCF/multiples               | SKIP if no financials → narrative-only   |
| persist_valuation  | Stores valuation snapshot   | SKIP if no valuation                     |
| compose_ficha      | Aggregates to ficha         | Merges narrative across multiple docs    |

### Canonical state shape

```python
class CanonicalCompanyState(BaseSchema):
    # Existing
    metadata: ...

    # Make optional
    financial_data: FinancialData | None = None

    # Always preserved (already Phase 1.5.14)
    narrative_context: NarrativeContext | None = None

    # New
    operational_kpis: OperationalKPIs | None = None

    # Tracking
    source_document_type: str
    source_document_id: str
```

### Ficha aggregation strategy

When multiple documents exist for same period:
- Latest financial data wins (AR > preliminary)
- Narrative is MERGED across all sources
- Source attribution preserved per item to distinguish AR vs call vs deck
- Operational KPIs merged (deck typically has more depth)

### CLI workflow examples

```bash
# Ingest investor day deck
pte ingest --ticker 1846.HK \
  --extraction ~/data_inputs/euroeyes/investor_day_2025.yaml

# Ingest earnings call transcript
pte ingest --ticker 1846.HK \
  --extraction ~/data_inputs/euroeyes/h1_2025_call_transcript.yaml

# Process: pipeline picks correct documents per period
pte process 1846.HK --base-period H1_2025
# → Selects interim AR + h1_2025_call_transcript
# → Narrative summary integrates both sources
# → Valuation from interim financial data
# → Ficha shows multi-source narrative
```

### Effort estimate

- Schema relaxation + tests: 1.5h
- Validator type-aware logic + tests: 1.5h
- Pipeline stage adaptations + tests: 2h
- Ficha multi-source merging + tests: 1h
- Documentation: 0.5h

Total: 4-6h Claude Code

### Tag

v0.4.0-phase1-5-15-document-types

### Trigger conditions

Implement when ANY of:
- User has 5+ qualitative documents pending ingest
- Earnings call/investor day extraction available for portfolio holdings
- Phase 2 Sprint 7 (Qualitative Extraction Layer) reached in roadmap
- Specific company analysis blocked by qualitative-only document

### Notes

This phase enables information richness beyond financial statements.
Particularly valuable for:
- Real-time guidance tracking (calls happen quarterly)
- Strategic plan tracking (investor days yearly)
- ESG positioning analysis
- Multi-year capital allocation framework analysis
