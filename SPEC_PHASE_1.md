# Portfolio Thesis Engine — Spec da Fase 1: EuroEyes End-to-End MVP

**Versão:** 1.0
**Data:** 21 Abril 2026
**Destinatário:** Claude Code (via Hugo Condesa)
**Pré-requisito:** Fase 0 completa, 352 testes a passar, `pte smoke-test` com `PTE_SMOKE_HIT_REAL_APIS=true` 8/8 OK
**Propósito:** Construir o primeiro pipeline completo que processa uma empresa do markdown à ficha visualizável.

---

## PARTE A — Overview

### A.1 — Propósito da Fase 1

Validar a arquitectura end-to-end processando **EuroEyes (1846.HK)** de forma completamente automatizada dentro da app. Primeira demonstração de que o sistema substitui o workflow de 40 conversas em Claude chat.

**Deliverable concreto:** um utilizador corre:

```bash
uv run pte ingest --ticker 1846.HK \
  --files annual_report_2024.md,interim_h1_2025.md,wacc_inputs.md

uv run pte process 1846.HK
```

E obtém:

- `CanonicalCompanyState` guardado e versionado
- `ValuationSnapshot` com 3 cenários e targets
- `Ficha` aggregate view
- UI Streamlit mostra a ficha EuroEyes

Total: **< 30 minutos wall clock, < $10 API cost, com preparação manual do markdown fora da app**.

### A.2 — Scope da Fase 1 — Thin Vertical Slice

A Fase 1 é deliberadamente **thin vertical slice**: cobre **todo** o pipeline mas com **subset** do método. Validação end-to-end prioriza sobre completude.

**IN scope (Fase 1):**
- Modo B ingestion (markdown completo do relatório)
- Section extractor LLM-driven para archetype P1
- Cross-check gate contra FMP + yfinance
- Extraction engine subset: Module A core (taxes) + Module C core (leases) + Module B minimal (provisions classification)
- Analysis derivation: IC summary, NOPAT bridge, key ratios
- DCF 3-scenario simples (Bear/Base/Bull)
- Ficha composer
- Streamlit UI read-only com ficha view
- Hook arquitectural para Modo A (interface preparada, implementação Fase 2)

**OUT of scope (Fase 2+):**
- Modo A ingestion (ficheiros raw/ pré-separados)
- Patches 1-7 (NCI, Associates, Discontinued Ops, Business Combinations, Hyperinflation, CTA, SOTP)
- Module D (Pensions), Module E (SBC), Module F (Capitalize Expenses)
- Reverse DDM / DCF, Monte Carlo, EPS bridge vs consensus, correlated stress
- Research/RAG (earnings calls, MD&A narrative, news)
- Scenario tuner interactivo
- Portfolio dashboard cross-empresa
- Update workflow pós-earnings
- Devil's advocate LLM
- Peer discovery runtime + extraction levels A/B/C
- Archetypes P2-P6
- Guardrails D/E/F detalhados (apenas A/V core)

### A.3 — Critérios de Aceitação

A Fase 1 está completa quando **todos** os seguintes passam:

1. `uv run pte ingest --ticker 1846.HK --files <markdown_files>` corre sem erros
2. `uv run pte process 1846.HK` corre end-to-end produzindo Canonical State + Valuation Snapshot + Ficha
3. Cross-check gate detecta discrepâncias entre extraction e FMP/yfinance nos níveis PASS/WARN/FAIL
4. `uv run pte show 1846.HK` (ou Streamlit UI) mostra ficha EuroEyes com identity, statements, scenarios, targets
5. Guardrails A/V core aplicáveis passam (ou FAIL visível ao utilizador)
6. Custo total: < $10 API para uma run completa EuroEyes
7. Tempo total: < 30 min wall clock (excluindo preparação manual do markdown)
8. Testes: coverage ≥80% nos novos módulos
9. Integration test end-to-end passa com fixtures EuroEyes (mocked LLM + market data)
10. Smoke test real com `PTE_SMOKE_HIT_REAL_APIS=true` processa fixture EuroEyes sintética com APIs reais

### A.4 — Arquitectura de Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ FORA da app (Hugo prepara)                                      │
│                                                                 │
│   PDF Annual Report → annual_report_2024.md                     │
│   PDF Interim Report → interim_h1_2025.md                       │
│   WACC_inputs.md (manual preenchido)                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ DENTRO da app (pipeline automático)                             │
│                                                                 │
│  1. Ingestion (Modo B)                                          │
│     Input: [*.md, wacc_inputs.md]                               │
│     Output: IngestedDocuments registered in filesystem          │
│                                                                 │
│  2. Section Extraction (LLM-driven)                             │
│     Input: IngestedDocuments                                    │
│     Output: StructuredSections (IS, BS, CF, Notes, MD&A, Segs)  │
│                                                                 │
│  3. Cross-check Gate                                            │
│     Input: Raw extracted values                                 │
│     vs: FMP /stable/ + yfinance                                 │
│     Output: CrossCheckReport (PASS/WARN/FAIL per metric)        │
│                                                                 │
│  4. Extraction Engine (Modules A, B, C subset)                  │
│     Input: StructuredSections + WACC_inputs                     │
│     Output: Reclassified Statements + Adjustments + Log         │
│                                                                 │
│  5. Analysis Derivation                                         │
│     Input: Reclassified Statements                              │
│     Output: IC, NOPAT Bridge, Ratios                            │
│                                                                 │
│  6. CanonicalCompanyState (persisted)                           │
│     Schema from Fase 0, versioned save                          │
│                                                                 │
│  7. Valuation Engine (DCF 3-scenario)                           │
│     Input: CanonicalCompanyState + WACC + Scenarios             │
│     Output: Targets by scenario, Weighted E[V], IRR decomp      │
│                                                                 │
│  8. ValuationSnapshot (persisted)                               │
│     Schema from Fase 0, versioned save                          │
│                                                                 │
│  9. Ficha Composer                                              │
│     Input: CanonicalCompanyState + ValuationSnapshot            │
│     Output: Ficha aggregate view                                │
│                                                                 │
│ 10. Streamlit UI                                                │
│     Read-only view of Ficha per ticker                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## PARTE B — Ingestion (Modo B primário, Modo A hook)

### B.1 — Responsabilidades

O módulo `ingestion` é o primeiro ponto de entrada ao sistema. Responsável por:

- Aceitar markdowns estruturados (Modo B) ou ficheiros pré-separados (Modo A, Fase 2)
- Validar que conteúdo parece razoável (tamanho mínimo, UTF-8, tem algumas palavras-chave financeiras)
- Registar documentos ingeridos como blobs no `DocumentRepository` (Fase 0)
- Emitir metadata: ticker, doc_type, data do report, fonte, timestamp ingestão
- Retornar `IngestionResult` consumível pelo próximo passo do pipeline

### B.2 — Estrutura de módulos

```
src/portfolio_thesis_engine/ingestion/
├── __init__.py
├── base.py              # IngestionMode ABC, IngestedDocument dataclass
├── bulk_markdown.py     # Modo B — markdown completo
├── pre_extracted.py     # Modo A — stub com NotImplementedError (Fase 2)
└── coordinator.py       # IngestionCoordinator que despacha por modo
```

### B.3 — Interface

