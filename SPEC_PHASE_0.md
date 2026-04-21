# Portfolio Thesis Engine — Spec da Fase 0: Foundations

**Versão:** 1.0
**Data:** 20 Abril 2026
**Destinatário:** Claude Code (via Hugo Condesa)
**Propósito:** Estabelecer as fundações técnicas sobre as quais as Fases 1-6 constroem

---

## PARTE A — Overview e Contexto

### A.1 — O que é o projecto

`portfolio-thesis-engine` é uma aplicação Python para gestão semi-automatizada de portfolio de investimento com valuation rigorosa. Substitui um workflow actual de 40+ conversas manuais por sessão de trabalho por uma aplicação unificada correndo num VPS.

O sistema tem três objectivos:
1. **Valuation engine** — aplica metodologia estruturada (extraction + forecast + valuation multi-método) a cada empresa, produzindo snapshots versionados e imutáveis
2. **Portfolio management activo** — dashboard cross-portfolio, tracking de teses, scenario tuner, update review pós-earnings
3. **Knowledge base unificada** — todos os documentos indexados e queryable, com factor exposures e correlações

### A.2 — O que a Fase 0 resolve

A Fase 0 estabelece o **andaime técnico** sobre o qual todas as lógicas de negócio (Fases 1-6) vão construir. **Não inclui lógica de negócio** — nenhum DCF, nenhuma extracção, nenhum parser, nenhum dashboard com conteúdo.

Especificamente, Fase 0 entrega:

- Repositório Python estruturado com dependencies pinned
- Pydantic schemas para todos os objectos estruturais (Canonical Company State, Valuation Snapshot, Position, Ficha, Peer, Scenario, Market Context)
- Storage layer abstracto com Repository classes para 5 layers (YAMLs git-versioned, DuckDB, ChromaDB, Filesystem, SQLite)
- LLM orchestrator multi-provider (Anthropic primary, OpenAI embeddings only, extensível)
- Market data provider abstracto (FMP como primeira implementação)
- Guardrails framework base
- CLI skeleton com comandos `setup`, `health-check`, `smoke-test`
- VPS provisioning script (Ubuntu 24.04, Python 3.12, systemd, backup)
- Testing infrastructure (pytest, fixtures, mocks)
- README e docs de contribuição

### A.3 — Critérios de Aceitação

A Fase 0 está completa quando **todos** os seguintes passam:

```bash
# No VPS, com repo clonado e .env configurado:
cd ~/workspace/portfolio-thesis-engine
uv sync                              # Instala dependencies
uv run pytest                        # Todos os tests passam
uv run pte health-check              # CLI reporta sistema operacional
uv run pte smoke-test                # Smoke tests end-to-end passam
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
# Streamlit arranca em localhost:8501 mostrando página vazia
```

Smoke tests obrigatórios:
- **Storage**: criar Company, ler de volta, guardar nova versão de Valuation, recuperar histórico
- **LLM**: chamada Anthropic + OpenAI embeddings com cost tracking funcional
- **Config**: carregar `.env`, validar schema, detectar keys em falta
- **Guardrails**: runner executa guardrail trivial, produz GuardrailResult correcto

### A.4 — Stack Técnica Finalizada

| Camada | Tecnologia | Versão |
|---|---|---|
| Runtime | Python | 3.12+ |
| Package manager | uv | latest |
| Schemas / validation | pydantic | 2.x |
| Config | pydantic-settings | 2.x |
| Linting/formatting | ruff | latest |
| Testing | pytest + pytest-asyncio + pytest-cov | latest |
| HTTP client | httpx | latest |
| YAML | pyyaml | latest |
| Analytics DB | duckdb | 0.10+ |
| Vector DB | chromadb | 0.5+ |
| Metadata DB | sqlalchemy + sqlite | 2.x |
| UI | streamlit | latest |
| CLI | typer | latest |
| LLM — Anthropic | anthropic | latest |
| LLM — OpenAI (embeddings only) | openai | latest |
| Logging | structlog | latest |
| Env management | python-dotenv | latest |

### A.5 — Glossário

- **Canonical Company State** — output estruturado do Sistema 1 (extraction). Contém statements reclassificados, ajustamentos aplicados, análise derivada, validação, vintage tags. Imutável após extraction completa.
- **Valuation Snapshot** — output estruturado do Sistema 2 (forecast + valuation). Contém cenários, targets, E[IRR], guardrails status. Versionado; cada nova valuation cria novo snapshot.
- **Ficha** — objecto aggregado que compõe todos os outputs de uma empresa numa vista única. Consumido pelo portfolio system.
- **Scenario** — definição de um cenário (Bear/Base/Bull) com drivers, probabilidade, survival conditions.
- **Profile / Archetype** — P1-P6 (Industrial, Banks, Insurance, REITs, Resources, Pre-Revenue, Holdings). Determina schemas específicos e métodos aplicáveis.
- **Cluster / Market Context** — agrupamento de empresas por dinâmica de mercado (ex: "UK specialist banks", "luxury goods"). Empresas referenciam clusters.
- **Repository** — classe Python que abstrai acesso a storage. Módulos nunca acedem ficheiros/DBs directamente — sempre via Repository.
- **Guardrail** — verificação automática (A=extraction, D=valuation, E=ratios, F=cross-temporal) que valida integridade analítica.

---

## PARTE B — Repo Structure

### B.1 — Árvore completa

```
portfolio-thesis-engine/
├── .env.example
├── .gitignore
├── .python-version              # Fixa Python 3.12
├── LICENSE                      # MIT
├── README.md
├── pyproject.toml
├── uv.lock                      # Commitado
│
├── src/
│   └── portfolio_thesis_engine/
│       ├── __init__.py
│       │
│       ├── shared/              # Infraestrutura partilhada
│       │   ├── __init__.py
│       │   ├── config.py        # Settings (pydantic-settings)
│       │   ├── logging_.py      # structlog setup
│       │   ├── exceptions.py    # Custom exception hierarchy
│       │   └── types.py         # Type aliases, enums
│       │
│       ├── schemas/             # Pydantic models
│       │   ├── __init__.py
│       │   ├── base.py          # Base classes, mixins
│       │   ├── common.py        # Shared types (Money, Percentage, DateRange)
│       │   ├── company.py       # CanonicalCompanyState
│       │   ├── valuation.py     # ValuationSnapshot, Scenario
│       │   ├── ficha.py         # Ficha (aggregate)
│       │   ├── position.py      # Position, PortfolioState
│       │   ├── peer.py          # Peer
│       │   └── market_context.py  # MarketContext (extensível)
│       │
│       ├── storage/             # Repository layer
│       │   ├── __init__.py
│       │   ├── base.py          # Repository base class, interfaces
│       │   ├── yaml_repo.py     # YAML file repository
│       │   ├── duckdb_repo.py   # DuckDB analytics
│       │   ├── chroma_repo.py   # ChromaDB RAG
│       │   ├── filesystem_repo.py  # Blob storage
│       │   ├── sqlite_repo.py   # SQLite metadata
│       │   └── unit_of_work.py  # Transaction boundaries
│       │
│       ├── llm/                 # LLM orchestrator
│       │   ├── __init__.py
│       │   ├── base.py          # LLMProvider interface
│       │   ├── anthropic_provider.py
│       │   ├── openai_provider.py   # Embeddings only
│       │   ├── router.py        # Model routing logic
│       │   ├── retry.py         # Retry with exponential backoff
│       │   ├── cost_tracker.py  # Token + cost tracking
│       │   └── structured.py    # Tool use helpers
│       │
│       ├── market_data/         # Market data providers
│       │   ├── __init__.py
│       │   ├── base.py          # MarketDataProvider interface
│       │   └── fmp_provider.py  # FMP implementation
│       │
│       ├── guardrails/          # Validation framework
│       │   ├── __init__.py
│       │   ├── base.py          # Guardrail, GuardrailResult
│       │   ├── runner.py        # GuardrailRunner
│       │   └── results.py       # Result aggregation, reporting
│       │
│       ├── cli/                 # Typer CLI
│       │   ├── __init__.py
│       │   ├── app.py           # Main CLI app
│       │   ├── setup_cmd.py     # `pte setup`
│       │   ├── health_cmd.py    # `pte health-check`
│       │   └── smoke_cmd.py     # `pte smoke-test`
│       │
│       └── ui/                  # Streamlit (stub)
│           ├── __init__.py
│           └── app.py           # Placeholder; Fase 1 enche
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Fixtures partilhadas
│   ├── fixtures/
│   │   ├── sample_company.yaml
│   │   ├── sample_valuation.yaml
│   │   └── sample_filing.pdf    # Small test PDF
│   ├── unit/
│   │   ├── test_schemas.py
│   │   ├── test_storage.py
│   │   ├── test_llm.py
│   │   ├── test_market_data.py
│   │   ├── test_guardrails.py
│   │   └── test_config.py
│   └── integration/
│       ├── test_storage_integration.py
│       ├── test_llm_integration.py  # Requer API keys
│       └── test_smoke.py
│
├── scripts/
│   ├── provision_vps.sh         # Bootstrap VPS
│   ├── backup.sh                # rclone backup
│   └── deploy.sh                # Deploy to VPS
│
├── systemd/
│   ├── pte-streamlit.service    # Streamlit service
│   └── pte-backup.timer         # Daily backup timer
│
└── docs/
    ├── architecture.md          # Arquitectura high-level
    ├── schemas.md               # Reference dos schemas
    └── contributing.md          # Como contribuir
```

### B.2 — `pyproject.toml` completo

