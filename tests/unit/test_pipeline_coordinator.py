"""Unit tests for pipeline.coordinator.PipelineCoordinator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.cross_check.base import (
    CrossCheckMetric,
    CrossCheckReport,
    CrossCheckStatus,
)
from portfolio_thesis_engine.extraction.base import (
    ExtractionResult as ExtractionEngineResult,
)
from portfolio_thesis_engine.extraction.base import parse_fiscal_period
from portfolio_thesis_engine.pipeline.coordinator import (
    CrossCheckBlocked,
    PipelineCoordinator,
    PipelineError,
    PipelineStage,
)
from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    GuardrailStatus,
    Profile,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    CanonicalCompanyState,
    CompanyIdentity,
    IncomeStatementLine,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult as SectionExtractionResult,
)
from portfolio_thesis_engine.section_extractor.base import StructuredSection

# ======================================================================
# Fixtures
# ======================================================================


def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _wacc_markdown() -> str:
    return """---
ticker: 1846.HK
profile: P1
valuation_date: "2024-12-31"
current_price: "12.30"
cost_of_capital:
  risk_free_rate: 2.5
  equity_risk_premium: 5.5
  beta: 1.1
  cost_of_debt_pretax: 4.0
  tax_rate_for_wacc: 16.5
capital_structure:
  debt_weight: 25
  equity_weight: 75
scenarios:
  base:
    probability: 100
    revenue_cagr_explicit_period: 8
    terminal_growth: 3
    terminal_operating_margin: 20