```python
# ingestion/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class IngestedDocument:
    """A single document registered in the system."""
    doc_id: str                  # Stable ID, e.g. "1846-HK/annual_report_2024"
    ticker: str                  # Normalized ticker
    doc_type: str                # "annual_report" | "interim_report" | "wacc_inputs" | "other"
    source_path: Path            # Path to blob in DocumentRepository
    report_date: str | None      # ISO date if derivable
    content_hash: str            # SHA-256 of content
    ingested_at: datetime
    mode: str                    # "bulk_markdown" | "pre_extracted"
    metadata: dict               # Mode-specific metadata


@dataclass
class IngestionResult:
    """Result of an ingestion operation."""
    ticker: str
    documents: list[IngestedDocument]
    errors: list[str]            # Non-fatal warnings


class IngestionMode(ABC):
    """Base for ingestion modes."""
    
    @abstractmethod
    def ingest(
        self,
        ticker: str,
        files: list[Path],
    ) -> IngestionResult:
        """Process files and register documents."""
    
    @abstractmethod
    def validate(self, files: list[Path]) -> list[str]:
        """Return list of validation errors (empty = valid)."""
```

### B.4 — Modo B (BulkMarkdownMode)

```python
# ingestion/bulk_markdown.py

class BulkMarkdownMode(IngestionMode):
    """
    Accepts one or more large markdown files representing reports.
    
    Expected inputs per EuroEyes:
    - annual_report_2024.md  (~300 pages, 500k-1M tokens)
    - interim_h1_2025.md     (~100 pages, 200k-400k tokens)
    - wacc_inputs.md         (~200 lines, structured manual)
    
    Detection heuristics for doc_type:
    - Filename contains "annual" or "AR" → "annual_report"
    - Filename contains "interim" or "H1" or "Q" → "interim_report"
    - Filename is wacc_inputs.md → "wacc_inputs"
    - Else: "other"
    """
    
    def __init__(self, document_repo: DocumentRepository):
        self.document_repo = document_repo
    
    def ingest(self, ticker: str, files: list[Path]) -> IngestionResult:
        # 1. Validate
        errors = self.validate(files)
        if errors and all("FATAL" in e for e in errors):
            raise IngestionError(errors)
        
        # 2. For each file:
        #    - Compute content hash
        #    - Infer doc_type from filename
        #    - Extract report date if possible (from filename or content)
        #    - Register in DocumentRepository
        #    - Create IngestedDocument
        
        # 3. Return IngestionResult
        ...
    
    def validate(self, files: list[Path]) -> list[str]:
        errors = []
        for f in files:
            if not f.exists():
                errors.append(f"FATAL: {f} does not exist")
            if f.stat().st_size == 0:
                errors.append(f"FATAL: {f} is empty")
            if f.stat().st_size > 50_000_000:  # 50MB sanity cap
                errors.append(f"WARN: {f} is very large ({f.stat().st_size / 1e6:.1f}MB)")
            # Check UTF-8
            try:
                f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"FATAL: {f} is not valid UTF-8")
            # Sanity check: contains financial keywords
            content = f.read_text(encoding="utf-8", errors="ignore").lower()
            financial_words = ["revenue", "income", "equity", "cash", "assets"]
            if not any(w in content for w in financial_words):
                errors.append(f"WARN: {f} does not appear to be a financial report")
        return errors
```

### B.5 — Modo A (PreExtractedMode) — Stub

```python
# ingestion/pre_extracted.py

class PreExtractedMode(IngestionMode):
    """
    Stub for Fase 2. Accepts pre-separated raw/ files:
    - raw/01_bs_raw.md
    - raw/02_is_raw.md
    - raw/03_cf_raw.md
    - ...
    
    Implementation deferred to Fase 2.
    """
    
    def ingest(self, ticker: str, files: list[Path]) -> IngestionResult:
        raise NotImplementedError("PreExtractedMode is Fase 2")
    
    def validate(self, files: list[Path]) -> list[str]:
        return ["FATAL: PreExtractedMode is Fase 2, use BulkMarkdownMode"]
```

### B.6 — IngestionCoordinator

```python
# ingestion/coordinator.py

class IngestionCoordinator:
    """Despatches ingestion to the appropriate mode."""
    
    def __init__(
        self,
        document_repo: DocumentRepository,
        metadata_repo: MetadataRepository,
    ):
        self.modes = {
            "bulk_markdown": BulkMarkdownMode(document_repo),
            "pre_extracted": PreExtractedMode(),
        }
        self.metadata_repo = metadata_repo
    
    def ingest(
        self,
        ticker: str,
        files: list[Path],
        mode: str = "bulk_markdown",
    ) -> IngestionResult:
        if mode not in self.modes:
            raise ValueError(f"Unknown mode: {mode}")
        
        result = self.modes[mode].ingest(ticker, files)
        
        # Register ticker in metadata if new
        self.metadata_repo.upsert_company(ticker=ticker, profile="P1")
        
        return result
```

### B.7 — Tests

- `test_bulk_markdown_mode.py`: validation edge cases (empty, non-UTF8, not financial), happy path roundtrip
- `test_pre_extracted_mode.py`: raises NotImplementedError
- `test_coordinator.py`: mode dispatch, ticker normalisation, metadata registration

Coverage target: ≥85%.

---

## PARTE C — Section Extractor (LLM-driven)

### C.1 — Responsabilidade

Este é o **módulo mais crítico** da Fase 1. Transforma markdown corrido (potencialmente 500k tokens) em **structured sections** consumíveis pelo extraction engine.

### C.2 — Estrutura de módulos

```
src/portfolio_thesis_engine/section_extractor/
├── __init__.py
├── base.py              # SectionExtractor ABC, StructuredSection dataclass
├── p1_extractor.py      # P1 Industrial archetype
├── prompts.py           # Prompt templates
├── tools.py             # Tool definitions for structured output
└── validator.py         # Post-extraction validation
```

### C.3 — Definição de Section

```python
# section_extractor/base.py

@dataclass(frozen=True)
class StructuredSection:
    """A recognized and extracted section of a financial report."""
    section_type: str               # "income_statement" | "balance_sheet" | "cash_flow" | "segments" | "mda" | "notes_leases" | etc
    title: str                      # Original title from document
    content: str                    # Markdown content
    page_range: tuple[int, int] | None
    fiscal_period: str | None       # "FY2024" | "H1 2025" | etc
    confidence: float               # 0.0-1.0 heuristic confidence
    extraction_method: str          # "llm_section_detection" | "pre_separated"


@dataclass
class ExtractionResult:
    """All sections extracted from a document."""
    doc_id: str
    ticker: str
    fiscal_period: str
    sections: list[StructuredSection]
    unresolved: list[str]           # Sections we couldn't identify
    warnings: list[str]


class SectionExtractor(ABC):
    """Base for section extractors (archetype-specific)."""
    
    @abstractmethod
    def extract(self, document: IngestedDocument) -> ExtractionResult:
        """Process document, return structured sections."""
```

### C.4 — P1 Industrial Extractor

Strategy: **chunked LLM extraction with structured output via tool use**.

O documento pode ser grande (500k+ tokens). Processar inteiro num único call seria caro e lento. Strategy:

1. **Pass 1 — Table of Contents (rápido, small context):**
   - Primeira section: pedir LLM para localizar índice do documento
   - Identifica page ranges por section
   - Output: mapa `{section_type: (start_page, end_page)}`

2. **Pass 2 — Per-section extraction (parallel, focused):**
   - Para cada section identificada no Pass 1, extrai o chunk correspondente
   - LLM focado só nessa section (smaller context, melhor precisão)
   - Usa tool use estruturado para forçar output em schema

3. **Pass 3 — Validation (Python):**
   - Confirma que sections core existem (IS, BS, CF)
   - Valida que períodos batem (se AR 2024, todas as sections têm FY2024 ou FY2023 comparativo)