```toml
[project]
name = "portfolio-thesis-engine"
version = "0.1.0"
description = "Semi-automated portfolio management with rigorous valuation"
requires-python = ">=3.12"
authors = [{name = "Hugo Condesa"}]
license = {text = "MIT"}
readme = "README.md"

dependencies = [
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "anthropic>=0.40",
    "openai>=1.50",
    "duckdb>=1.0",
    "chromadb>=0.5",
    "sqlalchemy>=2.0",
    "streamlit>=1.38",
    "typer>=0.12",
    "structlog>=24.1",
    "python-dotenv>=1.0",
    "rich>=13.7",
    "tenacity>=9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "pytest-mock>=3.14",
    "ruff>=0.6",
    "mypy>=1.11",
    "ipython>=8.26",
]

[project.scripts]
pte = "portfolio_thesis_engine.cli.app:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/portfolio_thesis_engine"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "UP",  # pyupgrade
    "SIM", # flake8-simplify
    "RET", # flake8-return
    "PTH", # flake8-use-pathlib
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-v --cov=portfolio_thesis_engine --cov-report=term-missing"
asyncio_mode = "auto"
markers = [
    "integration: integration tests requiring external services",
    "slow: tests that take >1s",
]

[tool.mypy]
python_version = "3.12"
strict = true
```

### B.3 — `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST
.pytest_cache/
.coverage
.coverage.*
.cache
htmlcov/
.tox/
.nox/
.hypothesis/

# Virtual environments
.venv/
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Secrets (CRITICAL)
.env
.env.local
.env.production
*.pem
*.key
!*.key.example

# Data (never commit)
data/
!data/.gitkeep
backup/
*.duckdb
*.sqlite
*.sqlite3
chromadb/
documents/

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Streamlit
.streamlit/secrets.toml
```

### B.4 — `.env.example`

```bash
# ============================================================
# Portfolio Thesis Engine — Environment Variables
# Copy this file to .env and fill in real values
# NEVER commit .env to git
# ============================================================

# --- LLM Providers ---
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...       # Only used for embeddings

# --- Market Data ---
FMP_API_KEY=...                   # Financial Modeling Prep

# --- Paths ---
PTE_DATA_DIR=/home/user/workspace/portfolio-thesis-engine/data
PTE_BACKUP_DIR=/home/user/workspace/portfolio-thesis-engine/backup

# --- LLM Model Selection ---
PTE_LLM_MODEL_JUDGMENT=claude-opus-4-7      # Julgamento crítico (devil's advocate, narrativa final)
PTE_LLM_MODEL_ANALYSIS=claude-sonnet-4-6    # Análise standard (extraction, synthesis)
PTE_LLM_MODEL_CLASSIFICATION=claude-haiku-4-5-20251001  # Classificação barata
PTE_LLM_MODEL_EMBEDDINGS=text-embedding-3-small

# --- Cost controls ---
PTE_LLM_MAX_COST_PER_COMPANY_USD=15.0
PTE_LLM_MAX_TOKENS_PER_REQUEST=200000

# --- Logging ---
PTE_LOG_LEVEL=INFO
PTE_LOG_FORMAT=json                # json | console

# --- Feature flags ---
PTE_ENABLE_COST_TRACKING=true
PTE_ENABLE_GUARDRAILS=true
PTE_ENABLE_TELEMETRY=false
```

### B.5 — `README.md` inicial

```markdown
# Portfolio Thesis Engine

Semi-automated portfolio management with rigorous valuation.

## Quick Start

```bash
# Clone
git clone https://github.com/hugocondesa-debug/portfolio-thesis-engine.git
cd portfolio-thesis-engine

# Install dependencies
uv sync

# Configure
cp .env.example .env
# Edit .env with your API keys

# Verify installation
uv run pte health-check
uv run pytest

# Launch UI
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

## Structure

See `docs/architecture.md`.

## Status

**Phase 0** — Foundations ✓
- Repo structure, schemas, storage layer, LLM orchestrator, guardrails framework, CLI, DevOps

**Phase 1** — Portfolio System MVP (next)
- Parser of forecast outputs, Dashboard, Scenario tuner, Ficha viewer

## License

MIT
```

---

## PARTE C — Pydantic Schemas

Todos os schemas usam **Pydantic v2**. Convenções:

- Fields obrigatórios vs opcionais claramente marcados
- `Field(..., description=...)` para documentação
- Validators onde aplicável
- `model_config = ConfigDict(frozen=True)` para immutable objects (snapshots)
- UTC timestamps sempre
- Enums em vez de strings livres onde aplicável

### C.1 — `schemas/common.py` — Tipos comuns

```python
"""Common types shared across schemas."""

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Currency(str, Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    CHF = "CHF"
    JPY = "JPY"
    HKD = "HKD"
    # Extensível conforme necessário


class Profile(str, Enum):
    """Archetype do sector da empresa."""
    P1_INDUSTRIAL = "P1"
    P2_BANKS = "P2"
    P3A_INSURANCE = "P3a"
    P3B_REITS = "P3b"
    P4_RESOURCES = "P4"
    P5_PRE_REVENUE = "P5"
    P6_HOLDINGS = "P6"


class ConvictionLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GuardrailStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    REVIEW = "REVIEW"
    NOTA = "NOTA"


class ConfidenceTag(str, Enum):
    """Tags de confiança de dados (vintage)."""
    REPORTED = "REPORTED"        # Do relatório oficial
    CALCULATED = "CALCULATED"    # Computado de dados reportados
    ESTIMATED = "ESTIMATED"      # Estimativa com método documentado
    ADJUSTED = "ADJUSTED"        # Ajustado por methodology
    ALIGNED = "ALIGNED"          # Alinhado com vintage mais recente


# Type aliases
Money = Annotated[Decimal, Field(description="Monetary amount, precision preserved")]
Percentage = Annotated[Decimal, Field(ge=-100, le=1000, description="Percentage, e.g. 12.5 = 12.5%")]
BasisPoints = Annotated[int, Field(description="Basis points, e.g. 250 = 2.5%")]


class MoneyWithCurrency(BaseModel):
    """Monetary value with explicit currency."""
    amount: Money
    currency: Currency

    model_config = ConfigDict(frozen=True)


class DateRange(BaseModel):
    """Date range for periods."""
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class FiscalPeriod(BaseModel):
    """Fiscal period identifier, e.g. FY2025 or Q3-2025."""
    year: int = Field(ge=1990, le=2100)
    quarter: int | None = Field(default=None, ge=1, le=4)
    label: str  # e.g., "FY2025", "Q3 2025"

    def __str__(self) -> str:
        return self.label


class Source(BaseModel):
    """Documentation of data source."""
    document: str                                    # e.g., "Annual Report 2024"
    page: int | None = None
    confidence: ConfidenceTag = ConfidenceTag.REPORTED
    url: str | None = None
    accessed: str | None = None                      # ISO date
```

### C.2 — `schemas/base.py` — Base classes

```python
"""Base classes and mixins for schemas."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base for all schemas in the system."""
    model_config = ConfigDict(
        extra="forbid",                # Reject unknown fields
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ImmutableSchema(BaseSchema):
    """Base for immutable objects (snapshots)."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,                   # Immutable after creation
    )


class VersionedMixin(BaseModel):
    """Mixin for versioned entities."""
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(default="system")
    previous_version: str | None = None  # Reference to previous version id


class AuditableMixin(BaseModel):
    """Mixin for entities with audit trail."""
    changelog: list[dict[str, Any]] = Field(default_factory=list)

    def add_change(self, description: str, actor: str = "system") -> None:
        """Record a change in the audit trail."""
        self.changelog.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "description": description,
        })
```

### C.3 — `schemas/company.py` — CanonicalCompanyState

Schema completo — é o output do Sistema 1 (extraction), consumido por tudo o que vem a seguir.