---
"""


def _fake_section_result() -> SectionExtractionResult:
    return SectionExtractionResult(
        doc_id="1846-HK/ar/2024.md",
        ticker="1846.HK",
        fiscal_period="FY2024",
        sections=[
            StructuredSection(
                "income_statement",
                "IS",
                "",
                parsed_data={
                    "line_items": [
                        {"label": "Revenue", "value_current": 580, "category": "revenue"},
                        {"label": "Net income", "value_current": 75, "category": "net_income"},
                    ]
                },
            ),
            StructuredSection(
                "balance_sheet",
                "BS",
                "",
                parsed_data={
                    "line_items": [
                        {"label": "Total assets", "value_current": 3200, "category": "total_assets"},
                    ]
                },
            ),
        ],
    )


def _make_canonical(ticker: str = "1846.HK") -> CanonicalCompanyState:
    period = _period()
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker=ticker,
            name="Stub",
            reporting_currency=Currency.HKD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=12,
            country_domicile="HK",
            exchange="HKEX",
        ),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=[
                    IncomeStatementLine(label="Revenue", value=Decimal("580")),
                    IncomeStatementLine(label="Net income", value=Decimal("580")),
                ],
                balance_sheet=[],
                cash_flow=[],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("100"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("100"),
                    financial_assets=Decimal("0"),
                    financial_liabilities=Decimal("0"),
                    equity_claims=Decimal("100"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("10"),
                    operating_taxes=Decimal("0"),
                    nopat=Decimal("10"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("0"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("10"),
                )
            ],
            ratios_by_period=[KeyRatios(period=period)],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(check_id="V.0", name="s", status="PASS", detail="ok")
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=["A", "B", "C"],
        ),
    )


def _pass_report(ticker: str = "1846.HK") -> CrossCheckReport:
    return CrossCheckReport(
        ticker=ticker,
        period="FY2024",
        metrics=[
            CrossCheckMetric(
                metric="revenue",
                extracted_value=Decimal("580"),
                fmp_value=Decimal("580"),
                yfinance_value=Decimal("580"),
                max_delta_pct=Decimal("0"),
                status=CrossCheckStatus.PASS,
            )
        ],
        overall_status=CrossCheckStatus.PASS,
        blocking=False,
        generated_at=datetime.now(UTC),
    )


def _fail_report(ticker: str = "1846.HK") -> CrossCheckReport:
    return CrossCheckReport(
        ticker=ticker,
        period="FY2024",
        metrics=[],
        overall_status=CrossCheckStatus.FAIL,
        blocking=True,
        generated_at=datetime.now(UTC),
    )


@pytest.fixture
def _setup(tmp_path: Path) -> dict[str, object]:
    """Build a fully-mocked PipelineCoordinator and the moving parts
    tests need to assert against."""
    doc_repo = MagicMock()
    doc_repo.list_documents = MagicMock(
        return_value=[tmp_path / "1846-HK" / "annual_report" / "ar.md"]
    )
    # Create the file so wacc_path resolution + section extract have a real file.
    (tmp_path / "1846-HK" / "annual_report").mkdir(parents=True)
    (tmp_path / "1846-HK" / "annual_report" / "ar.md").write_text(
        "# Report\n\nSynthetic", encoding="utf-8"
    )

    wacc_path = tmp_path / "wacc_inputs.md"
    wacc_path.write_text(_wacc_markdown(), encoding="utf-8")

    # Section extractor returns a canned SectionExtractionResult.
    section_extractor = MagicMock()
    section_extractor.extract = AsyncMock(return_value=_fake_section_result())

    # CrossCheckGate returns a PASS report by default.
    cross_check_gate = MagicMock()
    cross_check_gate.check = AsyncMock(return_value=_pass_report())

    # ExtractionCoordinator returns a canonical state.
    extraction_coordinator = MagicMock()
    extraction_coordinator.extract_canonical = AsyncMock(
        return_value=ExtractionEngineResult(
            ticker="1846.HK",
            fiscal_period_label="FY2024",
            primary_period=parse_fiscal_period("FY2024"),
            adjustments=[],
            decision_log=[],
            estimates_log=[],
            modules_run=["A", "B", "C"],
            canonical_state=_make_canonical(),
        )
    )

    metadata_repo = MagicMock()
    metadata_repo.get_company = MagicMock(return_value=None)

    state_repo = MagicMock()

    coord = PipelineCoordinator(
        document_repo=doc_repo,
        metadata_repo=metadata_repo,
        section_extractor=section_extractor,
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=state_repo,
        runs_log_dir=tmp_path / "logs",
    )
    return {
        "coord": coord,
        "wacc_path": wacc_path,
        "tmp_path": tmp_path,
        "doc_repo": doc_repo,
        "metadata_repo": metadata_repo,
        "state_repo": state_repo,
        "cross_check_gate": cross_check_gate,
        "section_extractor": section_extractor,
        "extraction_coordinator": extraction_coordinator,
    }


# ======================================================================
# 1. Happy path
# ======================================================================


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_runs_all_stages_in_order(self, _setup: dict[str, object]) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
        )
        stage_names = [s.stage for s in outcome.stages]
        # Sprint 9 added VALUATE + PERSIST_VALUATION; Sprint 10 adds
        # COMPOSE_FICHA. All three SKIP when their wiring is absent
        # (default in this test fixture).
        assert stage_names == [
            PipelineStage.CHECK_INGESTION,
            PipelineStage.LOAD_WACC,
            PipelineStage.SECTION_EXTRACT,
            PipelineStage.CROSS_CHECK,
            PipelineStage.EXTRACT_CANONICAL,
            PipelineStage.PERSIST,
            PipelineStage.GUARDRAILS,
            PipelineStage.VALUATE,
            PipelineStage.PERSIST_VALUATION,
            PipelineStage.COMPOSE_FICHA,
        ]
        assert outcome.success is True
        assert outcome.canonical_state is not None
        assert outcome.cross_check_report is not None
        assert outcome.log_path is not None and outcome.log_path.exists()

    @pytest.mark.asyncio
    async def test_persists_canonical_state(self, _setup: dict[str, object]) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        state_repo = _setup["state_repo"]  # type: ignore[index]

        await coord.process("1846.HK", wacc_path=wacc_path)  # type: ignore[arg-type]
        state_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_log_has_stage_entries(self, _setup: dict[str, object]) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]

        outcome = await coord.process("1846.HK", wacc_path=wacc_path)  # type: ignore[arg-type]
        assert outcome.log_path is not None
        lines = outcome.log_path.read_text(encoding="utf-8").strip().splitlines()
        # Header + 10 stages (7 Sprint 8 + 2 SKIP valuation + 1 SKIP
        # ficha) + N guardrails
        assert lines[0].startswith('{"type": "run_header"')
        stage_lines = [ln for ln in lines if '"type": "stage"' in ln]
        assert len(stage_lines) == 10
        guardrail_lines = [ln for ln in lines if '"type": "guardrail"' in ln]
        assert len(guardrail_lines) >= 1


# ======================================================================
# 2. Failure modes
# ======================================================================


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_no_ingested_documents_raises(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        doc_repo = _setup["doc_repo"]  # type: ignore[index]
        doc_repo.list_documents = MagicMock(return_value=[])

        with pytest.raises(PipelineError, match="No documents ingested"):
            await coord.process("1846.HK", wacc_path=wacc_path)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_cross_check_blocking_raises_without_skip(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        gate = _setup["cross_check_gate"]  # type: ignore[index]
        gate.check = AsyncMock(return_value=_fail_report())

        with pytest.raises(CrossCheckBlocked):
            await coord.process("1846.HK", wacc_path=wacc_path)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_cross_check_blocking_bypassed_with_skip(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        gate = _setup["cross_check_gate"]  # type: ignore[index]
        gate.check = AsyncMock(return_value=_fail_report())

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            skip_cross_check=True,
        )
        # Cross-check stage marked as skip, pipeline finished
        cc_stage = next(s for s in outcome.stages if s.stage == PipelineStage.CROSS_CHECK)
        assert cc_stage.status == "skip"
        # gate.check must NOT have been called
        gate.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_wacc_parse_failure_raises(
        self, _setup: dict[str, object], tmp_path: Path
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        bogus = tmp_path / "bogus.md"
        bogus.write_text("not yaml", encoding="utf-8")

        with pytest.raises(PipelineError, match="Failed to parse WACC"):
            await coord.process("1846.HK", wacc_path=bogus)  # type: ignore[arg-type]


# ======================================================================
# 3. Flags
# ======================================================================


class TestFlags:
    @pytest.mark.asyncio
    async def test_force_cost_override_raises_cap(
        self, _setup: dict[str, object]
    ) -> None:
        from portfolio_thesis_engine.shared.config import settings

        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        original_cap = settings.llm_max_cost_per_company_usd

        # The cost cap is raised for the duration of the run. We probe by
        # attaching a side-effect to extract_canonical that reads
        # settings.llm_max_cost_per_company_usd at call-time.
        observed: list[float] = []
        ec = _setup["extraction_coordinator"]  # type: ignore[index]
        original_ec = ec.extract_canonical

        async def spy(*a: object, **kw: object):  # type: ignore[no-untyped-def]
            observed.append(settings.llm_max_cost_per_company_usd)
            return await original_ec(*a, **kw)

        ec.extract_canonical = AsyncMock(side_effect=spy)

        await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            force_cost_override=True,
        )
        # Cap was raised inside the run and restored after.
        assert observed[0] > original_cap
        assert settings.llm_max_cost_per_company_usd == original_cap


# ======================================================================
# 4. Guardrail failure propagates to outcome.success
# ======================================================================


class TestGuardrailFailure:
    @pytest.mark.asyncio
    async def test_guardrail_fail_marks_outcome_unsuccessful(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        ec = _setup["extraction_coordinator"]  # type: ignore[index]

        # Force a broken canonical state (IS components don't match NI).
        broken = _make_canonical()
        broken.reclassified_statements[0].income_statement.clear()
        broken.reclassified_statements[0].income_statement.extend(
            [
                IncomeStatementLine(label="Revenue", value=Decimal("100")),
                IncomeStatementLine(label="Tax", value=Decimal("-50")),
                IncomeStatementLine(label="Net income", value=Decimal("999")),
            ]
        )
        ec.extract_canonical = AsyncMock(
            return_value=ExtractionEngineResult(
                ticker="1846.HK",
                fiscal_period_label="FY2024",
                primary_period=parse_fiscal_period("FY2024"),
                adjustments=[],
                decision_log=[],
                estimates_log=[],
                modules_run=["A", "B", "C"],
                canonical_state=broken,
            )
        )

        outcome = await coord.process("1846.HK", wacc_path=wacc_path)  # type: ignore[arg-type]
        assert outcome.success is False
        assert outcome.overall_guardrail_status == GuardrailStatus.FAIL