### C.5 — Sections esperadas P1 Industrial

Para archetype P1 (industrial), esperar-se:

**Obrigatórias (FATAL se ausentes):**
- `income_statement` — Consolidated Income Statement
- `balance_sheet` — Consolidated Balance Sheet
- `cash_flow` — Consolidated Cash Flow Statement

**Altamente recomendadas (WARN se ausentes):**
- `segments` — Segment information (revenue, margin by segment/geography)
- `notes_revenue` — Revenue recognition note
- `notes_taxes` — Income tax reconciliation
- `notes_leases` — Leases disclosure (IFRS 16)
- `mda` — Management Discussion & Analysis

**Opcionais (INFO se ausentes):**
- `notes_pensions` — Post-employment benefits (ignored in Fase 1, Module D is Fase 2)
- `notes_sbc` — Share-based compensation (ignored in Fase 1, Module E is Fase 2)
- `notes_provisions` — Provisions detail
- `notes_goodwill` — Goodwill + impairment testing
- `operating_data` — KPIs, operational data
- `esg` — ESG disclosure

### C.6 — Tool definition para structured output

Exemplo de tool definition para extracção de Income Statement:

```python
# section_extractor/tools.py

INCOME_STATEMENT_TOOL = {
    "name": "extract_income_statement",
    "description": "Extract structured income statement data from text",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {
                "type": "string",
                "description": "Fiscal period, e.g. 'FY2024' or 'H1 2025'"
            },
            "currency": {
                "type": "string",
                "description": "Reporting currency, e.g. 'HKD', 'EUR'"
            },
            "currency_unit": {
                "type": "string",
                "enum": ["units", "thousands", "millions", "billions"],
                "description": "Whether values are in units, thousands, millions, or billions"
            },
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value_current": {"type": "number"},
                        "value_prior": {"type": "number", "nullable": True},
                        "category": {
                            "type": "string",
                            "enum": ["revenue", "cost_of_sales", "opex", "d_and_a", "operating_income", "finance", "tax", "net_income", "other"]
                        },
                        "notes_reference": {"type": "string", "nullable": True}
                    },
                    "required": ["label", "value_current", "category"]
                }
            }
        },
        "required": ["fiscal_period", "currency", "currency_unit", "line_items"]
    }
}
```

Tools análogos para:
- `extract_balance_sheet`
- `extract_cash_flow`
- `extract_segments`
- `extract_leases_disclosure`
- `extract_tax_reconciliation`
- `extract_mda_narrative`

### C.7 — Prompts

```python
# section_extractor/prompts.py

SECTION_IDENTIFICATION_PROMPT = """
You are analyzing a financial report markdown file. Your task is to identify the structure of the document by locating key sections.

For each section found, return:
- section_type (one of the known types)
- title as written in the document
- approximate page range (if page markers exist) or character range
- fiscal period covered

Known section types for industrial companies (P1):
- income_statement
- balance_sheet
- cash_flow
- segments
- notes_revenue
- notes_taxes
- notes_leases
- notes_pensions
- notes_sbc
- mda
- operating_data

Be rigorous: only report sections you can actually locate in the text.
Return via the tool `report_sections_found`.
"""

INCOME_STATEMENT_EXTRACTION_PROMPT = """
Extract the income statement from this text chunk.

Focus on:
- All line items (labels and values)
- Fiscal period
- Currency and unit scale (millions, thousands, etc)
- Prior year comparatives if present

Be careful with:
- Parentheses indicating negative values, convert to negative numbers
- "Cost of sales" vs "Cost of goods sold" — normalize to "cost_of_sales"
- D&A may be shown as line item or included within other expenses
- Operating income may be labeled as EBIT, Operating profit, etc
- Tax may show as "(Tax expense)" or "Taxation"

Return via the tool `extract_income_statement`. Do not invent values.
"""
```

### C.8 — Validator (post-extraction)

```python
# section_extractor/validator.py

class ExtractionValidator:
    """Validates extracted sections for internal consistency."""
    
    def validate(self, result: ExtractionResult) -> list[ValidationIssue]:
        issues = []
        
        # 1. Core sections present
        required = {"income_statement", "balance_sheet", "cash_flow"}
        found = {s.section_type for s in result.sections}
        for req in required:
            if req not in found:
                issues.append(ValidationIssue("FATAL", f"Missing {req}"))
        
        # 2. Fiscal period consistency
        periods = {s.fiscal_period for s in result.sections if s.fiscal_period}
        if len(periods) > 2:  # Current + prior year
            issues.append(ValidationIssue(
                "WARN",
                f"Multiple fiscal periods detected: {periods}. Ensure we're extracting consistent snapshot."
            ))
        
        # 3. Currency consistency
        # (extract currency from each section, should match across IS/BS/CF)
        
        # 4. Checksum: IS total checks
        # Revenue - costs = operating income (within rounding)
        # Operating income - tax - interest = net income (within rounding)
        
        return issues
```

### C.9 — Custo estimado

Para EuroEyes AR 2024 (~300 páginas, ~500k tokens):

| Pass | Tokens in | Tokens out | Model | Cost |
|---|---|---|---|---|
| 1. Section ID | 500k | 2k | Sonnet | ~$1.80 |
| 2. Per-section × 8 sections | 200k total | 10k total | Sonnet | ~$0.75 |
| 3. Validation | Python, 0 tokens | - | - | $0 |

**Total por documento: ~$2.55**. Para AR + Interim: ~$5.

Para reduzir: Pass 1 pode usar Haiku (10x cheaper) com prompt mais simples para localização de TOC. Poupança: ~$1.50.

### C.10 — Tests

- `test_bulk_markdown_extractor.py`: fixtures de sample markdown (uma IS simples, um BS simples)
- `test_prompts.py`: snapshot testing de prompts (detectar regressões silenciosas)
- `test_validator.py`: validation issues raised appropriately
- `test_cost_tracking.py`: confirma que cost tracker regista cada call

Integration test com LLM real (gated): processa um markdown pequeno real da EuroEyes e confirma que sections core são identificadas.

Coverage target: ≥80%.

---

## PARTE D — Cross-Check Gate

### D.1 — Responsabilidade

Após extraction mas antes de analysis, validar valores extraídos contra fontes externas (FMP + yfinance) para detectar erros silenciosos de LLM.

### D.2 — Estrutura

```
src/portfolio_thesis_engine/cross_check/
├── __init__.py
├── base.py              # CrossCheckReport, CrossCheckMetric dataclasses
├── gate.py              # CrossCheckGate main class
└── thresholds.py        # Threshold configuration
```

### D.3 — Métricas cross-checkable

Métricas que ambas APIs publicam de forma razoavelmente consistente:

| Métrica | FMP field | yfinance field | Tolerance typical |
|---|---|---|---|
| Revenue (latest FY) | `income-statement.revenue` | `income_stmt.Total Revenue` | 1-2% (restated common) |
| Operating income | `income-statement.operatingIncome` | `income_stmt.Operating Income` | 2-5% (classification differences) |
| Net income | `income-statement.netIncome` | `income_stmt.Net Income` | 1-2% |
| Total assets | `balance-sheet.totalAssets` | `balance_sheet.Total Assets` | <1% |
| Total equity | `balance-sheet.totalStockholdersEquity` | `balance_sheet.Stockholders Equity` | <1% |
| Cash | `balance-sheet.cashAndCashEquivalents` | `balance_sheet.Cash` | <1% |
| Operating cash flow | `cash-flow-statement.operatingCashFlow` | `cashflow.Operating Cash Flow` | 1-2% |
| Capex | `cash-flow-statement.capitalExpenditure` | `cashflow.Capital Expenditures` | 1-2% |
| Shares outstanding | `key-metrics.sharesOutstanding` | `info.sharesOutstanding` | <1% |
| Market cap | `key-metrics.marketCap` | `info.marketCap` | <1% (date-dependent) |