```python
"""Canonical Company State — output of extraction system."""

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, ImmutableSchema
from portfolio_thesis_engine.schemas.common import (
    ConfidenceTag,
    Currency,
    FiscalPeriod,
    Money,
    Percentage,
    Profile,
    Source,
)


# ============================================================
# Identity
# ============================================================

class CompanyIdentity(BaseSchema):
    """Basic company identification."""
    ticker: str = Field(min_length=1, max_length=20)
    isin: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{9}\d$")
    name: str
    legal_name: str | None = None
    reporting_currency: Currency
    profile: Profile
    sector_gics: str | None = None
    industry_gics: str | None = None
    fiscal_year_end_month: int = Field(ge=1, le=12)
    country_domicile: str  # ISO 3166-1 alpha-2
    exchange: str
    shares_outstanding: Decimal | None = None
    market_contexts: list[str] = Field(default_factory=list)  # Cluster references


# ============================================================
# Reclassified Statements
# ============================================================

class IncomeStatementLine(BaseSchema):
    """Single line in reclassified IS."""
    label: str
    value: Money
    is_adjusted: bool = False
    adjustment_note: str | None = None
    source: Source | None = None


class BalanceSheetLine(BaseSchema):
    """Single line in reclassified BS (Invested Capital view for P1)."""
    label: str
    value: Money
    category: str  # e.g., "operating_assets", "financial_claims", "equity"
    is_adjusted: bool = False
    source: Source | None = None


class CashFlowLine(BaseSchema):
    """Single line in CF (economic view)."""
    label: str
    value: Money
    category: str  # e.g., "CFO", "CFI", "CFF"
    is_adjusted: bool = False


class ReclassifiedStatements(BaseSchema):
    """Reclassified financial statements for a fiscal period."""
    period: FiscalPeriod
    
    # Income statement (EBITA → NOPAT view for P1; NII + Provisions for P2)
    income_statement: list[IncomeStatementLine]
    
    # Balance sheet (Invested Capital for P1; Capital stack for P2)
    balance_sheet: list[BalanceSheetLine]
    
    # Cash flow (economic view)
    cash_flow: list[CashFlowLine]
    
    # Checksum validations
    bs_checksum_pass: bool
    is_checksum_pass: bool
    cf_checksum_pass: bool
    checksum_notes: list[str] = Field(default_factory=list)


# ============================================================
# Adjustments Applied (Modules A-F)
# ============================================================

class ModuleAdjustment(BaseSchema):
    """Single adjustment from a module (A-F or Patches)."""
    module: str  # "A.2.3", "C.1", "F.4", etc
    description: str
    amount: Money
    affected_periods: list[FiscalPeriod]
    rationale: str
    source: Source | None = None


class AdjustmentsApplied(BaseSchema):
    """All adjustments applied during extraction."""
    module_a_taxes: list[ModuleAdjustment] = Field(default_factory=list)
    module_b_provisions: list[ModuleAdjustment] = Field(default_factory=list)
    module_c_leases: list[ModuleAdjustment] = Field(default_factory=list)
    module_d_pensions: list[ModuleAdjustment] = Field(default_factory=list)
    module_e_sbc: list[ModuleAdjustment] = Field(default_factory=list)
    module_f_capitalize: list[ModuleAdjustment] = Field(default_factory=list)
    patches: list[ModuleAdjustment] = Field(default_factory=list)  # Patches 1-7
    
    decision_log: list[str] = Field(default_factory=list)
    estimates_log: list[str] = Field(default_factory=list)


# ============================================================
# Analysis Derived
# ============================================================

class InvestedCapital(BaseSchema):
    """IC summary (P1, P4)."""
    period: FiscalPeriod
    operating_assets: Money
    operating_liabilities: Money
    invested_capital: Money
    financial_assets: Money
    financial_liabilities: Money
    equity_claims: Money
    nci_claims: Money = Decimal("0")
    cross_check_residual: Money  # Should be ~0


class NOPATBridge(BaseSchema):
    """EBITA → NOPAT → NI bridge."""
    period: FiscalPeriod
    ebita: Money
    operating_taxes: Money
    nopat: Money
    financial_income: Money
    financial_expense: Money
    non_operating_items: Money
    reported_net_income: Money


class KeyRatios(BaseSchema):
    """Ratios derived from reclassified statements."""
    period: FiscalPeriod
    roic: Percentage | None = None                    # NOPAT / IC
    roic_adj_leases: Percentage | None = None
    roe: Percentage | None = None
    ros: Percentage | None = None                     # NOPAT / Revenue
    operating_margin: Percentage | None = None
    ebitda_margin: Percentage | None = None
    net_debt_ebitda: Decimal | None = None
    capex_revenue: Percentage | None = None
    dso: Decimal | None = None
    dpo: Decimal | None = None
    dio: Decimal | None = None
    
    # Sector-specific ratios (extensible)
    sector_specific: dict[str, Decimal] = Field(default_factory=dict)


class CapitalAllocationHistory(BaseSchema):
    """Capital allocation tracking over multiple years."""
    periods: list[FiscalPeriod]
    cfo_total: Money
    capex_total: Money
    acquisitions_total: Money
    dividends_total: Money
    buybacks_total: Money
    debt_change: Money
    equity_issuance: Money
    
    allocation_mix: dict[str, Percentage] = Field(default_factory=dict)


class AnalysisDerived(BaseSchema):
    """All derived analysis artifacts."""
    invested_capital_by_period: list[InvestedCapital]
    nopat_bridge_by_period: list[NOPATBridge]
    ratios_by_period: list[KeyRatios]
    capital_allocation: CapitalAllocationHistory | None = None
    
    # Optional deep-dive analyses
    dupont_decomposition: dict | None = None
    cf_quality_analysis: dict | None = None
    unit_economics: dict | None = None


# ============================================================
# Quarterly Data
# ============================================================

class QuarterlyData(BaseSchema):
    """Quarterly IS + BS snapshot."""
    latest_quarter: FiscalPeriod
    
    # IS trimestral (3 FYs worth)
    quarterly_is_lines: list[dict]  # Flexible; quarter × line matrix
    
    # Seasonality classification
    seasonality: str  # "FLAT" | "MODERATE" | "STRONG" | "VARIABLE"
    seasonality_method_used: str  # "A_guidance" | "B_historical" | "C_consensus"
    
    # BS snapshot
    bs_snapshot_date: str  # ISO date
    bs_snapshot: dict[str, Money]
    
    # Changes since FY-end
    material_changes_since_fye: list[str] = Field(default_factory=list)


# ============================================================
# Validation
# ============================================================

class ValidationResult(BaseSchema):
    """Single validation check result."""
    check_id: str        # e.g., "V.1", "V.2", "A-check-1"
    name: str
    status: str          # "PASS" | "WARN" | "FAIL" | "SKIP"
    detail: str
    blocking: bool = False


class ValidationResults(BaseSchema):
    """All validation results from extraction."""
    universal_checksums: list[ValidationResult]    # V.1
    profile_specific_checksums: list[ValidationResult]  # V.2
    confidence_rating: str  # "HIGH" | "MEDIUM" | "LOW"
    blocking_issues: list[str] = Field(default_factory=list)


# ============================================================
# Vintage Tags & Cascade Log (FP-06)
# ============================================================

class VintageTag(BaseSchema):
    """Vintage tag documenting temporal provenance."""
    value_reference: str  # Which value this tag applies to
    confidence: ConfidenceTag
    original_date: str    # When originally reported
    latest_restatement: str | None = None
    notes: str | None = None


class CascadeEntry(BaseSchema):
    """Documents a restatement cascade."""
    original_period: FiscalPeriod
    restated_in: FiscalPeriod
    affected_metrics: list[str]
    reason: str
    impact_summary: str


class VintageAndCascade(BaseSchema):
    """Vintage tags and cascade log."""
    vintage_tags: list[VintageTag] = Field(default_factory=list)
    cascade_log: list[CascadeEntry] = Field(default_factory=list)


# ============================================================
# Methodology Metadata
# ============================================================

class MethodologyMetadata(BaseSchema):
    """Documents what methodology was used."""
    extraction_system_version: str  # e.g., "1.4"
    profile_applied: Profile
    protocols_activated: list[str]  # e.g., ["Retail_SSS", "Lease_Heavy", "M&A_Serial"]
    sub_modules_active: dict[str, bool] = Field(default_factory=dict)
    tiers: dict[str, int] = Field(default_factory=dict)  # e.g., {"revenue": 1, "cost": 2}
    
    # LLM calls made during extraction
    llm_calls_summary: dict[str, int] = Field(default_factory=dict)  # model → count
    total_api_cost_usd: Decimal | None = None


# ============================================================
# CANONICAL COMPANY STATE (top-level)
# ============================================================

class CanonicalCompanyState(ImmutableSchema):
    """
    Immutable output of the extraction system for a company.
    
    Represents a complete, reclassified, validated view of the company's
    financial state as of a specific extraction date.
    
    Consumed by: valuation module (as input), portfolio module (for ratios)
    """
    
    # Metadata
    extraction_id: str                              # UUID or timestamp-based ID
    extraction_date: datetime
    as_of_date: str                                 # ISO date; the "as of" for the data
    
    # Core content
    identity: CompanyIdentity
    reclassified_statements: list[ReclassifiedStatements]  # Multiple years
    adjustments: AdjustmentsApplied
    analysis: AnalysisDerived
    quarterly: QuarterlyData | None = None
    
    # Validation & provenance
    validation: ValidationResults
    vintage: VintageAndCascade
    methodology: MethodologyMetadata
    
    # Raw source references (filesystem paths)
    source_documents: list[str] = Field(default_factory=list)
```

### C.4 — `schemas/valuation.py` — ValuationSnapshot & Scenario

