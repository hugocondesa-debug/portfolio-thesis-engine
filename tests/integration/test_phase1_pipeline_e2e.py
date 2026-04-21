"""End-to-end smoke for the Phase 1 pipeline.

Runs the full :class:`PipelineCoordinator.process` chain over the
synthetic EuroEyes fixture (``tests/fixtures/euroeyes/*``) with:

- Real ingestion (documents end up on disk in a tmp directory).
- Real section extractor but with the Anthropic LLM replaced by a
  dispatch mock that returns canned TOC + per-section parsed_data.
- Real cross-check gate with FMP + yfinance providers replaced by
  MagicMocks that return values matching the fixture so the gate
  PASSes.
- Real :class:`ExtractionCoordinator` (Modules A, B, C + Analysis).
- Real :class:`CompanyStateRepository` writing into tmp.
- Real Guardrails A + V.

Asserts:

- All 7 pipeline stages ran.
- ``outcome.success`` is True.
- A valid :class:`CanonicalCompanyState` was persisted.
- The run-log JSONL file was written.
- The overall guardrail status is PASS or WARN (not FAIL).

The test is in-suite (no ``integration`` marker) because everything is
mocked — it's the strongest protection we have against regressions that
cross module boundaries.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.llm.base import LLMResponse
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.pipeline import PipelineCoordinator
from portfolio_thesis_engine.schemas.common import Currency, GuardrailStatus, Profile
from portfolio_thesis_engine.section_extractor.p1_extractor import P1IndustrialExtractor
from portfolio_thesis_engine.section_extractor.tools import (
    BALANCE_SHEET_TOOL_NAME,
    CASH_FLOW_TOOL_NAME,
    INCOME_STATEMENT_TOOL_NAME,
    LEASES_TOOL_NAME,
    MDA_TOOL_NAME,
    REPORT_SECTIONS_TOOL_NAME,
    SEGMENTS_TOOL_NAME,
    TAX_RECON_TOOL_NAME,
)
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyStateRepository,
    ValuationRepository,
)
from portfolio_thesis_engine.valuation import (
    FCFFDCFEngine,
    ScenarioComposer,
    ValuationComposer,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "euroeyes"


# ======================================================================
# Canned parsed_data (mirrors tests/fixtures/euroeyes/annual_report_2024_minimal.md)
# ======================================================================


def _toc_response() -> LLMResponse:
    return LLMResponse(
        content="",
        structured_output={
            "primary_fiscal_period": "FY2024",
            "sections": [
                {
                    "section_type": "income_statement",
                    "title": "Consolidated Income Statement",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    "end_marker": "## 3. Consolidated Balance Sheet",
                },
                {
                    "section_type": "balance_sheet",
                    "title": "Consolidated Balance Sheet",
                    "start_marker": "## 3. Consolidated Balance Sheet (as of 31 December 2024)",
                    "end_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                },
                {
                    "section_type": "cash_flow",
                    "title": "Cash Flow Statement",
                    "start_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                    "end_marker": "## 5. Segment Information",
                },
                {
                    "section_type": "notes_taxes",
                    "title": "Note 7 — Income Tax Reconciliation",
                    "start_marker": "### Note 7 — Income Tax Reconciliation",
                    "end_marker": "### Note 8 — Leases (IFRS 16)",
                },
                {
                    "section_type": "notes_leases",
                    "title": "Note 8 — Leases (IFRS 16)",
                    "start_marker": "### Note 8 — Leases (IFRS 16)",
                    "end_marker": "### Note 9 — Provisions",
                },
            ],
        },
        input_tokens=800,
        output_tokens=150,
        cost_usd=Decimal("0.002"),
        model_used="claude-sonnet-4-6",
    )


_IS_PARSED = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "Revenue", "value_current": 580.0, "category": "revenue"},
        {"label": "Cost of sales", "value_current": -290.0, "category": "cost_of_sales"},
        {"label": "Selling and marketing", "value_current": -95.0, "category": "opex"},
        {"label": "General and administrative", "value_current": -65.0, "category": "opex"},
        {
            "label": "Depreciation and amortisation",
            "value_current": -20.0,
            "category": "d_and_a",
        },
        {"label": "Operating income", "value_current": 110.0, "category": "operating_income"},
        {"label": "Finance income", "value_current": 4.0, "category": "finance_income"},
        {"label": "Finance expense", "value_current": -18.0, "category": "finance_expense"},
        {"label": "Income tax expense", "value_current": -21.0, "category": "tax"},
        {"label": "Net income", "value_current": 75.0, "category": "net_income"},
    ],
}

_BS_PARSED = {
    "as_of_date": "2024-12-31",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "Cash and equivalents", "value_current": 450.0, "category": "cash"},
        {"label": "Trade receivables", "value_current": 120.0, "category": "operating_assets"},
        {"label": "Inventories", "value_current": 80.0, "category": "operating_assets"},
        {"label": "PP&E", "value_current": 950.0, "category": "operating_assets"},
        {"label": "Right-of-use assets", "value_current": 380.0, "category": "operating_assets"},
        {"label": "Intangible assets", "value_current": 420.0, "category": "intangibles"},
        {"label": "Goodwill", "value_current": 600.0, "category": "intangibles"},
        {"label": "Other assets", "value_current": 200.0, "category": "operating_assets"},
        {"label": "Trade payables", "value_current": 95.0, "category": "operating_liabilities"},
        {
            "label": "Lease liabilities (current)",
            "value_current": 60.0,
            "category": "lease_liabilities",
        },
        {
            "label": "Short-term borrowings",
            "value_current": 150.0,
            "category": "financial_liabilities",
        },
        {
            "label": "Lease liabilities (non-current)",
            "value_current": 310.0,
            "category": "lease_liabilities",
        },
        {
            "label": "Long-term borrowings",
            "value_current": 580.0,
            "category": "financial_liabilities",
        },
        {"label": "Other liabilities", "value_current": 105.0, "category": "operating_liabilities"},
        {"label": "Total equity", "value_current": 1900.0, "category": "equity"},
    ],
}

_CF_PARSED = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "Operating cash flow", "value_current": 135.0, "category": "cfo"},
        {"label": "Capital expenditure", "value_current": -75.0, "category": "capex"},
        {"label": "Investing cash flow", "value_current": -75.0, "category": "cfi"},
        {"label": "Dividends paid", "value_current": -25.0, "category": "dividends"},
        {"label": "Net debt issuance", "value_current": 35.0, "category": "debt_issuance"},
        {
            "label": "Lease liability payments",
            "value_current": -55.0,
            "category": "lease_payments",
        },
        {"label": "Financing cash flow", "value_current": -45.0, "category": "cff"},
        {"label": "Net change in cash", "value_current": 15.0, "category": "net_change_in_cash"},
    ],
}

_TAXES_PARSED = {
    "fiscal_period": "FY2024",
    "statutory_rate_pct": 16.5,
    "effective_rate_pct": 21.9,
    "profit_before_tax": 96.0,
    "statutory_tax": 15.84,
    "reported_tax_expense": 21.0,
    "reconciling_items": [
        {
            "label": "Effect of lower tax rate in Germany (~15.8%)",
            "amount": -0.2,
            "category": "rate_diff_jurisdiction",
        },
        {
            "label": "Non-deductible expenses",
            "amount": 1.5,
            "category": "non_deductible",
        },
        {
            "label": "Prior-year adjustments",
            "amount": 0.8,
            "category": "prior_year_adjustment",
        },
        {
            "label": "Tax loss carry-forward utilisation",
            "amount": -1.0,
            "category": "tax_loss_utilisation",
        },
    ],
}

_LEASES_PARSED = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "rou_assets_by_category": [
        {"category": "Medical facilities", "value_current": 280.0},
        {"category": "Office space", "value_current": 70.0},
        {"category": "Equipment", "value_current": 30.0},
    ],
    "lease_liability_movement": {
        "opening_balance": 350.0,
        "additions": 55.0,
        "depreciation_of_rou": 45.0,
        "interest_expense": 15.0,
        "principal_payments": 40.0,
        "closing_balance": 370.0,
    },
}


_PARSE_RESPONSES: dict[str, dict] = {
    INCOME_STATEMENT_TOOL_NAME: _IS_PARSED,
    BALANCE_SHEET_TOOL_NAME: _BS_PARSED,
    CASH_FLOW_TOOL_NAME: _CF_PARSED,
    SEGMENTS_TOOL_NAME: {"fiscal_period": "FY2024", "segments": []},
    TAX_RECON_TOOL_NAME: _TAXES_PARSED,
    LEASES_TOOL_NAME: _LEASES_PARSED,
    MDA_TOOL_NAME: {"fiscal_period": "FY2024"},
}


def _dispatch_llm() -> MagicMock:
    """MagicMock whose ``complete`` returns the TOC or parsed payload
    depending on which tool the request targets."""
    llm = MagicMock()

    async def complete(request):  # type: ignore[no-untyped-def]
        tool_names = [t["name"] for t in (request.tools or [])]
        if REPORT_SECTIONS_TOOL_NAME in tool_names:
            return _toc_response()
        for name in tool_names:
            if name in _PARSE_RESPONSES:
                return LLMResponse(
                    content="",
                    structured_output=_PARSE_RESPONSES[name],
                    input_tokens=300,
                    output_tokens=80,
                    cost_usd=Decimal("0.0008"),
                    model_used="claude-sonnet-4-6",
                )
        return LLMResponse(
            content="",
            structured_output=None,
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            model_used="claude-sonnet-4-6",
        )

    llm.complete = AsyncMock(side_effect=complete)
    return llm


def _fake_providers() -> tuple[MagicMock, MagicMock]:
    """FMP + yfinance mocks returning values matching the fixture."""
    fmp = MagicMock()
    fmp.__aenter__ = AsyncMock(return_value=fmp)
    fmp.__aexit__ = AsyncMock(return_value=None)
    fmp.get_fundamentals = AsyncMock(
        return_value={
            "income_statement": [
                {
                    "revenue": 580,
                    "operatingIncome": 110,
                    "netIncome": 75,
                }
            ],
            "balance_sheet": [
                {
                    "totalAssets": 3200,
                    "totalStockholdersEquity": 1900,
                    "cashAndCashEquivalents": 450,
                }
            ],
            "cash_flow": [
                {"operatingCashFlow": 135, "capitalExpenditure": -75}
            ],
        }
    )
    fmp.get_key_metrics = AsyncMock(
        return_value={"records": [{"sharesOutstanding": 200_000_000, "marketCap": 2_460_000_000}]}
    )

    yf = MagicMock()
    yf.get_fundamentals = AsyncMock(
        return_value={
            "income_statement": [
                {
                    "Total Revenue": 581,
                    "Operating Income": 109,
                    "Net Income": 75,
                }
            ],
            "balance_sheet": [
                {
                    "Total Assets": 3195,
                    "Stockholders Equity": 1895,
                    "Cash And Cash Equivalents": 449,
                }
            ],
            "cash_flow": [
                {"Operating Cash Flow": 134, "Capital Expenditure": -74}
            ],
        }
    )
    yf.get_key_metrics = AsyncMock(
        return_value={"records": [{"sharesOutstanding": 199_000_000, "marketCap": 2_440_000_000}]}
    )
    return fmp, yf


# ======================================================================
# Fixture setup — copy EuroEyes files into a tmp data_dir, ingest them
# ======================================================================


@pytest.fixture
def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )

    # Copy the fixture files somewhere "outside" the data dir to simulate
    # a real analyst workspace.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ar_path = workspace / "annual_report_2024.md"
    wacc_path = workspace / "wacc_inputs.md"
    shutil.copyfile(_FIXTURE_DIR / "annual_report_2024_minimal.md", ar_path)
    shutil.copyfile(_FIXTURE_DIR / "wacc_inputs.md", wacc_path)

    # Ingest the two files (real ingestion, writes into data_dir/documents).
    doc_repo = DocumentRepository()
    meta_repo = MetadataRepository()
    IngestionCoordinator(doc_repo, meta_repo).ingest(
        ticker="1846.HK",
        files=[ar_path, wacc_path],
        mode="bulk_markdown",
        profile="P1",
    )

    # Build real components with mocked LLM + providers.
    llm = _dispatch_llm()
    cost_tracker = CostTracker(log_path=data_dir / "llm_costs.jsonl")
    section_extractor = P1IndustrialExtractor(llm=llm, cost_tracker=cost_tracker)
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=llm,
        cost_tracker=cost_tracker,
    )
    fmp, yf = _fake_providers()
    # Add a get_quote mock to FMP for the valuation market snapshot.
    fmp.get_quote = AsyncMock(
        return_value={
            "price": 12.30,
            "sharesOutstanding": 200_000_000,
            "marketCap": 2_460_000_000,
        }
    )
    cross_check_gate = CrossCheckGate(fmp, yf, log_dir=data_dir / "logs" / "cross_check")
    state_repo = CompanyStateRepository(base_path=data_dir / "yamls" / "companies")
    valuation_repo = ValuationRepository(base_path=data_dir / "yamls" / "companies")

    pipeline = PipelineCoordinator(
        document_repo=doc_repo,
        metadata_repo=meta_repo,
        section_extractor=section_extractor,
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=state_repo,
        runs_log_dir=data_dir / "logs" / "runs",
        valuation_composer=ValuationComposer(),
        scenario_composer=ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5)),
        valuation_repo=valuation_repo,
        market_data_provider=fmp,
    )
    return {
        "pipeline": pipeline,
        "wacc_path": wacc_path,
        "state_repo": state_repo,
        "valuation_repo": valuation_repo,
        "data_dir": data_dir,
    }


# ======================================================================
# Smoke test
# ======================================================================


class TestPhase1E2E:
    @pytest.mark.asyncio
    async def test_euroeyes_end_to_end_succeeds(
        self, _setup: dict[str, object]
    ) -> None:
        pipeline: PipelineCoordinator = _setup["pipeline"]  # type: ignore[assignment]
        wacc_path: Path = _setup["wacc_path"]  # type: ignore[assignment]
        state_repo: CompanyStateRepository = _setup["state_repo"]  # type: ignore[assignment]
        valuation_repo: ValuationRepository = _setup["valuation_repo"]  # type: ignore[assignment]

        outcome = await pipeline.process("1846.HK", wacc_path=wacc_path)

        # All nine stages executed (Sprint 8's 7 + Sprint 9's 2 valuation stages).
        assert len(outcome.stages) == 9
        assert outcome.success is True
        # Overall is PASS or WARN — never FAIL for the calibrated fixture.
        overall = outcome.overall_guardrail_status
        assert overall in (GuardrailStatus.PASS, GuardrailStatus.WARN, GuardrailStatus.SKIP)

        # Canonical state persisted via the repo.
        state = state_repo.get("1846.HK")
        assert state is not None
        assert state.identity.ticker == "1846.HK"
        assert state.identity.reporting_currency == Currency.HKD
        assert state.methodology.protocols_activated == ["A", "B", "C"]
        assert len(state.reclassified_statements) == 1
        rs = state.reclassified_statements[0]
        assert len(rs.income_statement) >= 5
        assert len(rs.balance_sheet) >= 5

        # Cross-check report embedded and PASSing / non-blocking.
        assert outcome.cross_check_report is not None
        assert outcome.cross_check_report.blocking is False

        # Valuation snapshot produced, persisted, and carries 3 scenarios.
        assert outcome.valuation_snapshot is not None
        snap = outcome.valuation_snapshot
        assert len(snap.scenarios) == 3
        labels = [sc.label for sc in snap.scenarios]
        assert labels == ["bear", "base", "bull"]
        assert snap.weighted.expected_value > 0
        assert snap.weighted.fair_value_range_low <= snap.weighted.expected_value
        assert snap.weighted.fair_value_range_high >= snap.weighted.expected_value

        persisted_snap = valuation_repo.get("1846.HK")
        assert persisted_snap is not None
        assert persisted_snap.snapshot_id == snap.snapshot_id

        # Run log written and parseable.
        assert outcome.log_path is not None
        assert outcome.log_path.exists()
        log_lines = outcome.log_path.read_text(encoding="utf-8").strip().splitlines()
        assert any('"type": "run_header"' in ln for ln in log_lines)
        stage_lines = [ln for ln in log_lines if '"type": "stage"' in ln]
        assert len(stage_lines) == 9
        guardrail_lines = [ln for ln in log_lines if '"type": "guardrail"' in ln]
        # 8 default guardrails (4 A.* + 4 V.*)
        assert len(guardrail_lines) == 8