### D.4 — Thresholds configuration

```python
# cross_check/thresholds.py

DEFAULT_THRESHOLDS = {
    "PASS": 0.02,      # < 2% difference
    "WARN": 0.10,      # 2-10% difference
    # > 10% → FAIL
    "sources_disagree": 0.05,  # If FMP and yfinance differ by > 5% between themselves
}

# Can be overridden per-metric via .env or YAML config
# E.g. for restated companies, revenue tolerance might need to be 5%
METRIC_SPECIFIC_THRESHOLDS = {
    "operating_income": {"PASS": 0.05, "WARN": 0.15},  # Classification differences common
}
```

### D.5 — Gate logic

```python
# cross_check/gate.py

@dataclass
class CrossCheckMetric:
    """Single metric cross-check result."""
    metric: str
    extracted_value: Decimal
    fmp_value: Decimal | None
    yfinance_value: Decimal | None
    max_delta_pct: Decimal         # max(|ext-fmp|, |ext-yf|) / |ext|
    status: str                    # PASS | WARN | FAIL | SOURCES_DISAGREE | UNAVAILABLE
    notes: str = ""


@dataclass
class CrossCheckReport:
    """Full cross-check result for a ticker."""
    ticker: str
    period: str
    metrics: list[CrossCheckMetric]
    overall_status: str            # PASS | WARN | FAIL
    blocking: bool                 # True if should pause pipeline
    generated_at: datetime


class CrossCheckGate:
    """Validates extracted values against external sources."""
    
    def __init__(
        self,
        fmp_provider: FMPProvider,
        yfinance_provider: YFinanceProvider,
        thresholds: dict = DEFAULT_THRESHOLDS,
    ):
        self.fmp = fmp_provider
        self.yfinance = yfinance_provider
        self.thresholds = thresholds
    
    async def check(
        self,
        ticker: str,
        extracted_values: dict[str, Decimal],
        period: str,
    ) -> CrossCheckReport:
        # 1. Fetch both sources in parallel
        fmp_data = await self.fmp.get_fundamentals(ticker)
        yf_data = await self.yfinance.get_fundamentals(ticker)
        
        # 2. For each cross-checkable metric:
        #    - Get extracted value
        #    - Get FMP value (may be None if not published for this ticker)
        #    - Get yfinance value (may be None)
        #    - Compute max_delta_pct
        #    - Assign status based on thresholds
        
        # 3. Overall status: worst status across metrics
        
        # 4. Blocking rule: overall_status == FAIL
        
        # 5. Write log file: logs/cross_check/{ticker}_{date}.json
        
        return report
```

### D.6 — User interaction

Quando gate retorna FAIL:

**In CLI (`pte process`):**
```
⚠️  Cross-check FAILED for 1846.HK:
   - Revenue (FY2024): extracted=HKD 580M, FMP=HKD 582M (0.3%) ✓ PASS
   - Net income (FY2024): extracted=HKD 620M, FMP=HKD 62M (10x) ✗ FAIL
   - Total assets: extracted=HKD 3200M, FMP=HKD 3180M (0.6%) ✓ PASS

Options:
  1. Override and continue (requires confirmation)
  2. Abort pipeline to investigate
  3. Re-run section extraction with stricter prompt

Choice [1/2/3]:
```

**In Streamlit UI** (future):
- Warning banner at top of ficha
- Click "Investigate" → shows diff table
- "Override" button with required rationale

### D.7 — Tests

- `test_gate_happy.py`: all metrics PASS
- `test_gate_warn.py`: one WARN, overall status WARN
- `test_gate_fail.py`: one FAIL, overall status FAIL, blocking=True
- `test_sources_disagree.py`: FMP and yfinance differ >5% between themselves
- `test_unavailable.py`: neither source has data for a metric
- `test_tolerance_override.py`: metric-specific threshold applies
- `test_report_persistence.py`: log file written correctly

Integration test gated: real API calls for 1846.HK, validate actual response shapes.

Coverage target: ≥90%. This module is critical to correctness.

---

## PARTE E — Extraction Engine (Modules A, B, C subset)

### E.1 — Responsabilidade

Aplicar metodologia estruturada às `StructuredSections` para produzir **reclassified statements** e **adjustments** conforme Modules A-F (F1 implementa subset: A core + B minimal + C core).

### E.2 — Escopo Fase 1

**Module A — Operating Taxes:**
- A.1 Hierarquia de taxas (statutory → effective → cash)
- A.2.0 Teste de materialidade non-operating
- A.2.1-A.2.5 Tax table reconciliation (parcial, casos simples)
- A.3 DTA/DTL classificação básica
- A.4 Conversão para cash taxes
- A.5 Tratamento no BS reorganizado

**NÃO inclui:** A.6 valuation de TLCF, A.7 templates avançados, A.9 extensões sectoriais (P4 royalty, P2 tax shield).

**Module B — Provisions Classification:**
- B.0 Aplicabilidade
- B.1 Operating profit vs EBITA framework
- B.2 Non-operating items minimal (goodwill impairment, restructuring one-off óbvios)

**NÃO inclui:** B.3-B.10 treatment detalhado de múltiplas categorias.

**Module C — Leases:**
- C.0 Aplicabilidade
- C.1 IFRS 16 base identification
- C.2 Capitalization basics (já parte de reclassified BS)
- C.3 Lease additions para FCFF economic view

**NÃO inclui:** C.4+ treatment detalhado, operating vs finance lease distinctions.

**Modules D, E, F — SKIP (Fase 2):**
- D Pensions
- E SBC
- F Capitalize Expenses

### E.3 — Estrutura

```
src/portfolio_thesis_engine/extraction/
├── __init__.py
├── base.py              # ExtractionContext, ExtractionResult
├── coordinator.py       # ExtractionCoordinator
├── module_a_taxes.py
├── module_b_provisions.py
├── module_c_leases.py
├── analysis.py          # IC, NOPAT bridge, ratios
└── archetypes/
    ├── __init__.py
    └── p1_industrial.py  # P1-specific orchestration
```

### E.4 — ExtractionCoordinator

```python
# extraction/coordinator.py

class ExtractionCoordinator:
    """Orchestrates extraction modules in correct order."""
    
    def __init__(
        self,
        profile: Profile,
        llm_provider: AnthropicProvider,
        cost_tracker: CostTracker,
    ):
        self.profile = profile
        self.llm = llm_provider
        self.cost_tracker = cost_tracker
        self.modules = self._load_modules_for_profile()
    
    def _load_modules_for_profile(self) -> list[ExtractionModule]:
        if self.profile == Profile.P1_INDUSTRIAL:
            return [
                ModuleATaxes(self.llm, self.cost_tracker),
                ModuleBProvisions(self.llm, self.cost_tracker),
                ModuleCLeases(self.llm, self.cost_tracker),
                # D, E, F deferred to Fase 2
            ]
        raise NotImplementedError(f"Profile {self.profile} not in Fase 1")
    
    async def extract(
        self,
        sections: list[StructuredSection],
        wacc_inputs: WACCInputs,
    ) -> ExtractionResult:
        context = ExtractionContext(
            sections=sections,
            wacc_inputs=wacc_inputs,
            adjustments=[],
            decision_log=[],
            estimates_log=[],
        )
        
        for module in self.modules:
            context = await module.apply(context)
            # Each module appends to adjustments, decision_log, estimates_log
        
        # After modules: derive analysis
        analysis = AnalysisDeriver().derive(context)
        
        return ExtractionResult(
            canonical_state=build_canonical_state(context, analysis),
            guardrails_results=run_guardrails_a(context),
            cost_breakdown=self.cost_tracker.session_total(),
        )
```