```python
"""Valuation Snapshot — output of forecast & valuation system."""

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import ImmutableSchema, VersionedMixin
from portfolio_thesis_engine.schemas.common import (
    ConvictionLevel,
    Currency,
    FiscalPeriod,
    GuardrailStatus,
    Money,
    Percentage,
    Profile,
)


# ============================================================
# Scenario
# ============================================================

class ScenarioDrivers(BaseSchema):
    """Key drivers defining a scenario. Schema varies by profile."""
    # Common fields
    revenue_cagr: Percentage | None = None
    terminal_growth: Percentage | None = None
    terminal_margin: Percentage | None = None
    terminal_roic: Percentage | None = None
    terminal_wacc: Percentage | None = None
    
    # P2-specific
    terminal_roe: Percentage | None = None
    terminal_payout: Percentage | None = None
    terminal_nim: Percentage | None = None
    terminal_cor_bps: int | None = None
    terminal_cost_income: Percentage | None = None
    terminal_cet1: Percentage | None = None
    
    # Extensible for other profiles
    custom_drivers: dict[str, Decimal] = Field(default_factory=dict)


class SurvivalCondition(BaseSchema):
    """Condition that keeps a scenario alive."""
    metric: str                    # e.g., "NIM exit H1/26"
    on_track: str                  # e.g., ">= 3.20%"
    warning: str                   # e.g., "< 3.00%"
    source: str | None = None      # e.g., "interim results"
    last_observed: str | None = None  # Value or null


class Scenario(BaseSchema):
    """A scenario definition (Bear, Base, Bull, or custom)."""
    label: str                                      # "bear", "base", "bull"
    description: str
    probability: Percentage = Field(ge=0, le=100)
    horizon_years: int = Field(default=3, ge=1, le=10)
    
    drivers: ScenarioDrivers
    
    # Targets computed from drivers
    targets: dict[str, Money] = Field(default_factory=dict)  # method → target
    
    # IRR decomposition
    irr_3y: Percentage | None = None
    irr_5y: Percentage | None = None
    irr_decomposition: dict[str, Percentage] | None = None
    
    # Upside/downside
    upside_pct: Percentage | None = None
    
    # Tracking
    survival_conditions: list[SurvivalCondition] = Field(default_factory=list)
    kill_signals: list[str] = Field(default_factory=list)


# ============================================================
# Reverse analysis (expectations matrix)
# ============================================================

class MarketImpliedView(BaseSchema):
    """What the market is pricing."""
    roe_terminal: Percentage | None = None
    prob_bear: Percentage | None = None
    prob_base: Percentage | None = None
    prob_bull: Percentage | None = None
    growth_implied_in_price: Percentage | None = None
    custom_fields: dict[str, Decimal] = Field(default_factory=dict)


class GapDecomposition(BaseSchema):
    """Decomposition of gap between model and market."""
    driver: str                        # e.g., "roe_terminal"
    delta: str                         # e.g., "+3.0pp"
    contribution_value: Decimal        # e.g., 48 (pence)
    pct_of_gap: Percentage
    prove_right: str | None = None
    prove_wrong: str | None = None


class ReverseAnalysis(BaseSchema):
    """Reverse DDM / DCF analysis."""
    market_implied: MarketImpliedView
    gap_total_value: Decimal
    gap_unit: str                      # "pence", "cents", etc
    gap_decomposition: list[GapDecomposition]


# ============================================================
# Cross-checks
# ============================================================

class MonteCarloResult(BaseSchema):
    """Monte Carlo simulation output."""
    iterations: int
    p10: Money
    p25: Money
    p50: Money
    p75: Money
    p90: Money
    prob_above_current: Percentage


class CorrelatedStress(BaseSchema):
    """Correlated stress test result."""
    value_per_share: Money
    assumptions: dict[str, str] = Field(default_factory=dict)


class ConsensusComparison(BaseSchema):
    """Comparison with sell-side consensus."""
    tp_avg: Money | None = None
    tp_range_low: Money | None = None
    tp_range_high: Money | None = None
    analyst_count: int | None = None
    quality_note: str | None = None


class CrossChecks(BaseSchema):
    """All cross-check analyses."""
    monte_carlo: MonteCarloResult | None = None
    correlated_stress: CorrelatedStress | None = None
    consensus: ConsensusComparison | None = None


# ============================================================
# EPS Bridge
# ============================================================

class EPSBridgeComponent(BaseSchema):
    """Single component in EPS bridge."""
    item: str
    impact: Decimal


class EPSBridgeYear(BaseSchema):
    """EPS bridge for a specific year."""
    period: FiscalPeriod
    model: Decimal
    consensus: Decimal | None = None
    gap: Decimal | None = None
    components: list[EPSBridgeComponent] = Field(default_factory=list)


class EPSBridge(BaseSchema):
    """Multi-year EPS bridge."""
    years: list[EPSBridgeYear]


# ============================================================
# Catalysts
# ============================================================

class Catalyst(BaseSchema):
    """Single catalyst event."""
    date: str                          # ISO date
    event: str
    scenarios_affected: list[str]      # ["base", "bull"] or ["all"]
    impact: str
    probability: Percentage | None = None
    notes: str | None = None


# ============================================================
# Weighted outputs
# ============================================================

class WeightedOutputs(BaseSchema):
    """Probability-weighted outputs across scenarios."""
    expected_value: Money                          # E[V]
    expected_value_method_used: str                # "RI", "DDM", "DCF"
    fair_value_range_low: Money
    fair_value_range_high: Money
    upside_pct: Percentage                         # vs current price
    asymmetry_ratio: Decimal                       # upside / downside weighted
    weighted_irr_3y: Percentage | None = None
    weighted_irr_5y: Percentage | None = None


# ============================================================
# Guardrails Status
# ============================================================

class GuardrailCategory(BaseSchema):
    """Guardrails results for one category (A-F)."""
    category: str                      # "D_valuation", "E_ratios", "F_cross_temporal"
    total: int
    passed: int
    warned: int
    failed: int
    skipped: int
    notes: list[str] = Field(default_factory=list)


class GuardrailsStatus(BaseSchema):
    """All guardrails status."""
    categories: list[GuardrailCategory]
    overall: GuardrailStatus           # Worst-case across categories


# ============================================================
# Market context at valuation time
# ============================================================

class MarketSnapshot(BaseSchema):
    """Market data at the time of valuation."""
    price: Money
    price_date: str                    # ISO date
    shares_outstanding: Decimal | None = None
    market_cap: Money | None = None
    cost_of_equity: Percentage | None = None
    wacc: Percentage | None = None
    currency: Currency


# ============================================================
# Factor Exposures (archived at snapshot time)
# ============================================================

class FactorExposure(BaseSchema):
    """Single factor exposure."""
    factor: str                        # e.g., "ftse_250", "break_even_inflation"
    beta: Decimal
    r_squared: Decimal
    window_months: int                 # e.g., 24, 36
    computed_at: str                   # ISO date


# ============================================================
# Conviction
# ============================================================

class Conviction(BaseSchema):
    """Conviction levels across dimensions."""
    forecast: ConvictionLevel
    valuation: ConvictionLevel
    asymmetry: ConvictionLevel
    timing_risk: ConvictionLevel
    liquidity_risk: ConvictionLevel
    governance_risk: ConvictionLevel


# ============================================================
# VALUATION SNAPSHOT (top-level)
# ============================================================

class ValuationSnapshot(ImmutableSchema, VersionedMixin):
    """
    Immutable output of the valuation system.
    
    Represents a complete valuation analysis of a company at a point in time,
    including scenarios, targets, gap analysis, catalysts, and validation.
    
    Versioned: each new valuation creates a new snapshot. Portfolio reads
    current snapshot but never writes to snapshots.
    """
    
    # Identity
    snapshot_id: str                               # UUID
    ticker: str
    company_name: str
    profile: Profile
    valuation_date: datetime
    
    # Reference to extraction used
    based_on_extraction_id: str                    # Links to CanonicalCompanyState
    based_on_extraction_date: datetime
    
    # Market snapshot at valuation time
    market: MarketSnapshot
    
    # Scenarios
    scenarios: list[Scenario]                      # Typically [bear, base, bull]
    
    # Weighted outputs
    weighted: WeightedOutputs
    
    # Reverse analysis
    reverse: ReverseAnalysis | None = None
    
    # Cross-checks
    cross_checks: CrossChecks | None = None
    
    # EPS bridge
    eps_bridge: EPSBridge | None = None
    
    # Catalysts
    catalysts: list[Catalyst] = Field(default_factory=list)
    
    # Factor exposures archived at this moment
    factor_exposures: list[FactorExposure] = Field(default_factory=list)
    scenario_response: dict | None = None          # Hook for Prospective Layer (MVP: None)
    
    # Conviction
    conviction: Conviction
    
    # Guardrails
    guardrails: GuardrailsStatus
    
    # Methodology
    forecast_system_version: str                   # e.g., "2.0"
    source_documents: list[str] = Field(default_factory=list)
    
    # Total API cost for this valuation
    total_api_cost_usd: Decimal | None = None
```

### C.5 — `schemas/position.py` — Position

```python
"""Position — portfolio holding of a company."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, AuditableMixin
from portfolio_thesis_engine.schemas.common import Currency, Money, Percentage


class PositionStatus(str, Enum):
    ACTIVE = "active"
    EXITED = "exited"
    WATCHLIST = "watchlist"
    RESEARCH = "research"


class PositionTransaction(BaseSchema):
    """Single transaction in a position's history."""
    date: str                          # ISO date
    type: str                          # "open", "add", "reduce", "close"
    quantity: Decimal
    price: Money
    currency: Currency
    rationale: str
    fees: Money | None = None


class PositionCurrentState(BaseSchema):
    """Auto-computed current state of a position."""
    quantity: Decimal
    avg_cost: Money
    last_price: Money
    last_price_date: str
    market_value: Money
    unrealized_pnl: Money
    unrealized_pnl_pct: Percentage
    weight_pct: Percentage             # Of portfolio total


class PositionLinkage(BaseSchema):
    """Links to related entities."""
    valuation_snapshot_current: str | None = None  # Snapshot ID
    ficha_path: str | None = None
    company_state_id: str | None = None


class Position(BaseSchema, AuditableMixin):
    """Portfolio position in a company."""
    ticker: str
    company_name: str
    status: PositionStatus
    currency: Currency
    
    # History
    transactions: list[PositionTransaction] = Field(default_factory=list)
    
    # Current computed state
    current: PositionCurrentState | None = None
    
    # Exit information (if status == EXITED)
    exit_date: str | None = None
    exit_price: Money | None = None
    realized_pnl: Money | None = None
    realized_pnl_pct: Percentage | None = None
    
    # Links
    linkage: PositionLinkage = Field(default_factory=PositionLinkage)
    
    # Custom tags
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
```

### C.6 — `schemas/peer.py` — Peer

```python
"""Peer — comparable company for benchmarking."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.common import Currency, Money, Percentage, Profile


class PeerExtractionLevel(str, Enum):
    """How much extraction was performed on this peer."""
    LEVEL_A = "A"   # Full extraction (promoted to watchlist)
    LEVEL_B = "B"   # Adjusted metrics (manual supplementation)
    LEVEL_C = "C"   # API data only (default)


class PeerStatus(str, Enum):
    ACTIVE = "active"
    PROMOTED = "promoted"        # Became a watchlist/position
    DROPPED = "dropped"


class Peer(BaseSchema):
    """A peer comparable to a target company."""
    
    # Identity
    ticker: str
    name: str
    profile: Profile
    currency: Currency
    exchange: str
    
    # Reference to parent
    peer_of_ticker: str            # The target company this is a peer of
    
    # Extraction metadata
    extraction_level: PeerExtractionLevel
    last_update: datetime
    status: PeerStatus = PeerStatus.ACTIVE
    
    # Level C — always present (API data)
    market_data: dict[str, Decimal] = Field(default_factory=dict)
    reported_metrics: dict[str, Decimal] = Field(default_factory=dict)
    
    # Level B — present if extraction_level >= B
    adjusted_metrics: dict[str, Decimal] | None = None
    
    # Archetype-specific fields (flexible)
    # E.g., for P2 banks: cet1_ratio, nim, cor_bps
    archetype_specific: dict[str, Decimal] = Field(default_factory=dict)
    
    # If promoted to watchlist
    promotion_date: datetime | None = None
    promoted_to: str | None = None  # Path to new company entity
```

### C.7 — `schemas/market_context.py` — MarketContext (extensível)

