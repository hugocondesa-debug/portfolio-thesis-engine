"""End-to-end integration smoke for the Phase 1.5 pipeline.

Uses the EuroEyes ``raw_extraction.yaml`` fixture + mocked FMP /
yfinance cross-check providers. No LLM involvement anywhere —
extraction is the YAML file, modules are deterministic, valuation
is deterministic. This is the strongest in-suite regression test.

The test runs the full 11-stage Phase 1.5 pipeline and asserts:

- Every stage runs and records OK / skip (no failures).
- Extraction validation produces the expected strict/warn/completeness
  statuses.
- CanonicalCompanyState, ValuationSnapshot, and Ficha are persisted.
- Specific key analysis values (IC, NOPAT bridge, ratios, 3 scenarios)
  are coherent with the fixture.
- The pipeline's run log is written + readable.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.ficha import FichaComposer
from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.pipeline import PipelineCoordinator
from portfolio_thesis_engine.pipeline.coordinator import PipelineStage
from portfolio_thesis_engine.schemas.common import Currency, GuardrailStatus, Profile
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)
from portfolio_thesis_engine.valuation import (
    FCFFDCFEngine,
    ScenarioComposer,
    ValuationComposer,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "euroeyes"
_WACC_FIXTURE = Path(__file__).parent.parent / "fixtures" / "wacc" / "euroeyes_real.md"


# ----------------------------------------------------------------------
# Mocked market-data providers
# ----------------------------------------------------------------------
def _fake_providers() -> tuple[MagicMock, MagicMock]:
    """FMP + yfinance mocks returning values that match the EuroEyes
    AR 2024 fixture (Revenue 715.68M, NI 84.36M, Total Assets 3.75B
    — all in base units since the fixture's unit_scale was 'thousands'
    and the parser normalised)."""
    fmp = MagicMock()
    fmp.__aenter__ = AsyncMock(return_value=fmp)
    fmp.__aexit__ = AsyncMock(return_value=None)
    fmp.get_fundamentals = AsyncMock(
        return_value={
            "income_statement": [
                {
                    "revenue": 715_682_000,
                    "operatingIncome": 130_682_000,
                    "netIncome": 84_359_000,
                }
            ],
            "balance_sheet": [
                {
                    "totalAssets": 3_750_000_000,
                    "totalStockholdersEquity": 2_210_000_000,
                    "cashAndCashEquivalents": 550_000_000,
                }
            ],
            "cash_flow": [
                {
                    "operatingCashFlow": 145_000_000,
                    "capitalExpenditure": -120_000_000,
                }
            ],
        }
    )
    fmp.get_key_metrics = AsyncMock(
        return_value={
            "records": [
                {
                    "sharesOutstanding": 200_000_000,
                    "marketCap": 2_460_000_000,
                }
            ]
        }
    )
    fmp.get_quote = AsyncMock(
        return_value={
            "price": 12.30,
            "sharesOutstanding": 200_000_000,
            "marketCap": 2_460_000_000,
        }
    )

    yf = MagicMock()
    yf.get_fundamentals = AsyncMock(
        return_value={
            "income_statement": [
                {
                    "Total Revenue": 716_000_000,
                    "Operating Income": 131_000_000,
                    "Net Income": 84_000_000,
                }
            ],
            "balance_sheet": [
                {
                    "Total Assets": 3_745_000_000,
                    "Stockholders Equity": 2_205_000_000,
                    "Cash And Cash Equivalents": 548_000_000,
                }
            ],
            "cash_flow": [
                {
                    "Operating Cash Flow": 144_000_000,
                    "Capital Expenditure": -119_000_000,
                }
            ],
        }
    )
    yf.get_key_metrics = AsyncMock(
        return_value={
            "records": [
                {
                    "sharesOutstanding": 199_000_000,
                    "marketCap": 2_440_000_000,
                }
            ]
        }
    )
    return fmp, yf


# ----------------------------------------------------------------------
# Fixture
# ----------------------------------------------------------------------
@pytest.fixture
def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )

    # Copy fixtures to a simulated analyst workspace.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    extraction_path = workspace / "raw_extraction_ar_2024.yaml"
    wacc_path = workspace / "wacc_inputs.md"
    shutil.copyfile(_FIXTURE_DIR / "raw_extraction_ar_2024.yaml", extraction_path)
    shutil.copyfile(_WACC_FIXTURE, wacc_path)

    # Real ingestion: register the two files under 1846.HK.
    doc_repo = DocumentRepository()
    meta_repo = MetadataRepository()
    IngestionCoordinator(doc_repo, meta_repo).ingest(
        ticker="1846.HK",
        files=[extraction_path, wacc_path],
        mode="bulk_markdown",
        profile="P1",
    )

    # Build the pipeline components.
    cost_tracker = CostTracker(log_path=data_dir / "llm_costs.jsonl")
    # LLM is never called in the Phase 1.5 pipeline — pass a MagicMock
    # to satisfy the extraction_coordinator constructor signature.
    llm = MagicMock()
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=llm,
        cost_tracker=cost_tracker,
    )
    fmp, yf = _fake_providers()
    cross_check_gate = CrossCheckGate(fmp, yf, log_dir=data_dir / "logs" / "cross_check")
    state_repo = CompanyStateRepository(base_path=data_dir / "yamls" / "companies")
    valuation_repo = ValuationRepository(base_path=data_dir / "yamls" / "companies")
    company_repo = CompanyRepository(base_path=data_dir / "yamls" / "companies")

    pipeline = PipelineCoordinator(
        document_repo=doc_repo,
        metadata_repo=meta_repo,
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=state_repo,
        runs_log_dir=data_dir / "logs" / "runs",
        valuation_composer=ValuationComposer(),
        scenario_composer=ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5)),
        valuation_repo=valuation_repo,
        market_data_provider=fmp,
        ficha_composer=FichaComposer(),
        company_repo=company_repo,
    )
    return {
        "pipeline": pipeline,
        "wacc_path": wacc_path,
        "extraction_path": extraction_path,
        "state_repo": state_repo,
        "valuation_repo": valuation_repo,
        "company_repo": company_repo,
    }


# ----------------------------------------------------------------------
# The smoke
# ----------------------------------------------------------------------
class TestPhase1_5E2E:
    @pytest.mark.asyncio
    async def test_euroeyes_end_to_end_succeeds(
        self, _setup: dict[str, object]
    ) -> None:
        pipeline: PipelineCoordinator = _setup["pipeline"]  # type: ignore[assignment]
        wacc_path: Path = _setup["wacc_path"]  # type: ignore[assignment]
        extraction_path: Path = _setup["extraction_path"]  # type: ignore[assignment]
        state_repo: CompanyStateRepository = _setup["state_repo"]  # type: ignore[assignment]
        valuation_repo: ValuationRepository = _setup["valuation_repo"]  # type: ignore[assignment]
        company_repo: CompanyRepository = _setup["company_repo"]  # type: ignore[assignment]

        outcome = await pipeline.process(
            "1846.HK",
            wacc_path=wacc_path,
            extraction_path=extraction_path,
        )

        # Phase 1.5.10 — 12 stages (DECOMPOSE_NOTES added).
        assert len(outcome.stages) == 12
        stage_names = [s.stage for s in outcome.stages]
        assert stage_names == [
            PipelineStage.CHECK_INGESTION,
            PipelineStage.LOAD_WACC,
            PipelineStage.LOAD_EXTRACTION,
            PipelineStage.VALIDATE_EXTRACTION,
            PipelineStage.CROSS_CHECK,
            PipelineStage.DECOMPOSE_NOTES,
            PipelineStage.EXTRACT_CANONICAL,
            PipelineStage.PERSIST,
            PipelineStage.GUARDRAILS,
            PipelineStage.VALUATE,
            PipelineStage.PERSIST_VALUATION,
            PipelineStage.COMPOSE_FICHA,
        ]
        assert outcome.success is True

        # Extraction validation reports present.
        assert outcome.raw_extraction is not None
        assert outcome.extraction_validation_strict is not None
        assert outcome.extraction_validation_strict.overall_status == "OK"
        assert outcome.extraction_validation_warn is not None
        assert outcome.extraction_validation_completeness is not None

        # Guardrails overall PASS/WARN (never FAIL).
        assert outcome.overall_guardrail_status in (
            GuardrailStatus.PASS,
            GuardrailStatus.WARN,
            GuardrailStatus.SKIP,
        )

        # Canonical state persisted.
        state = state_repo.get("1846.HK")
        assert state is not None
        assert state.identity.ticker == "1846.HK"
        assert state.identity.reporting_currency == Currency.HKD
        assert state.methodology.protocols_activated == ["A", "B", "C"]
        assert state.methodology.extraction_system_version == "phase1.5.3"

        # Adjustments routed into correct buckets.
        # Module A.1 always produces an operating-tax-rate adjustment.
        assert len(state.adjustments.module_a_taxes) >= 1
        # Module C.3 lease additions adjustment.
        assert len(state.adjustments.module_c_leases) == 1
        # Module B.2.goodwill_impairment comes from notes.goodwill.impairment.
        b_modules = {adj.module for adj in state.adjustments.module_b_provisions}
        assert "B.2.goodwill_impairment" in b_modules

        # Analysis block: IC + NOPAT bridge + ratios present.
        assert len(state.analysis.invested_capital_by_period) == 1
        ic = state.analysis.invested_capital_by_period[0]
        # Operating assets + IC coherent (EuroEyes fixture in base units).
        assert ic.operating_assets > Decimal("0")
        assert ic.invested_capital > Decimal("0")

        bridge = state.analysis.nopat_bridge_by_period[0]
        assert bridge.ebitda > Decimal("0")
        assert bridge.nopat > Decimal("0")
        assert bridge.reported_net_income > Decimal("0")

        ratios = state.analysis.ratios_by_period[0]
        # Op margin 110/580 ≈ 18.97% — sanity-check it's in range.
        assert ratios.operating_margin is not None
        assert Decimal("15") < ratios.operating_margin < Decimal("25")

        # Reclassified statements carry every non-None typed field.
        # Phase 2 Sprint 2A — primary at [0] plus optional comparatives
        # appended when the raw extraction carries prior-period data.
        # EuroEyes AR 2024 fixture has FY2023 comparative → 2 entries.
        assert len(state.reclassified_statements) >= 1
        rs = state.reclassified_statements[0]
        assert rs.period.label == "FY2024"
        assert len(rs.income_statement) > 0
        assert len(rs.balance_sheet) > 0
        assert len(rs.cash_flow) > 0

        # Valuation snapshot persisted with 3 scenarios.
        snap = valuation_repo.get("1846.HK")
        assert snap is not None
        assert len(snap.scenarios) == 3
        labels = [sc.label for sc in snap.scenarios]
        assert labels == ["bear", "base", "bull"]
        # This test asserts pipeline wiring (all 11 stages run +
        # artefacts persist), not DCF output correctness. The fixture
        # has synthetic CapEx / D&A that produces negative FCFF under
        # Phase 1.5.8's correct arithmetic — that's a fixture-realism
        # artefact, not a pipeline bug. DCF output correctness is
        # covered by `tests/unit/test_dcf_engine.py` and the
        # `test_dcf_euroeyes_*` scenarios on the real production YAML.
        assert snap.weighted.expected_value is not None
        # Fair-value range is ordered.
        assert snap.weighted.fair_value_range_low <= snap.weighted.expected_value
        assert snap.weighted.expected_value <= snap.weighted.fair_value_range_high

        # Ficha persisted.
        ficha = company_repo.get("1846.HK")
        assert ficha is not None
        assert ficha.ticker == "1846.HK"
        assert ficha.current_extraction_id == state.extraction_id
        assert ficha.current_valuation_snapshot_id == snap.snapshot_id

        # Cross-check report recorded.
        assert outcome.cross_check_report is not None
        assert outcome.cross_check_report.blocking is False

        # Run log written + parseable.
        assert outcome.log_path is not None
        assert outcome.log_path.exists()
        log_lines = outcome.log_path.read_text(encoding="utf-8").strip().splitlines()
        stage_log_lines = [ln for ln in log_lines if '"type": "stage"' in ln]
        assert len(stage_log_lines) == 12