### E.5 — Module A (taxes) example

```python
# extraction/module_a_taxes.py

class ModuleATaxes(ExtractionModule):
    """Operating taxes normalization per Module A methodology."""
    
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        # 1. Find tax reconciliation in sections
        tax_section = self._find_section(context, "notes_taxes")
        if not tax_section:
            context.estimates_log.append("Module A: No tax reconciliation note found, using statutory rate")
            effective_tax = self._compute_from_is(context)
        else:
            # 2. LLM-parse the tax reconciliation table
            tax_recon = await self._parse_tax_reconciliation(tax_section)
            
            # 3. Classify adjustments (operational vs non-operational)
            classified = self._classify_adjustments(tax_recon)
            
            # 4. Compute operating tax rate
            operating_tax = self._compute_operating_tax(classified)
        
        # 5. Update context with adjustment + log entry
        context.adjustments.append(ModuleAdjustment(
            module="A.2",
            description="Operating tax rate normalization",
            amount=Decimal(operating_tax),
            affected_periods=[context.current_period],
            rationale="Separated non-operating items per A.2.2",
        ))
        context.decision_log.append(
            f"Module A: operating tax rate = {operating_tax:.2%}"
        )
        
        return context
```

### E.6 — Module B (provisions minimal)

```python
# extraction/module_b_provisions.py

class ModuleBProvisions(ExtractionModule):
    """Minimal provisions classification — just separate non-operating items."""
    
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        # Identify obvious non-operating items in IS:
        # - Goodwill impairment → non-operating
        # - Restructuring (if large, one-off nature) → non-operating
        # - Gains/losses on asset sales → non-operating
        
        is_section = self._find_section(context, "income_statement")
        for line in is_section.line_items:
            label = line.label.lower()
            if "goodwill impairment" in label or "restructuring" in label:
                # Classify and log
                context.adjustments.append(...)
        
        return context
```

### E.7 — Module C (leases core)

```python
# extraction/module_c_leases.py

class ModuleCLeases(ExtractionModule):
    """Lease reclassification per IFRS 16."""
    
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        # 1. Find leases note
        leases_section = self._find_section(context, "notes_leases")
        if not leases_section:
            context.estimates_log.append("Module C: No leases note, assuming no material leases")
            return context
        
        # 2. LLM-parse lease disclosure:
        #    - Right-of-use assets by category
        #    - Lease liabilities (current + non-current)
        #    - Depreciation of ROU in period
        #    - Interest expense on lease liabilities
        #    - Total lease payments (cash outflow)
        lease_data = await self._parse_leases_disclosure(leases_section)
        
        # 3. Compute "lease additions" (new leases capitalized in period)
        lease_additions = self._compute_additions(lease_data, context)
        
        context.adjustments.append(ModuleAdjustment(
            module="C.3",
            description="Lease additions for FCFF economic view",
            amount=lease_additions,
            affected_periods=[context.current_period],
            rationale="Include as investment in Total Reinvestment per P1 methodology",
        ))
        
        return context
```

### E.8 — Analysis Derivation

```python
# extraction/analysis.py

class AnalysisDeriver:
    """Derives IC summary, NOPAT bridge, and ratios from reclassified statements."""
    
    def derive(self, context: ExtractionContext) -> AnalysisDerived:
        # 1. Invested Capital:
        #    Operating Assets - Operating Liabilities = IC
        ic = self._compute_invested_capital(context)
        
        # 2. NOPAT Bridge:
        #    EBITA - Operating taxes = NOPAT
        #    NOPAT + Financial Income - Financial Expense - Non-operating items = Reported NI
        nopat_bridge = self._compute_nopat_bridge(context)
        
        # 3. Key Ratios:
        #    ROIC = NOPAT / IC
        #    ROE, Operating Margin, EBITDA Margin, Net Debt/EBITDA, etc
        ratios = self._compute_ratios(context, ic, nopat_bridge)
        
        return AnalysisDerived(
            invested_capital_by_period=[ic],
            nopat_bridge_by_period=[nopat_bridge],
            ratios_by_period=[ratios],
            capital_allocation=None,  # Fase 2
        )
```

### E.9 — Tests

- `test_module_a_taxes.py`: simple tax recon parse, classification, rate computation
- `test_module_b_provisions.py`: goodwill impairment detection, restructuring
- `test_module_c_leases.py`: lease disclosure parse, additions computation
- `test_coordinator.py`: module ordering, context passing
- `test_analysis.py`: IC, NOPAT bridge, ratios math
- `test_archetype_p1.py`: full P1 pipeline with fixture

Coverage target: ≥85%.

---

## PARTE F — Valuation Engine (DCF 3-scenario subset)

### F.1 — Responsabilidade

Produzir `ValuationSnapshot` com 3 scenarios (Bear, Base, Bull) via DCF FCFF, incluindo targets, E[V] ponderado, IRR decomposition.

### F.2 — Escopo Fase 1

**IN:**
- FCFF DCF 3-scenario
- Terminal value (Gordon growth)
- Mid-year discounting
- WACC from `WACC_inputs.md`
- Equity bridge (EV → Equity → per share)
- E[V] probability-weighted
- IRR decomposition (fundamentals vs re-rating) — simple
- Football field visualization data

**OUT (Fase 2+):**
- Reverse DCF / expectations matrix
- Monte Carlo
- Correlated stress
- EPS bridge vs consensus
- SOTP (Patches)
- Sensitivity tables multi-dimensional

### F.3 — Estrutura

```
src/portfolio_thesis_engine/valuation/
├── __init__.py
├── base.py              # ValuationEngine ABC
├── dcf.py               # FCFF DCF engine
├── scenarios.py         # Scenario definition + probability weighting
├── equity_bridge.py     # EV → Equity → per share
├── irr.py               # IRR decomposition
└── composer.py          # Builds ValuationSnapshot
```

### F.4 — DCF Engine

```python
# valuation/dcf.py

class FCFFDCFEngine:
    """FCFF DCF with mid-year discounting and Gordon terminal."""
    
    def compute_target(
        self,
        scenario: ScenarioInputs,
        wacc: Decimal,
        canonical_state: CanonicalCompanyState,
    ) -> DCFResult:
        # 1. Project FCFF for N years (default 10)
        projected_fcff = self._project_fcff(scenario, canonical_state)
        
        # 2. Terminal value: TV = FCFF_N+1 / (WACC - g_terminal)
        tv = self._compute_terminal(projected_fcff[-1], scenario, wacc)
        
        # 3. Discount with mid-year convention:
        #    Year 1 discount exponent: 0.5
        #    Year 2: 1.5
        #    ...
        #    Year N: N - 0.5
        #    TV discount exponent: N
        pv_explicit = sum(
            fcff / (1 + wacc) ** (i + 0.5)
            for i, fcff in enumerate(projected_fcff)
        )
        pv_terminal = tv / (1 + wacc) ** len(projected_fcff)
        
        enterprise_value = pv_explicit + pv_terminal
        
        return DCFResult(
            enterprise_value=enterprise_value,
            pv_explicit=pv_explicit,
            pv_terminal=pv_terminal,
            implied_g=scenario.drivers.terminal_growth,
            wacc_used=wacc,
            terminal_value=tv,
        )
```