```python
"""Market context — cluster-level data shared across companies."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, AuditableMixin


class MarketParticipant(BaseSchema):
    """A participant in a market cluster."""
    ticker: str
    name: str
    market_share_pct: Decimal | None = None
    position: str | None = None        # "leader", "challenger", "niche", etc


class MarketDimension(BaseSchema):
    """A dimension of the market (geography, segment, etc)."""
    name: str
    description: str | None = None
    total_market_value: Decimal | None = None
    unit: str | None = None             # "GBP_bn", "EUR_m", etc
    year: int | None = None
    cagr: Decimal | None = None
    source: str | None = None
    participants: list[MarketParticipant] = Field(default_factory=list)


class MarketCatalyst(BaseSchema):
    """A catalyst/trigger affecting the market."""
    date_approx: str                   # Could be precise or range "H2 2026"
    event: str
    impact_direction: str               # "positive", "negative", "mixed"
    affected_companies: list[str] = Field(default_factory=list)
    probability: Decimal | None = None
    description: str | None = None


class MarketContext(BaseSchema, AuditableMixin):
    """
    Cluster-level market context.
    
    MVP is minimal: just identity + reference + extension point.
    Rich content added incrementally over time.
    """
    
    # Identity (minimum required)
    cluster_id: str                    # e.g., "uk_specialist_banks"
    name: str
    description: str
    
    # References
    companies: list[str] = Field(default_factory=list)  # Tickers in this cluster
    
    # Optional rich content (added incrementally)
    dimensions: list[MarketDimension] = Field(default_factory=list)
    catalysts: list[MarketCatalyst] = Field(default_factory=list)
    regulatory_notes: list[str] = Field(default_factory=list)
    dynamics_notes: list[str] = Field(default_factory=list)
    
    # Flexible extension for future fields without schema migration
    extensions: dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    last_updated: datetime
    sources: list[str] = Field(default_factory=list)
```

### C.8 — `schemas/ficha.py` — Ficha (aggregate view)

```python
"""Ficha — aggregate view of a company across all modules."""

from datetime import datetime

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, VersionedMixin
from portfolio_thesis_engine.schemas.company import CompanyIdentity
from portfolio_thesis_engine.schemas.position import Position
from portfolio_thesis_engine.schemas.valuation import Conviction


class ThesisStatement(BaseSchema):
    """Investment thesis in one paragraph."""
    version: int = Field(default=1)
    text: str
    written_at: datetime
    last_reviewed: datetime | None = None


class Monitorable(BaseSchema):
    """A metric being tracked over time."""
    metric: str
    on_track_condition: str
    warning_condition: str
    last_observed: str | None = None
    last_observed_date: str | None = None
    status: str                         # "on_track", "warning", "missed", "unknown"
    source: str | None = None


class Ficha(BaseSchema, VersionedMixin):
    """
    Aggregate view of a company.
    
    This is the composed output that the portfolio system displays.
    Composed from: CanonicalCompanyState + ValuationSnapshot + Position + Peer data.
    
    The ficha is not stored as a single file; rather it's composed on-demand
    from its constituent entities. This schema defines the canonical shape.
    """
    
    # Identity
    ticker: str
    identity: CompanyIdentity
    
    # Thesis
    thesis: ThesisStatement | None = None
    
    # References (IDs/paths to underlying entities)
    current_extraction_id: str | None = None
    current_valuation_snapshot_id: str | None = None
    position: Position | None = None
    
    # Aggregated display data
    conviction: Conviction | None = None
    monitorables: list[Monitorable] = Field(default_factory=list)
    
    # Tags
    tags: list[str] = Field(default_factory=list)
    market_contexts: list[str] = Field(default_factory=list)
    
    # Staleness indicator (computed)
    snapshot_age_days: int | None = None
    is_stale: bool = False             # True if next earnings + 30d exceeded
    next_earnings_expected: str | None = None
```

---

## PARTE D — Storage Layer

### D.1 — Princípios

1. **Módulos nunca acedem storage directamente.** Sempre via Repository.
2. **Uma Repository por tipo de entidade**, não por layer técnica.
3. **Operações atómicas onde aplicável** — `UnitOfWork` para transacções.
4. **Testabilidade**: cada Repository tem equivalente in-memory para tests.
5. **YAMLs são source of truth para human-edited data**. DuckDB/SQLite/Chroma são caches/indexes.

### D.2 — `storage/base.py` — Interfaces base

```python
"""Base classes and protocols for storage."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Repository(ABC, Generic[T]):
    """Base Repository for an entity type."""
    
    @abstractmethod
    def get(self, key: str) -> T | None:
        """Retrieve entity by primary key."""
    
    @abstractmethod
    def save(self, entity: T) -> None:
        """Persist entity."""
    
    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove entity."""
    
    @abstractmethod
    def list_keys(self) -> list[str]:
        """List all primary keys."""
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if entity exists."""


class VersionedRepository(Repository[T]):
    """Repository for versioned/immutable entities (snapshots)."""
    
    @abstractmethod
    def get_version(self, key: str, version: str) -> T | None:
        """Get specific version."""
    
    @abstractmethod
    def list_versions(self, key: str) -> list[str]:
        """List versions of entity."""
    
    @abstractmethod
    def get_current(self, key: str) -> T | None:
        """Get current (latest) version."""
    
    @abstractmethod
    def set_current(self, key: str, version: str) -> None:
        """Mark a version as current."""


class StorageError(Exception):
    """Base exception for storage operations."""


class EntityNotFoundError(StorageError):
    """Entity not found."""


class EntityAlreadyExistsError(StorageError):
    """Entity already exists (on create)."""
```

### D.3 — Concrete Repositories (conceptual structure)

Cada Repository concreta implementa interfaces acima. Claude Code deve implementar:

**`CompanyRepository`** (YAML-based, uses `yaml_repo.py`)
- Key: ticker (e.g., "MTRO-L", where `.` in ticker is replaced by `-`)
- Path: `data/yamls/companies/{key}/ficha.yaml`
- Ops: CRUD on Ficha entity

**`ValuationRepository`** (versioned, YAML-based)
- Key: ticker
- Versions: `data/yamls/companies/{key}/valuation/{YYYY-MM-DD_vN}.yaml`
- Current symlink: `data/yamls/companies/{key}/valuation/current`
- Ops: Get, save (creates new version), list versions, get current

**`CompanyStateRepository`** (versioned, YAML-based)
- Similar pattern to ValuationRepository
- Path: `data/yamls/companies/{key}/extraction/{extraction_id}.yaml`

**`PositionRepository`** (YAML-based)
- Path: `data/yamls/portfolio/positions/{ticker}.yaml`

**`PeerRepository`** (YAML-based)
- Path: `data/yamls/companies/{ticker}/peers/{peer_ticker}.yaml`

**`MarketContextRepository`** (YAML-based)
- Path: `data/yamls/market_contexts/{cluster_id}/context.yaml`

**`TimeSeriesRepository`** (DuckDB-based, uses `duckdb_repo.py`)
- Schemas: `prices_eod`, `factor_series`, `peer_metrics_history`
- Ops: query (SQL-based), insert, upsert

**`DocumentRepository`** (Filesystem-based)
- Path: `data/documents/{ticker}/{type}/{filename}`
- Ops: store PDF, retrieve, list

**`RAGRepository`** (ChromaDB-based)
- Collections by entity type
- Ops: index document, semantic search, filter by metadata

**`MetadataRepository`** (SQLite-based)
- Tables: `companies`, `archetypes`, `clusters`, `company_clusters`, `company_peers`
- Ops: lookup, relational queries

### D.4 — Example implementation: `yaml_repo.py`

```python
"""YAML-based repositories — source of truth for human-edited data."""

from pathlib import Path
from typing import Type

import yaml
from pydantic import BaseModel

from portfolio_thesis_engine.storage.base import (
    Repository,
    EntityNotFoundError,
    StorageError,
)
from portfolio_thesis_engine.shared.config import settings


class YAMLRepository(Repository):
    """
    Generic YAML file repository.
    
    Each entity is a single YAML file at `{base_path}/{key}.yaml`.
    """
    
    def __init__(
        self,
        entity_class: Type[BaseModel],
        base_path: Path,
        filename_template: str = "{key}.yaml",
    ):
        self.entity_class = entity_class
        self.base_path = base_path
        self.filename_template = filename_template
    
    def _path_for(self, key: str) -> Path:
        return self.base_path / self.filename_template.format(key=key)
    
    def get(self, key: str) -> BaseModel | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return self.entity_class.model_validate(data)
        except Exception as e:
            raise StorageError(f"Failed to load {path}: {e}") from e
    
    def save(self, entity: BaseModel) -> None:
        # Derive key — subclasses override if needed
        key = self._get_key(entity)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = entity.model_dump(mode="json", exclude_none=True)
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            raise StorageError(f"Failed to save {path}: {e}") from e
    
    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()
    
    def list_keys(self) -> list[str]:
        if not self.base_path.exists():
            return []
        # Default: list .yaml files, strip extension
        return sorted(p.stem for p in self.base_path.glob("*.yaml"))
    
    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()
    
    def _get_key(self, entity: BaseModel) -> str:
        # Default: look for 'ticker' or 'id' attribute
        if hasattr(entity, "ticker"):
            return entity.ticker.replace(".", "-")
        if hasattr(entity, "id"):
            return entity.id
        raise ValueError("Cannot derive key — override _get_key()")


# Concrete repositories (examples)

class CompanyRepository(YAMLRepository):
    """Repository for Ficha entities."""
    
    def __init__(self):
        from portfolio_thesis_engine.schemas.ficha import Ficha
        super().__init__(
            entity_class=Ficha,
            base_path=settings.data_dir / "yamls" / "companies",
            filename_template="{key}/ficha.yaml",
        )


class PositionRepository(YAMLRepository):
    """Repository for Position entities."""
    
    def __init__(self):
        from portfolio_thesis_engine.schemas.position import Position
        super().__init__(
            entity_class=Position,
            base_path=settings.data_dir / "yamls" / "portfolio" / "positions",
        )
```

### D.5 — `storage/duckdb_repo.py` — DuckDB repository

