"""Unit tests for pipeline.coordinator.PipelineCoordinator (Phase 1.5)."""

from __future__ import annotations

import shutil
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
    ExtractionValidationBlocked,
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

_EXTRACTION_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"
)
_WACC_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "wacc" / "euroeyes_real.md"
)


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------
def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _make_canonical() -> CanonicalCompanyState:
    """Synthetic canonical state for the extraction_coordinator mock."""
    period = _period()
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker="1846.HK",
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


def _pass_report() -> CrossCheckReport:
    return CrossCheckReport(
        ticker="1846.HK",
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


def _fail_report() -> CrossCheckReport:
    return CrossCheckReport(
        ticker="1846.HK",
        period="FY2024",
        metrics=[],
        overall_status=CrossCheckStatus.FAIL,
        blocking=True,
        generated_at=datetime.now(UTC),
    )


# ----------------------------------------------------------------------
# Fixture: pipeline with mocks, using the real raw_extraction fixture
# ----------------------------------------------------------------------
@pytest.fixture
def _setup(tmp_path: Path) -> dict[str, object]:
    # Real raw_extraction + wacc inputs copied into the data dir so
    # CHECK_INGESTION sees something and LOAD_EXTRACTION / LOAD_WACC
    # hit real parsers (validator also exercised).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    extraction_path = workspace / "raw_extraction.yaml"
    wacc_path = workspace / "wacc_inputs.md"
    shutil.copyfile(_EXTRACTION_FIXTURE, extraction_path)
    shutil.copyfile(_WACC_FIXTURE, wacc_path)

    doc_repo = MagicMock()
    doc_repo.list_documents = MagicMock(return_value=[extraction_path, wacc_path])

    # Metadata repo stubbed.
    meta_repo = MagicMock()
    meta_repo.get_company = MagicMock(return_value=None)

    # Cross-check gate defaults to PASS report.
    gate = MagicMock()
    gate.check = AsyncMock(return_value=_pass_report())

    # Extraction coordinator returns a canned canonical state.
    ec = MagicMock()
    ec.extract_canonical = AsyncMock(
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

    state_repo = MagicMock()

    coord = PipelineCoordinator(
        document_repo=doc_repo,
        metadata_repo=meta_repo,
        cross_check_gate=gate,
        extraction_coordinator=ec,
        state_repo=state_repo,
        runs_log_dir=tmp_path / "logs",
    )
    return {
        "coord": coord,
        "wacc_path": wacc_path,
        "extraction_path": extraction_path,
        "doc_repo": doc_repo,
        "meta_repo": meta_repo,
        "gate": gate,
        "extraction_coordinator": ec,
        "state_repo": state_repo,
    }


# ======================================================================
# 1. Happy path
# ======================================================================


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_runs_all_stages_in_order(self, _setup: dict[str, object]) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        extraction_path = _setup["extraction_path"]  # type: ignore[index]

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            extraction_path=extraction_path,  # type: ignore[arg-type]
        )
        stage_names = [s.stage for s in outcome.stages]
        # Sprint 9 added VALUATE + PERSIST_VALUATION; Sprint 10 added
        # COMPOSE_FICHA. Sprint 2 (Phase 1.5) replaced SECTION_EXTRACT
        # with LOAD_EXTRACTION + VALIDATE_EXTRACTION. All SKIP stages
        # still appear in the log.
        assert stage_names == [
            PipelineStage.CHECK_INGESTION,
            PipelineStage.LOAD_WACC,
            PipelineStage.LOAD_EXTRACTION,
            PipelineStage.VALIDATE_EXTRACTION,
            PipelineStage.CROSS_CHECK,
            PipelineStage.EXTRACT_CANONICAL,
            PipelineStage.PERSIST,
            PipelineStage.GUARDRAILS,
            PipelineStage.VALUATE,
            PipelineStage.PERSIST_VALUATION,
            PipelineStage.COMPOSE_FICHA,
        ]
        assert outcome.success is True
        assert outcome.raw_extraction is not None
        assert outcome.extraction_validation_strict is not None
        assert outcome.extraction_validation_strict.overall_status == "OK"
        assert outcome.canonical_state is not None

    @pytest.mark.asyncio
    async def test_run_log_has_all_stage_entries(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        extraction_path = _setup["extraction_path"]  # type: ignore[index]

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            extraction_path=extraction_path,  # type: ignore[arg-type]
        )
        assert outcome.log_path is not None
        lines = outcome.log_path.read_text(encoding="utf-8").strip().splitlines()
        stage_lines = [ln for ln in lines if '"type": "stage"' in ln]
        assert len(stage_lines) == 11


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
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        doc_repo = _setup["doc_repo"]  # type: ignore[index]
        doc_repo.list_documents = MagicMock(return_value=[])

        with pytest.raises(PipelineError, match="No documents ingested"):
            await coord.process(
                "1846.HK",
                wacc_path=wacc_path,  # type: ignore[arg-type]
                extraction_path=extraction_path,  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_bad_wacc_path_raises(
        self, _setup: dict[str, object], tmp_path: Path
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        bogus = tmp_path / "bogus.md"
        bogus.write_text("not yaml", encoding="utf-8")
        with pytest.raises(PipelineError, match="Failed to parse WACC"):
            await coord.process(
                "1846.HK",
                wacc_path=bogus,
                extraction_path=extraction_path,  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_bad_extraction_path_raises(
        self, _setup: dict[str, object], tmp_path: Path
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        bogus = tmp_path / "bogus_extraction.yaml"
        bogus.write_text("not yaml", encoding="utf-8")
        with pytest.raises(PipelineError, match="Failed to parse raw_extraction"):
            await coord.process(
                "1846.HK",
                wacc_path=wacc_path,  # type: ignore[arg-type]
                extraction_path=bogus,
            )

    @pytest.mark.asyncio
    async def test_cross_check_blocking_raises_without_skip(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        gate = _setup["gate"]  # type: ignore[index]
        gate.check = AsyncMock(return_value=_fail_report())

        with pytest.raises(CrossCheckBlocked):
            await coord.process(
                "1846.HK",
                wacc_path=wacc_path,  # type: ignore[arg-type]
                extraction_path=extraction_path,  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_cross_check_blocking_bypassed_with_skip(
        self, _setup: dict[str, object]
    ) -> None:
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        gate = _setup["gate"]  # type: ignore[index]
        gate.check = AsyncMock(return_value=_fail_report())

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            extraction_path=extraction_path,  # type: ignore[arg-type]
            skip_cross_check=True,
        )
        cc_stage = next(
            s for s in outcome.stages if s.stage == PipelineStage.CROSS_CHECK
        )
        assert cc_stage.status == "skip"
        gate.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_strict_validation_fail_blocks(
        self, _setup: dict[str, object], tmp_path: Path
    ) -> None:
        """When the extraction's IS or BS identity is broken, strict
        validation FAILs and raises :class:`ExtractionValidationBlocked`."""
        coord = _setup["coord"]  # type: ignore[index]
        wacc_path = _setup["wacc_path"]  # type: ignore[index]

        # Craft a broken extraction — BS identity wrong.
        broken = tmp_path / "broken_extraction.yaml"
        broken.write_text(
            """
metadata:
  ticker: "1846.HK"
  company_name: "Test"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  fiscal_year: 2024
  extraction_date: "2025-01-01"
  fiscal_periods:
    - period: "FY2024"
      end_date: "2024-12-31"
      is_primary: true
income_statement:
  FY2024:
    line_items:
      - {order: 1, label: "Revenue", value: "100"}
      - {order: 2, label: "Profit for the year", value: "10", is_subtotal: true}
balance_sheet:
  FY2024:
    line_items:
      - {order: 1, label: "Total assets", value: "500", section: "total_assets", is_subtotal: true}
      - {order: 2, label: "Total liabilities", value: "100", section: "total_liabilities", is_subtotal: true}
      - {order: 3, label: "Total equity", value: "100", section: "equity", is_subtotal: true}
""",
            encoding="utf-8",
        )
        with pytest.raises(ExtractionValidationBlocked, match="S.BS"):
            await coord.process(
                "1846.HK",
                wacc_path=wacc_path,  # type: ignore[arg-type]
                extraction_path=broken,
            )


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
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        original_cap = settings.llm_max_cost_per_company_usd

        observed: list[float] = []
        ec = _setup["extraction_coordinator"]  # type: ignore[index]
        original_ec = ec.extract_canonical

        async def spy(*a, **kw):  # type: ignore[no-untyped-def]
            observed.append(settings.llm_max_cost_per_company_usd)
            return await original_ec(*a, **kw)

        ec.extract_canonical = AsyncMock(side_effect=spy)

        await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            extraction_path=extraction_path,  # type: ignore[arg-type]
            force_cost_override=True,
        )
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
        extraction_path = _setup["extraction_path"]  # type: ignore[index]
        ec = _setup["extraction_coordinator"]  # type: ignore[index]

        # Break the canonical state's IS so guardrails FAIL.
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

        outcome = await coord.process(
            "1846.HK",
            wacc_path=wacc_path,  # type: ignore[arg-type]
            extraction_path=extraction_path,  # type: ignore[arg-type]
        )
        assert outcome.success is False
        assert outcome.overall_guardrail_status == GuardrailStatus.FAIL