### F.5 — Scenario composition

```python
# valuation/scenarios.py

@dataclass
class ScenarioInputs:
    """Manual scenario inputs for Fase 1."""
    label: str                           # "bear" | "base" | "bull"
    probability: Decimal
    drivers: ScenarioDrivers             # From schemas/valuation.py
    
    # Fase 1: simple drivers
    # revenue_cagr (%)
    # terminal_growth (%)
    # terminal_operating_margin (%)
    # wacc (from WACC_inputs, same across scenarios unless overridden)


class ScenarioComposer:
    """Builds 3 scenarios (Bear, Base, Bull) from user inputs."""
    
    def compose(
        self,
        user_inputs: dict,                # From WACC_inputs.md or interactive
        canonical_state: CanonicalCompanyState,
    ) -> list[Scenario]:
        scenarios = []
        for label in ["bear", "base", "bull"]:
            inputs = self._load_scenario_inputs(user_inputs, label)
            dcf_result = self.dcf_engine.compute_target(inputs, ...)
            equity_value = self.equity_bridge.compute(dcf_result, canonical_state)
            irr = self.irr_engine.decompose(equity_value, canonical_state)
            
            scenarios.append(Scenario(
                label=label,
                probability=inputs.probability,
                drivers=inputs.drivers,
                targets={"dcf_fcff": equity_value},
                irr_3y=irr.y3,
                irr_5y=irr.y5,
                irr_decomposition=irr.decomposition,
                upside_pct=(equity_value - current_price) / current_price * 100,
            ))
        
        # Validate probabilities sum to 1
        assert abs(sum(s.probability for s in scenarios) - 1) < 0.01
        
        return scenarios
```

### F.6 — Equity bridge

```python
# valuation/equity_bridge.py

class EquityBridge:
    """EV → Equity Value → Per Share."""
    
    def compute(
        self,
        dcf_result: DCFResult,
        canonical_state: CanonicalCompanyState,
    ) -> EquityValue:
        ev = dcf_result.enterprise_value
        
        # Subtract financial claims senior to common equity:
        net_debt = canonical_state.get_net_debt()
        preferred = canonical_state.get_preferred_equity()
        nci = canonical_state.get_nci()
        lease_liab = canonical_state.get_lease_liabilities()  # Already in EV from economic view
        
        equity_to_common = ev - net_debt - preferred - nci
        # Note: lease_liab NOT subtracted because FCFF economic view already treated leases as investment
        
        shares = canonical_state.identity.shares_outstanding
        per_share = equity_to_common / shares
        
        return EquityValue(
            equity_value=equity_to_common,
            per_share=per_share,
            shares_outstanding=shares,
        )
```

### F.7 — IRR decomposition

```python
# valuation/irr.py

class IRRDecomposer:
    """Decomposes IRR into: fundamental growth + dividend yield + re-rating."""
    
    def decompose(
        self,
        target_price: Decimal,
        current_price: Decimal,
        canonical_state: CanonicalCompanyState,
        horizon_years: int = 3,
    ) -> IRRResult:
        # IRR components:
        # 1. BV growth p.a. (or equity growth)
        # 2. Dividend yield p.a. (assumed, from history if no forecast)
        # 3. P/BV (or similar multiple) re-rating p.a.
        
        # Total IRR: (target_price / current_price) ^ (1/horizon) - 1
        total_irr = (target_price / current_price) ** (Decimal(1) / horizon_years) - 1
        
        # Decomposition requires some assumption about dividend and BV path
        # Fase 1: simplified — attribute to BV growth and re-rating only, 0 dividend
        
        # Current P/BV
        current_pbv = current_price / canonical_state.get_bvps()
        # Target P/BV at horizon (assume same terminal multiple)
        target_pbv = target_price / canonical_state.get_bvps_at_horizon(horizon_years)
        
        rerating_pa = (target_pbv / current_pbv) ** (Decimal(1) / horizon_years) - 1
        bv_growth_pa = total_irr - rerating_pa  # Simplification
        
        return IRRResult(
            total_p_a=total_irr,
            bv_growth_p_a=bv_growth_pa,
            rerating_p_a=rerating_pa,
            dividend_yield_p_a=Decimal(0),
            horizon_years=horizon_years,
        )
```

### F.8 — Composer

```python
# valuation/composer.py

class ValuationComposer:
    """Composes final ValuationSnapshot from components."""
    
    def compose(
        self,
        canonical_state: CanonicalCompanyState,
        scenarios: list[Scenario],
        market: MarketSnapshot,
    ) -> ValuationSnapshot:
        # Probability-weighted E[V]
        expected_value = sum(s.probability * s.targets["dcf_fcff"] for s in scenarios)
        
        # Fair value range
        fv_low = min(s.targets["dcf_fcff"] for s in scenarios)
        fv_high = max(s.targets["dcf_fcff"] for s in scenarios)
        
        weighted = WeightedOutputs(
            expected_value=expected_value,
            expected_value_method_used="DCF_FCFF",
            fair_value_range_low=fv_low,
            fair_value_range_high=fv_high,
            upside_pct=(expected_value - market.price) / market.price * 100,
            asymmetry_ratio=self._compute_asymmetry(scenarios, market.price),
            weighted_irr_3y=sum(s.probability * s.irr_3y for s in scenarios if s.irr_3y),
        )
        
        # Guardrails F (cross-temporal) — subset for Fase 1
        guardrails = self._run_guardrails_f(scenarios, canonical_state)
        
        return ValuationSnapshot(
            snapshot_id=self._new_id(),
            ticker=canonical_state.identity.ticker,
            company_name=canonical_state.identity.name,
            profile=canonical_state.identity.profile,
            valuation_date=datetime.now(timezone.utc),
            based_on_extraction_id=canonical_state.extraction_id,
            based_on_extraction_date=canonical_state.extraction_date,
            market=market,
            scenarios=scenarios,
            weighted=weighted,
            reverse=None,               # Fase 3
            cross_checks=None,          # Fase 3
            eps_bridge=None,            # Fase 3
            catalysts=[],               # Fase 2 — populated manually for now
            conviction=Conviction(      # Initialized, editable later
                forecast=ConvictionLevel.MEDIUM,
                valuation=ConvictionLevel.MEDIUM,
                asymmetry=ConvictionLevel.MEDIUM,
                timing_risk=ConvictionLevel.MEDIUM,
                liquidity_risk=ConvictionLevel.MEDIUM,
                governance_risk=ConvictionLevel.MEDIUM,
            ),
            guardrails=guardrails,
            forecast_system_version="0.1-fase1",
            total_api_cost_usd=self.cost_tracker.session_total(),
        )
```

### F.9 — Tests

- `test_dcf.py`: FCFF projection, terminal value, discount factors correctness
- `test_equity_bridge.py`: EV → equity with various capital structures
- `test_irr.py`: decomposition math
- `test_scenarios.py`: probability normalization, scenario ordering
- `test_composer.py`: ValuationSnapshot schema compliance

Coverage target: ≥85%.

---

## PARTE G — Ficha Composer

### G.1 — Responsabilidade

Combinar `CanonicalCompanyState` + `ValuationSnapshot` + market data live numa `Ficha` aggregate.

### G.2 — Implementação