```python
"""DuckDB-based repository for analytical time series."""

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from portfolio_thesis_engine.shared.config import settings


class DuckDBRepository:
    """
    Single DuckDB file for all analytical time series.
    
    Schemas:
    - prices_eod: EOD price data
    - factor_series: Factor time series
    - peer_metrics_history: Peer metrics over time
    - computed_betas: Cached rolling betas
    """
    
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (settings.data_dir / "timeseries.duckdb")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _init_schema(self) -> None:
        """Create tables if not exist."""
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prices_eod (
                    ticker VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    open DECIMAL(18,6),
                    high DECIMAL(18,6),
                    low DECIMAL(18,6),
                    close DECIMAL(18,6) NOT NULL,
                    volume BIGINT,
                    currency VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    PRIMARY KEY (ticker, date)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS factor_series (
                    factor_id VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    value DECIMAL(18,6) NOT NULL,
                    source VARCHAR,
                    PRIMARY KEY (factor_id, date)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS peer_metrics_history (
                    ticker VARCHAR NOT NULL,
                    period_label VARCHAR NOT NULL,
                    metric VARCHAR NOT NULL,
                    value DECIMAL(20,6),
                    unit VARCHAR,
                    is_adjusted BOOLEAN DEFAULT FALSE,
                    extracted_at TIMESTAMP,
                    PRIMARY KEY (ticker, period_label, metric)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS computed_betas (
                    ticker VARCHAR NOT NULL,
                    factor_id VARCHAR NOT NULL,
                    window_months INTEGER NOT NULL,
                    as_of_date DATE NOT NULL,
                    beta DECIMAL(10,6) NOT NULL,
                    r_squared DECIMAL(10,6),
                    PRIMARY KEY (ticker, factor_id, window_months, as_of_date)
                )
            """)
    
    @contextmanager
    def connect(self):
        """Context manager for connection."""
        conn = duckdb.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()
    
    def insert_prices(self, rows: list[dict]) -> None:
        """Bulk insert EOD prices."""
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO prices_eod (ticker, date, open, high, low, close, volume, currency, source)
                VALUES ($ticker, $date, $open, $high, $low, $close, $volume, $currency, $source)
                ON CONFLICT (ticker, date) DO UPDATE SET close=EXCLUDED.close
                """,
                rows,
            )
    
    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        """Execute SQL query, return results as list of dicts."""
        with self.connect() as conn:
            result = conn.execute(sql, params or {}).fetchall()
            columns = [desc[0] for desc in conn.description]
            return [dict(zip(columns, row)) for row in result]
```

### D.6 — Guidance para Claude Code

Ao implementar o resto dos Repositories:

1. **Seguir o padrão** — cada Repository herda de `Repository` ou `VersionedRepository`
2. **Erros tipados** — levantar `EntityNotFoundError`, `EntityAlreadyExistsError`, `StorageError`
3. **Testabilidade** — criar versão in-memory (`InMemoryCompanyRepository`) para unit tests
4. **Idempotência** — `save()` deve ser safe para rerun
5. **Atomicidade** — writes para YAML devem usar temp file + rename (não corromper em caso de crash)

---

## PARTE E — LLM Orchestrator

### E.1 — Arquitectura

```
llm/
├── base.py           # LLMProvider abstracto
├── anthropic_provider.py
├── openai_provider.py    # Só embeddings
├── router.py         # Routing por task type
├── retry.py          # Exponential backoff
├── cost_tracker.py
└── structured.py     # Tool use helpers
```

### E.2 — `llm/base.py` — Interface abstracta

```python
"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class LLMRequest:
    """A single LLM request."""
    prompt: str
    system: str | None = None
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    tools: list[dict] | None = None
    response_schema: dict | None = None        # For structured outputs
    metadata: dict = None                       # For logging/tracking


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    content: str
    structured_output: dict | None = None       # If schema used
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    model_used: str = ""
    latency_ms: int = 0
    raw_response: Any = None


class LLMProvider(ABC):
    """Abstract provider for LLM calls."""
    
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Make a completion call."""
    
    @abstractmethod
    def complete_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous version."""


class EmbeddingsProvider(ABC):
    """Abstract provider for embeddings."""
    
    @abstractmethod
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embed a list of texts."""
```

### E.3 — `llm/anthropic_provider.py`

```python
"""Anthropic Claude provider."""

import time
from decimal import Decimal

from anthropic import Anthropic, AsyncAnthropic

from portfolio_thesis_engine.llm.base import LLMProvider, LLMRequest, LLMResponse
from portfolio_thesis_engine.shared.config import settings


# Pricing as of Apr 2026 (USD per 1M tokens)
ANTHROPIC_PRICING = {
    "claude-opus-4-7": {"input": Decimal("15.00"), "output": Decimal("75.00")},
    "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-haiku-4-5-20251001": {"input": Decimal("0.80"), "output": Decimal("4.00")},
}


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key
        self.sync_client = Anthropic(api_key=self.api_key)
        self.async_client = AsyncAnthropic(api_key=self.api_key)
    
    def _compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        pricing = ANTHROPIC_PRICING.get(model)
        if not pricing:
            return Decimal("0")
        return (
            pricing["input"] * Decimal(input_tokens) / Decimal("1_000_000") +
            pricing["output"] * Decimal(output_tokens) / Decimal("1_000_000")
        )
    
    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or settings.llm_model_analysis
        
        start = time.time()
        
        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = request.tools
        
        response = await self.async_client.messages.create(**kwargs)
        
        latency = int((time.time() - start) * 1000)
        
        content = ""
        structured = None
        if response.content:
            for block in response.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    structured = block.input
        
        cost = self._compute_cost(
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        
        return LLMResponse(
            content=content,
            structured_output=structured,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=cost,
            model_used=model,
            latency_ms=latency,
            raw_response=response,
        )
    
    def complete_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous version (uses asyncio under the hood)."""
        import asyncio
        return asyncio.run(self.complete(request))
```

### E.4 — `llm/openai_provider.py` (embeddings only)

```python
"""OpenAI provider — RESTRICTED to embeddings only."""

from openai import AsyncOpenAI, OpenAI

from portfolio_thesis_engine.llm.base import EmbeddingsProvider
from portfolio_thesis_engine.shared.config import settings


class OpenAIEmbeddingsProvider(EmbeddingsProvider):
    """OpenAI provider for embeddings. NOT used for completions."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.openai_api_key
        self.sync_client = OpenAI(api_key=self.api_key)
        self.async_client = AsyncOpenAI(api_key=self.api_key)
    
    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        model = model or settings.llm_model_embeddings
        response = await self.async_client.embeddings.create(
            input=texts,
            model=model,
        )
        return [item.embedding for item in response.data]
```

### E.5 — `llm/router.py` — Model routing

```python
"""Route tasks to appropriate models."""

from enum import Enum

from portfolio_thesis_engine.shared.config import settings


class TaskType(str, Enum):
    CLASSIFICATION = "classification"       # Cheap, simple decisions
    EXTRACTION = "extraction"               # Standard parsing work
    ANALYSIS = "analysis"                   # Reasoning, synthesis
    JUDGMENT = "judgment"                   # Critical decisions (devil's advocate)
    NARRATIVE = "narrative"                 # Final ficha narrative


def model_for_task(task: TaskType) -> str:
    """Return the configured model for a task type."""
    mapping = {
        TaskType.CLASSIFICATION: settings.llm_model_classification,
        TaskType.EXTRACTION: settings.llm_model_analysis,
        TaskType.ANALYSIS: settings.llm_model_analysis,
        TaskType.JUDGMENT: settings.llm_model_judgment,
        TaskType.NARRATIVE: settings.llm_model_analysis,
    }
    return mapping[task]
```

### E.6 — `llm/cost_tracker.py`

```python
"""Track LLM costs per operation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock

from portfolio_thesis_engine.shared.config import settings


@dataclass
class CostEntry:
    timestamp: datetime
    operation: str
    ticker: str | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class CostTracker:
    """Thread-safe cost tracking."""
    
    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path or (settings.data_dir / "llm_costs.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._session_entries: list[CostEntry] = []
    
    def record(
        self,
        operation: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        ticker: str | None = None,
    ) -> None:
        entry = CostEntry(
            timestamp=datetime.now(timezone.utc),
            operation=operation,
            ticker=ticker,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        with self._lock:
            self._session_entries.append(entry)
            self._append_jsonl(entry)
    
    def _append_jsonl(self, entry: CostEntry) -> None:
        import json
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": entry.timestamp.isoformat(),
                "operation": entry.operation,
                "ticker": entry.ticker,
                "model": entry.model,
                "input_tokens": entry.input_tokens,
                "output_tokens": entry.output_tokens,
                "cost_usd": str(entry.cost_usd),
            }) + "\n")
    
    def session_total(self) -> Decimal:
        with self._lock:
            return sum((e.cost_usd for e in self._session_entries), Decimal("0"))
    
    def ticker_total(self, ticker: str) -> Decimal:
        """Total cost for a ticker from log file."""
        import json
        total = Decimal("0")
        if not self.log_path.exists():
            return total
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("ticker") == ticker:
                    total += Decimal(entry["cost_usd"])
        return total


# Singleton instance
_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
```

### E.7 — `llm/retry.py` — Retry logic

```python
"""Retry with exponential backoff."""

import asyncio
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


# Exceptions that trigger retry
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    # Add anthropic/openai specific retryable errors here
)


def with_retry(max_attempts: int = 3, wait_min: int = 1, wait_max: int = 30):
    """Decorator factory for retry with exponential backoff."""
    return retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
    )
```

### E.8 — Uso conjunto

```python
# Example use in a module:
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.base import LLMRequest
from portfolio_thesis_engine.llm.router import TaskType, model_for_task
from portfolio_thesis_engine.llm.cost_tracker import get_cost_tracker


async def classify_tax_adjustment(description: str) -> str:
    provider = AnthropicProvider()
    tracker = get_cost_tracker()
    
    request = LLMRequest(
        prompt=f"Classify as operational or non-operational: {description}",
        model=model_for_task(TaskType.CLASSIFICATION),
        max_tokens=200,
    )
    
    response = await provider.complete(request)
    
    tracker.record(
        operation="classify_tax_adjustment",
        model=response.model_used,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )
    
    return response.content
```

---

## PARTE F — Market Data Provider

### F.1 — Interface abstracta

```python
# market_data/base.py
"""Abstract market data provider."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any


class MarketDataProvider(ABC):
    """Abstract provider for market data."""
    
    @abstractmethod
    async def get_quote(self, ticker: str) -> dict:
        """Get latest quote for ticker."""
    
    @abstractmethod
    async def get_price_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """Get EOD price history."""
    
    @abstractmethod
    async def get_fundamentals(self, ticker: str) -> dict:
        """Get fundamentals (IS, BS, CF) — used for peer Level C."""
    
    @abstractmethod
    async def get_key_metrics(self, ticker: str) -> dict:
        """Get key metrics (multiples, ratios)."""
    
    @abstractmethod
    async def search_tickers(self, query: str) -> list[dict]:
        """Search for tickers."""
    
    @abstractmethod
    def validate_ticker(self, ticker: str) -> bool:
        """Check if ticker format is valid for this provider."""


class MarketDataError(Exception):
    """Base exception for market data errors."""


class TickerNotFoundError(MarketDataError):
    pass


class RateLimitError(MarketDataError):
    pass
```

### F.2 — FMP implementation skeleton

```python
# market_data/fmp_provider.py
"""FMP (Financial Modeling Prep) implementation."""

import httpx

from portfolio_thesis_engine.market_data.base import (
    MarketDataProvider,
    MarketDataError,
    TickerNotFoundError,
)
from portfolio_thesis_engine.shared.config import settings


class FMPProvider(MarketDataProvider):
    """Financial Modeling Prep provider."""
    
    BASE_URL = "https://financialmodelingprep.com/api/v3"
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.fmp_api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_quote(self, ticker: str) -> dict:
        url = f"{self.BASE_URL}/quote/{ticker}"
        params = {"apikey": self.api_key}
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data:
            raise TickerNotFoundError(f"Ticker {ticker} not found")
        return data[0]
    
    async def get_price_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        url = f"{self.BASE_URL}/historical-price-full/{ticker}"
        params = {
            "apikey": self.api_key,
            "from": start_date,
            "to": end_date,
        }
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json().get("historical", [])
    
    # Implement other methods similarly...
    
    async def close(self):
        await self.client.aclose()
    
    def validate_ticker(self, ticker: str) -> bool:
        """FMP accepts US and some international tickers."""
        return bool(ticker) and len(ticker) <= 20
```

---

## PARTE G — Guardrails Framework

### G.1 — Base classes

```python
# guardrails/base.py
"""Base classes for guardrails."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from portfolio_thesis_engine.schemas.common import GuardrailStatus


@dataclass
class GuardrailResult:
    """Result of a single guardrail check."""
    check_id: str
    name: str
    status: GuardrailStatus
    message: str
    blocking: bool = False
    data: dict[str, Any] = field(default_factory=dict)


class Guardrail(ABC):
    """Base class for a guardrail check."""
    
    @property
    @abstractmethod
    def check_id(self) -> str:
        """Unique identifier, e.g., 'A.1', 'V.1', 'D.3'."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
    
    @property
    def blocking(self) -> bool:
        """If True, a FAIL stops the pipeline."""
        return False
    
    @abstractmethod
    def check(self, context: dict) -> GuardrailResult:
        """Run the check. `context` has all necessary data."""
```

### G.2 — Runner

```python
# guardrails/runner.py
"""Runs guardrails over context."""

from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.schemas.common import GuardrailStatus


class GuardrailRunner:
    """Executes a set of guardrails."""
    
    def __init__(self, guardrails: list[Guardrail]):
        self.guardrails = guardrails
    
    def run(self, context: dict, stop_on_blocking_fail: bool = True) -> list[GuardrailResult]:
        results = []
        for guardrail in self.guardrails:
            try:
                result = guardrail.check(context)
            except Exception as e:
                result = GuardrailResult(
                    check_id=guardrail.check_id,
                    name=guardrail.name,
                    status=GuardrailStatus.FAIL,
                    message=f"Guardrail errored: {e}",
                    blocking=guardrail.blocking,
                )
            results.append(result)
            if (
                stop_on_blocking_fail
                and result.status == GuardrailStatus.FAIL
                and result.blocking
            ):
                break
        return results
    
    @staticmethod
    def overall_status(results: list[GuardrailResult]) -> GuardrailStatus:
        """Worst-case status across results."""
        priority = {
            GuardrailStatus.FAIL: 5,
            GuardrailStatus.REVIEW: 4,
            GuardrailStatus.WARN: 3,
            GuardrailStatus.NOTA: 2,
            GuardrailStatus.PASS: 1,
            GuardrailStatus.SKIP: 0,
        }
        if not results:
            return GuardrailStatus.PASS
        worst = max(results, key=lambda r: priority[r.status])
        return worst.status
```

### G.3 — Test example

```python
# tests/unit/test_guardrails.py
from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.schemas.common import GuardrailStatus


class TrivialPass(Guardrail):
    @property
    def check_id(self) -> str:
        return "TEST.1"
    
    @property
    def name(self) -> str:
        return "Trivial passing check"
    
    def check(self, context: dict) -> GuardrailResult:
        return GuardrailResult(
            check_id=self.check_id,
            name=self.name,
            status=GuardrailStatus.PASS,
            message="OK",
        )


def test_runner_executes_guardrails():
    runner = GuardrailRunner([TrivialPass()])
    results = runner.run({})
    assert len(results) == 1
    assert results[0].status == GuardrailStatus.PASS
```

---

## PARTE H — CLI, Config, Logging

### H.1 — `shared/config.py`

```python
"""Application configuration."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PTE_",
        case_sensitive=False,
        extra="ignore",
    )
    
    # LLM Providers
    anthropic_api_key: SecretStr = Field(..., alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr = Field(..., alias="OPENAI_API_KEY")
    fmp_api_key: SecretStr = Field(..., alias="FMP_API_KEY")
    
    # Paths
    data_dir: Path = Field(default=Path.home() / "workspace" / "portfolio-thesis-engine" / "data")
    backup_dir: Path = Field(default=Path.home() / "workspace" / "portfolio-thesis-engine" / "backup")
    
    # Models
    llm_model_judgment: str = "claude-opus-4-7"
    llm_model_analysis: str = "claude-sonnet-4-6"
    llm_model_classification: str = "claude-haiku-4-5-20251001"
    llm_model_embeddings: str = "text-embedding-3-small"
    
    # Cost controls
    llm_max_cost_per_company_usd: float = 15.0
    llm_max_tokens_per_request: int = 200_000
    
    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"
    
    # Feature flags
    enable_cost_tracking: bool = True
    enable_guardrails: bool = True
    enable_telemetry: bool = False
    
    def secret(self, name: str) -> str:
        """Get secret value as plain string."""
        val = getattr(self, name)
        return val.get_secret_value() if isinstance(val, SecretStr) else val


# Singleton
settings = Settings()
```

### H.2 — `shared/logging_.py`

```python
"""Structured logging setup."""

import logging
import sys

import structlog

from portfolio_thesis_engine.shared.config import settings


def setup_logging() -> None:
    """Configure structlog."""
    
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )
    
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
```

### H.3 — CLI skeleton

```python
# cli/app.py
"""Main CLI app for Portfolio Thesis Engine."""

import typer
from rich.console import Console

from portfolio_thesis_engine.cli.health_cmd import health_check
from portfolio_thesis_engine.cli.setup_cmd import setup
from portfolio_thesis_engine.cli.smoke_cmd import smoke_test

app = typer.Typer(
    name="pte",
    help="Portfolio Thesis Engine CLI",
    no_args_is_help=True,
)

app.command("setup")(setup)
app.command("health-check")(health_check)
app.command("smoke-test")(smoke_test)


if __name__ == "__main__":
    app()
```

```python
# cli/health_cmd.py
"""Health check command."""

from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.shared.config import settings

console = Console()


def health_check() -> None:
    """Check system health."""
    console.print("[bold]Portfolio Thesis Engine — Health Check[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")
    
    # Check Python version
    import sys
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    py_ok = sys.version_info >= (3, 12)
    table.add_row(
        "Python",
        "[green]OK[/green]" if py_ok else "[red]FAIL[/red]",
        f"Version {py_version} (requires 3.12+)",
    )
    
    # Check API keys configured
    for key_name in ["anthropic_api_key", "openai_api_key", "fmp_api_key"]:
        has_key = bool(settings.secret(key_name))
        table.add_row(
            key_name.upper(),
            "[green]OK[/green]" if has_key else "[red]MISSING[/red]",
            "Configured" if has_key else "Not configured in .env",
        )
    
    # Check data directory
    data_ok = settings.data_dir.exists() or settings.data_dir.parent.exists()
    table.add_row(
        "Data Directory",
        "[green]OK[/green]" if data_ok else "[yellow]WARN[/yellow]",
        str(settings.data_dir),
    )
    
    console.print(table)
```

```python
# cli/smoke_cmd.py
"""Smoke test command — verifies end-to-end works."""

from rich.console import Console

console = Console()


def smoke_test() -> None:
    """Run smoke tests."""
    console.print("[bold]Running smoke tests...[/bold]\n")
    
    tests = [
        ("Storage roundtrip", _test_storage),
        ("LLM call (Anthropic)", _test_anthropic),
        ("Embeddings (OpenAI)", _test_openai),
        ("Guardrail runner", _test_guardrails),
    ]
    
    passed = 0
    for name, fn in tests:
        try:
            fn()
            console.print(f"  [green]✓[/green] {name}")
            passed += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {name}: {e}")
    
    console.print(f"\n[bold]{passed}/{len(tests)} tests passed[/bold]")


def _test_storage():
    """Test basic storage operations."""
    # Claude Code: implement using in-memory Position fixture
    raise NotImplementedError("Claude Code to implement")


def _test_anthropic():
    """Test Anthropic API call with minimal prompt."""
    # Claude Code: implement
    raise NotImplementedError("Claude Code to implement")


def _test_openai():
    """Test OpenAI embeddings call."""
    # Claude Code: implement
    raise NotImplementedError("Claude Code to implement")


def _test_guardrails():
    """Test guardrail runner."""
    # Claude Code: implement
    raise NotImplementedError("Claude Code to implement")
```

---

## PARTE I — DevOps