```python
# ficha/composer.py

class FichaComposer:
    """Composes Ficha from canonical state + valuation snapshot."""
    
    def compose(
        self,
        canonical_state: CanonicalCompanyState,
        valuation_snapshot: ValuationSnapshot,
        current_market: MarketSnapshot,
    ) -> Ficha:
        return Ficha(
            ticker=canonical_state.identity.ticker,
            identity=canonical_state.identity,
            thesis=None,                    # User-added later
            current_extraction_id=canonical_state.extraction_id,
            current_valuation_snapshot_id=valuation_snapshot.snapshot_id,
            position=None,                  # From position repo if exists
            conviction=valuation_snapshot.conviction,
            monitorables=[],                # Fase 2
            tags=[],
            market_contexts=canonical_state.identity.market_contexts,
            snapshot_age_days=self._compute_age(valuation_snapshot),
            is_stale=self._is_stale(valuation_snapshot),
            next_earnings_expected=None,    # From metadata repo if set
            version=1,
            created_at=datetime.now(timezone.utc),
        )
```

Coverage target: ≥90%.

---

## PARTE H — Streamlit UI

### H.1 — Responsabilidade

Página dedicada que mostra `Ficha` da empresa seleccionada. Read-only na Fase 1.

### H.2 — Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Portfolio Thesis Engine                        [Settings]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Ticker selector: 1846.HK ▼]                                   │
│                                                                 │
│  ┌─── IDENTITY ────────────────────────────────────────────┐   │
│  │  EuroEyes Medical Group (1846.HK)                       │   │
│  │  P1 Industrial · Healthcare Operator                    │   │
│  │  HKD · HKEX · Reports FY ending December                │   │
│  │  Shares out: XXX.X M | Market cap: HKD X.XB             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── VALUATION ───────────────────────────────────────────┐   │
│  │  E[V] ponderado: HKD X.XX per share                     │   │
│  │  Upside: +X.X% (vs current HKD Y.YY)                    │   │
│  │  Fair value range: HKD X.X — X.X                        │   │
│  │                                                          │   │
│  │  FOOTBALL FIELD                                          │   │
│  │  Bear (30%) ████░░░░░░░░░░░░░░░░  X.X                   │   │
│  │  Base (45%) ████████████░░░░░░░░  Y.Y                   │   │
│  │  Bull (25%) ████████████████████  Z.Z                   │   │
│  │     ▼ current                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── SCENARIOS DETAIL ────────────────────────────────────┐   │
│  │  [Bear] [Base] [Bull]   (tabs)                          │   │
│  │                                                          │   │
│  │  Probability: 45%                                        │   │
│  │  Revenue CAGR: 8%                                        │   │
│  │  Terminal margin: 18%                                    │   │
│  │  Terminal g: 3%                                          │   │
│  │  WACC: 8.5%                                              │   │
│  │                                                          │   │
│  │  Target: HKD Y.YY                                        │   │
│  │  IRR (3Y): XX.X% = fund XX% + re-rating XX%             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── FINANCIALS (last 3 years) ──────────────────────────┐   │
│  │  [IS] [BS] [CF]   (tabs)                               │   │
│  │  Revenue:     HKD 500M → 520M → 580M  (+8% / +12%)     │   │
│  │  EBITDA:      HKD 80M → 90M → 110M    (ST%)             │   │
│  │  NOPAT:       HKD 50M → 55M → 70M                       │   │
│  │  ROIC:        12% → 13% → 15%                           │   │
│  │  ...                                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── GUARDRAILS STATUS ───────────────────────────────────┐   │
│  │  Overall: PASS                                          │   │
│  │  A (Extraction): 4/4 PASS                               │   │
│  │  V (Validation): 5/5 PASS                               │   │
│  │  F (Cross-temporal): N/A (Fase 2)                       │   │
│  │  Cross-check: PASS (max delta 1.2% vs FMP/yfinance)     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [View raw data] [Download as YAML] [View audit log]            │
└─────────────────────────────────────────────────────────────────┘
```

### H.3 — Implementação

```python
# ui/pages/ficha_view.py

import streamlit as st
from portfolio_thesis_engine.storage.yaml_repo import CompanyRepository, ValuationRepository
from portfolio_thesis_engine.ficha.composer import FichaComposer

def render():
    st.title("Portfolio Thesis Engine")
    
    # Ticker selector
    company_repo = CompanyRepository()
    available_tickers = company_repo.list_keys()
    ticker = st.selectbox("Ticker", available_tickers)
    
    if not ticker:
        st.info("No companies processed yet. Run `pte process <ticker>` first.")
        return
    
    # Load ficha
    ficha = load_ficha(ticker)  # Composes on-demand from repos
    
    # Identity section
    render_identity(ficha)
    
    # Valuation section
    render_valuation(ficha)
    
    # Scenarios detail
    render_scenarios(ficha)
    
    # Financials
    render_financials(ficha)
    
    # Guardrails
    render_guardrails(ficha)
```

### H.4 — Tests

- `test_ficha_view.py`: via `streamlit.testing.v1.AppTest` (padrão estabelecido em Fase 0)
- Mock do CompanyRepository/ValuationRepository
- Verificar que secções renderizam sem erros quando ficha tem dados
- Verificar que aviso aparece quando ticker não existe

Coverage target: best effort (Streamlit testing é limitado).

---

## PARTE I — CLI Commands

### I.1 — Comandos novos Fase 1

```bash
# Ingestion
pte ingest --ticker 1846.HK \
  --files path/to/annual_report_2024.md,path/to/interim_h1_2025.md,path/to/wacc_inputs.md \
  [--mode bulk_markdown|pre_extracted]  # default: bulk_markdown

# Process (end-to-end pipeline)
pte process 1846.HK  # Uses previously ingested documents

# Individual stages (for debugging)
pte extract-sections 1846.HK   # Only section extraction
pte run-modules 1846.HK        # Only Modules A/B/C
pte valuate 1846.HK            # Only valuation given extracted state

# Display
pte show 1846.HK               # Terminal summary of ficha
pte show 1846.HK --full        # Detailed with scenarios + financials

# Audit
pte cross-check 1846.HK        # Re-run cross-check independently
pte audit 1846.HK              # Show decision log + estimates log + guardrails
```

### I.2 — Update `pte smoke-test`

Adicionar aos smoke tests existentes:

- Fase 1 pipeline smoke test (fixture sintética EuroEyes): ingestion → sections → cross-check mocked → extraction → valuation → ficha. Não toca APIs reais.
- Integration gated: Fase 1 real com `PTE_SMOKE_HIT_REAL_APIS=true`, fixture markdown minimalista, APIs reais.

### I.3 — Tests

- `test_cli_ingest.py`, `test_cli_process.py`, `test_cli_show.py`
- Via `typer.testing.CliRunner`
- Mock do pipeline coordinator

---

## PARTE J — Testing Strategy

### J.1 — Unit Tests

Por módulo, conforme especificado em cada Parte. Target: ≥80% novos módulos.

### J.2 — Integration Tests

`tests/integration/test_phase1_pipeline.py`:

1. **test_ingestion_to_sections**: small markdown → ingestion → section extraction (mocked LLM) → sections produced
2. **test_sections_to_canonical**: sections → modules A/B/C (mocked) → canonical state
3. **test_canonical_to_valuation**: canonical state + scenarios → ValuationSnapshot
4. **test_valuation_to_ficha**: canonical + snapshot → ficha
5. **test_end_to_end_pipeline**: ingestion → ... → ficha, com fixtures e mocks
6. **test_cross_check_integration**: extracted values vs FMP mock + yfinance mock → PASS report

### J.3 — Fixtures

`tests/fixtures/euroeyes/`:
- `annual_report_2024_minimal.md` — ~10 pages of structured financial data (IS, BS, CF, notes básicas) for testing
- `interim_h1_2025_minimal.md` — ~5 pages
- `wacc_inputs.md` — complete WACC_inputs for EuroEyes P1
- `expected_canonical_state.yaml` — expected output after extraction
- `expected_valuation_snapshot.yaml` — expected output after valuation

Estas fixtures são **minimal mas realistas** — não são o AR completo mas têm estrutura suficiente para exercitar todo o pipeline.

### J.4 — Smoke Tests Reais

`PTE_SMOKE_HIT_REAL_APIS=true pte smoke-test`:

- Existing 8 checks from Fase 0
- New Fase 1 check: processes minimal EuroEyes fixture through pipeline with real APIs, validates output structure

Custo esperado: ~$0.50-1.00 por execução (small fixture, mas still multi-pass LLM).

### J.5 — Critérios de pass

- Todos os unit tests verdes
- Todos os integration tests verdes (com mocks)
- `PTE_SMOKE_HIT_REAL_APIS=true pte smoke-test`: 9/9 pass
- Manual smoke test: processar EuroEyes real (AR + Interim) end-to-end, verificar ficha razoável no Streamlit

---

## PARTE K — Sequência de Sprints

Proposta de 10 sprints para Fase 1. Cada sprint tem deliverable testável.

### Sprint 1 — Ingestion (BulkMarkdownMode)
- `ingestion/base.py`, `bulk_markdown.py`, `pre_extracted.py` (stub), `coordinator.py`
- Tests unit
- CLI `pte ingest` básico
- Deliverable: ingestar markdown + validar formato + registar em DocumentRepository

### Sprint 2 — Section Extractor (Pass 1: TOC identification)
- `section_extractor/base.py`, tools para TOC
- Prompt para identificar sections
- Tests com fixtures
- Deliverable: dar markdown, receber mapa de sections

### Sprint 3 — Section Extractor (Pass 2: Per-section parsing)
- Tools para extract_income_statement, extract_balance_sheet, extract_cash_flow
- Prompts específicos por tipo de section
- Tests com fixtures pequenas
- Deliverable: StructuredSection objects com dados extraídos

### Sprint 4 — Section Extractor (Pass 3: Validator)
- `validator.py` com checks internal consistency
- Tests
- Integração no pipeline
- Deliverable: ExtractionResult validated

### Sprint 5 — Cross-Check Gate
- `cross_check/` completo (base, gate, thresholds)
- Integration com FMP + yfinance
- CLI `pte cross-check`
- Tests
- Deliverable: gate operacional, user interaction em FAIL

### Sprint 6 — Extraction Modules A + B
- `extraction/base.py`, `coordinator.py`, `module_a_taxes.py`, `module_b_provisions.py`
- Tests
- Deliverable: tax reconciliation + provisions classification aplicados

### Sprint 7 — Module C + Analysis Derivation
- `module_c_leases.py`, `analysis.py`
- CanonicalCompanyState assembled
- Tests
- Deliverable: canonical state produzido para fixture EuroEyes

### Sprint 8 — Valuation Engine (DCF + Equity Bridge + IRR)
- `valuation/` completo
- Tests unit
- Deliverable: ValuationSnapshot com 3 scenarios para fixture

### Sprint 9 — Ficha Composer + Streamlit UI
- `ficha/composer.py`
- `ui/pages/ficha_view.py`
- CLI `pte show`
- Tests (unit + Streamlit AppTest)
- Deliverable: ficha visível via CLI e Streamlit

### Sprint 10 — Integration + End-to-End + Documentation
- Integration tests all combining
- Smoke tests update
- Real AR EuroEyes processing end-to-end
- Docs: `docs/phase1_architecture.md`, sprint reports
- Deliverable: Fase 1 oficialmente completa

**Total estimado:** 10 sprints × 15-45 min Claude Code = **2-7 horas de implementação**. Com validação humana entre batches, **1-2 semanas calendar**.

---

## PARTE L — Decisões Arquitecturais Antecipadas

Alguns pontos que podem surgir durante implementação. Preferências já tomadas:

1. **LLM model selection**: Sonnet para extraction/analysis; Opus para cross-check interaction quando FAIL (requires human-like explanation); Haiku para simple classification.

2. **Async vs sync**: Todos os LLM calls async (anthropic SDK). Section extractor paralleliza per-section extractions com `asyncio.gather`.

3. **Retry logic**: Herda de Fase 0 (`llm/retry.py`). Extraction específica tem retry com max 3 tentativas.

4. **Cost caps**: Hard cap `PTE_LLM_MAX_COST_PER_COMPANY_USD` do .env (default $15). Se exceder, pipeline aborta com erro claro.

5. **Idempotência**: `pte process` idempotente — se ficha já existe, re-run cria nova versão (versioned) em vez de sobrescrever. `--force` flag para re-processing completo.

6. **Fixture strategy**: Testes unit usam fixtures sintéticas minimalistas. Integration tests usam fixtures realísticas mas pequenas. Real AR processing é manual/CLI, não testa automaticamente (evitar lock-in a dados externos mutáveis).

7. **Error handling**: Cada stage do pipeline tem typed exceptions. Coordinator captura e decide: continuar com warning, abortar com error claro, pedir confirmação humana.

8. **Logging**: Cada pipeline run produz `logs/runs/{ticker}_{timestamp}.jsonl` com eventos estruturados. Útil para debug e audit.

---

## PARTE M — Pontos em aberto

Coisas a decidir durante implementação (não bloqueantes para arrancar):

1. **Caching de LLM responses**: valueOf Phase 1 não faz caching. Se o mesmo documento for reprocessado, LLM calls repetem. Fase 2 pode adicionar cache por content hash.

2. **Multi-document reconciliation**: Como o sistema lida com AR + Interim report — deveria produzir um single canonical state que combina ambos? Ou dois estados separados? Proposta: combinar, com Interim overriding AR em campos conflito (mais recente ganha).

3. **Language handling**: EuroEyes reporta em inglês. Fase 1 assume inglês. Fase 2+ pode adicionar detecção de língua e tradução.

4. **PDF quality degradation**: Se markdown input tem tabelas mal convertidas de PDF, LLM extraction pode falhar. Fase 1 assume quality razoável. Fase 2 pode adicionar pre-processing para limpar markdown mal formatado.

---

## Notas finais

Claude Code, ao implementar:

1. **Respeita o scope.** Fase 1 é deliberadamente slim. Não sucumbes à tentação de implementar "enquanto estou aqui". Patches 1-7, Modules D/E/F, reverse DCF, Monte Carlo, research/RAG — tudo Fase 2+.

2. **Fidelidade aos schemas Fase 0.** Todos os objectos produzidos devem serializar correctamente com schemas Pydantic existentes. Qualquer campo novo requer actualização explícita de schema.

3. **Cross-check rigorosamente.** A validação FMP+yfinance é o guardrail anti-regressão. Se um valor extraído falha cross-check consistentemente, é bug de extraction, não tolerância a apertar.

4. **Fixtures realísticas.** Testes com fixtures pequenas mas estruturalmente correctas. Testes que só passam com dados artificiais demasiado limpos não dão confiança.

5. **Cost awareness.** Cada sprint reporta custo acumulado em LLM. Se custo real ultrapassa estimativa em >50%, flag para review.

6. **Reports sprint-a-sprint.** Mesmo formato disciplina Fase 0.

Se ambiguidade real surgir, para e pergunta ao Hugo.

Boa construção. No fim da Fase 1, tens o primeiro sistema end-to-end que processa uma empresa real automaticamente.

---

**Fim da Spec Fase 1**