### I.1 — `scripts/provision_vps.sh`

```bash
#!/usr/bin/env bash
# VPS provisioning script for Ubuntu 24.04
# Usage: ./scripts/provision_vps.sh

set -euo pipefail

echo "=== Portfolio Thesis Engine — VPS Provisioning ==="

# 1. System update
echo "[1/8] Updating system..."
sudo apt update && sudo apt upgrade -y

# 2. Essential packages
echo "[2/8] Installing essentials..."
sudo apt install -y \
    build-essential \
    git \
    curl \
    wget \
    tmux \
    htop \
    jq \
    rclone \
    fail2ban

# 3. Python 3.12
echo "[3/8] Installing Python 3.12..."
sudo apt install -y python3.12 python3.12-venv python3.12-dev python3-pip

# 4. uv package manager
echo "[4/8] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.cargo/env" 2>/dev/null || source "$HOME/.bashrc"

# 5. Workspace
echo "[5/8] Creating workspace..."
mkdir -p "$HOME/workspace/portfolio-thesis-engine"
cd "$HOME/workspace"

# 6. Fail2ban configuration
echo "[6/8] Configuring fail2ban..."
sudo systemctl enable --now fail2ban

# 7. Tailscale check
echo "[7/8] Checking Tailscale..."
if ! command -v tailscale &> /dev/null; then
    echo "  Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "  [!] Run 'sudo tailscale up' manually to authenticate"
fi

# 8. Repo clone prompt
echo "[8/8] Ready to clone repo."
echo ""
echo "Next steps:"
echo "  1. cd $HOME/workspace"
echo "  2. git clone https://github.com/hugocondesa-debug/portfolio-thesis-engine.git"
echo "  3. cd portfolio-thesis-engine"
echo "  4. cp .env.example .env && \${EDITOR:-nano} .env"
echo "  5. uv sync"
echo "  6. uv run pte health-check"

echo ""
echo "=== Provisioning complete ==="
```

### I.2 — `systemd/pte-streamlit.service`

```ini
[Unit]
Description=Portfolio Thesis Engine - Streamlit UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/workspace/portfolio-thesis-engine
Environment="PATH=/home/YOUR_USER/.local/bin:/usr/bin"
EnvironmentFile=/home/YOUR_USER/workspace/portfolio-thesis-engine/.env
ExecStart=/home/YOUR_USER/.local/bin/uv run streamlit run src/portfolio_thesis_engine/ui/app.py --server.port=8501 --server.address=0.0.0.0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### I.3 — `scripts/backup.sh`

```bash
#!/usr/bin/env bash
# Daily backup script — runs via systemd timer

set -euo pipefail

BACKUP_ROOT="$HOME/workspace/portfolio-thesis-engine/backup"
DATA_DIR="$HOME/workspace/portfolio-thesis-engine/data"
TODAY=$(date +%Y-%m-%d)
BACKUP_PATH="$BACKUP_ROOT/daily/$TODAY"

mkdir -p "$BACKUP_PATH"

# 1. Backup YAMLs (using tar — preserves structure)
echo "Backing up YAMLs..."
tar -czf "$BACKUP_PATH/yamls.tar.gz" -C "$DATA_DIR" yamls/

# 2. Backup DuckDB
if [ -f "$DATA_DIR/timeseries.duckdb" ]; then
    echo "Backing up DuckDB..."
    cp "$DATA_DIR/timeseries.duckdb" "$BACKUP_PATH/timeseries.duckdb"
fi

# 3. Backup SQLite
if [ -f "$DATA_DIR/metadata.sqlite" ]; then
    echo "Backing up SQLite..."
    sqlite3 "$DATA_DIR/metadata.sqlite" ".backup $BACKUP_PATH/metadata.sqlite"
fi

# 4. Remote backup via rclone (if configured)
if command -v rclone &> /dev/null && rclone listremotes | grep -q backup:; then
    echo "Syncing to remote..."
    rclone sync "$BACKUP_ROOT/daily/$TODAY" "backup:portfolio-thesis-engine/$TODAY"
fi

# 5. Cleanup old backups
echo "Cleaning old backups..."
# Daily: keep 30 days
find "$BACKUP_ROOT/daily" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +

echo "Backup complete: $BACKUP_PATH"
```

### I.4 — `systemd/pte-backup.timer`

```ini
[Unit]
Description=Daily backup timer for Portfolio Thesis Engine

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

---

## PARTE J — Testing

### J.1 — `tests/conftest.py`

```python
"""Shared test fixtures."""

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    Profile,
)


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Isolated data directory for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "yamls" / "companies").mkdir(parents=True)
    (data_dir / "yamls" / "portfolio" / "positions").mkdir(parents=True)
    (data_dir / "yamls" / "market_contexts").mkdir(parents=True)
    return data_dir


@pytest.fixture
def sample_fiscal_period() -> FiscalPeriod:
    return FiscalPeriod(year=2025, label="FY2025")


@pytest.fixture
def sample_company_identity():
    from portfolio_thesis_engine.schemas.company import CompanyIdentity
    return CompanyIdentity(
        ticker="MTRO.L",
        name="Metro Bank Holdings PLC",
        reporting_currency=Currency.GBP,
        profile=Profile.P2_BANKS,
        fiscal_year_end_month=12,
        country_domicile="GB",
        exchange="LSE",
        shares_outstanding=Decimal("673.29"),
    )


@pytest.fixture
def mock_llm_response():
    """Factory for mock LLM responses."""
    from portfolio_thesis_engine.llm.base import LLMResponse
    
    def _make(content: str = "test response", cost: Decimal = Decimal("0.01")):
        return LLMResponse(
            content=content,
            input_tokens=100,
            output_tokens=50,
            cost_usd=cost,
            model_used="claude-sonnet-4-6",
            latency_ms=500,
        )
    
    return _make
```

### J.2 — Test coverage esperada

Para Fase 0, esperamos tests para:

- **Schemas** (`test_schemas.py`): instantiation, validation, serialization (to/from YAML)
- **Storage** (`test_storage.py`): CRUD per Repository, versioning, atomic writes
- **LLM** (`test_llm.py`): mocked providers, retry logic, cost tracking
- **Market data** (`test_market_data.py`): mocked FMP responses
- **Guardrails** (`test_guardrails.py`): runner, overall status, blocking behavior
- **Config** (`test_config.py`): loading, validation, secrets

Target coverage: **≥80%** nos módulos da Fase 0.

---

## PARTE K — Sequência de Implementação para Claude Code

Ordem recomendada, de forma que cada passo é testável sozinho:

1. **Setup básico** — `pyproject.toml`, `.env.example`, `.gitignore`, `README.md`, `src/` vazio, `tests/` vazio. Confirma `uv sync` funciona.

2. **Shared utilities** — `shared/config.py`, `shared/logging_.py`, `shared/exceptions.py`, `shared/types.py`. Tests correspondentes.

3. **Schemas** — `schemas/common.py` → `schemas/base.py` → restantes. Tests para cada.

4. **Storage base** — `storage/base.py`, `storage/yaml_repo.py`. Tests de CRUD.

5. **Storage completo** — `storage/duckdb_repo.py`, `storage/sqlite_repo.py`, `storage/chroma_repo.py`, `storage/filesystem_repo.py`. Tests para cada.

6. **LLM orchestrator** — `llm/base.py` → `llm/cost_tracker.py` → `llm/anthropic_provider.py` → `llm/openai_provider.py` → `llm/retry.py` → `llm/router.py`. Tests com mocks.

7. **Market data** — `market_data/base.py` → `market_data/fmp_provider.py`. Tests com mocks.

8. **Guardrails** — `guardrails/base.py` → `guardrails/runner.py`. Tests.

9. **CLI** — `cli/app.py` → `cli/setup_cmd.py` → `cli/health_cmd.py` → `cli/smoke_cmd.py`.

10. **UI stub** — `ui/app.py` com Streamlit "Hello World" placeholder.

11. **DevOps** — `scripts/provision_vps.sh`, `scripts/backup.sh`, `systemd/*.service`.

12. **Integration tests** — `tests/integration/test_smoke.py` end-to-end.

13. **Documentação** — `docs/architecture.md`, `docs/schemas.md`.

14. **Final check** — `uv run pte health-check`, `uv run pte smoke-test`, `uv run pytest` — tudo passa.

---

## PARTE L — Checklist Final de Aceitação

Antes de considerar Fase 0 completa, verifica:

- [ ] `uv sync` funciona sem erros
- [ ] `uv run pytest` — todos os tests passam, coverage ≥80%
- [ ] `uv run pte health-check` reporta tudo OK
- [ ] `uv run pte smoke-test` passa todos os smoke tests
- [ ] `uv run streamlit run src/portfolio_thesis_engine/ui/app.py` arranca (página vazia)
- [ ] Serviço systemd `pte-streamlit.service` arranca no VPS
- [ ] Backup script executa sem erros
- [ ] Tailscale permite aceder ao Streamlit do laptop/iPhone
- [ ] Todos os schemas têm docstrings
- [ ] README actualizado com instruções de setup
- [ ] `.env.example` tem todas as keys necessárias
- [ ] `.gitignore` exclui `.env`, `data/`, `*.duckdb`, `*.sqlite`
- [ ] Commit inicial feito e pushed para GitHub

---

## Notas finais

Claude Code, ao implementar:

1. **Não inventes novas decisões arquitecturais.** Se algo não está claro, regista como TODO e pergunta ao Hugo.
2. **Mantém fidelidade aos schemas.** São o contrato entre módulos das futuras fases.
3. **Testes primeiro onde fizer sentido.** TDD para Repositories e guardrails é especialmente valioso.
4. **Código limpo > código ambicioso.** Fase 0 é fundações; resistência a over-engineering.
5. **Documenta decisões non-obvious** em docstrings com rationale.
6. **Commits pequenos e frequentes.** Facilita review pelo Hugo.

Se encontrares ambiguidade real durante a implementação, **para e pergunta**. É melhor clarificar que implementar na direcção errada.

Boa construção.

---

**Fim da Spec Fase 0**
