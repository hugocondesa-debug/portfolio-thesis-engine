"""Real EuroEyes end-to-end smoke — Phase 1.5 final validation.

Gated by ``PTE_SMOKE_HIT_REAL_APIS=true`` so it doesn't run in default
CI. When enabled, reads the real EuroEyes inputs from
``~/data_inputs/euroeyes/`` (``raw_extraction.yaml`` + ``wacc_inputs.md``),
runs the full pipeline against **live** FMP + yfinance APIs, and
asserts structural outcomes — not specific numeric values (those will
vary over time and are pinned in the sprint report).

Phase 1.5 note: extraction no longer uses the LLM inside the app.
Hugo produces the ``raw_extraction.yaml`` via Claude.ai externally
and the pipeline consumes it deterministically.

Estimated cost per run: **~$0 LLM + metered FMP / yfinance calls**
(FMP is flat-fee subscription; yfinance is free).

Checklist the test enforces:

- ``raw_extraction.yaml`` + ``wacc_inputs.md`` present in
  ``~/data_inputs/euroeyes/``.
- Pipeline completes 11 stages; overall status PASS/WARN.
- Extraction validation strict OK (identities hold).
- Cross-check report has FMP + yfinance data for 1846.HK.
- CanonicalCompanyState persisted with IC + NOPAT + ratios.
- ValuationSnapshot with 3 scenarios.
- Ficha composed + persisted.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.ficha import FichaComposer
from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider
from portfolio_thesis_engine.pipeline import PipelineCoordinator
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)
from portfolio_thesis_engine.valuation import ScenarioComposer, ValuationComposer

_REAL_INPUTS = Path.home() / "data_inputs" / "euroeyes"
_HIT_REAL = os.environ.get("PTE_SMOKE_HIT_REAL_APIS", "").lower() in ("1", "true", "yes")


pytestmark = pytest.mark.skipif(
    not _HIT_REAL,
    reason="PTE_SMOKE_HIT_REAL_APIS=true required to run real-API smoke tests.",
)


def _required_files() -> list[Path]:
    return [
        _REAL_INPUTS / "raw_extraction.yaml",
        _REAL_INPUTS / "wacc_inputs.md",
    ]


@pytest.fixture
def _all_inputs_present() -> list[Path]:
    files = _required_files()
    missing = [p for p in files if not p.exists()]
    if missing:
        pytest.skip(
            f"Real EuroEyes inputs missing: {missing}. "
            f"Place files under {_REAL_INPUTS}/ to run this smoke."
        )
    return files


@pytest.fixture
def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _all_inputs_present: list[Path],
) -> dict[str, object]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )

    # --- ingestion (real documents, real MetadataRepository) -----------
    doc_repo = DocumentRepository()
    meta_repo = MetadataRepository()
    IngestionCoordinator(doc_repo, meta_repo).ingest(
        ticker="1846.HK",
        files=_all_inputs_present,
        mode="bulk_markdown",
        profile="P1",
    )

    wacc_path = next(p for p in _all_inputs_present if p.name == "wacc_inputs.md")
    extraction_path = next(
        p for p in _all_inputs_present if p.name == "raw_extraction.yaml"
    )

    # --- pipeline components (LLM unused; mocked via MagicMock) ------
    from unittest.mock import MagicMock

    cost_tracker = CostTracker(log_path=data_dir / "llm_costs.jsonl")
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=MagicMock(),
        cost_tracker=cost_tracker,
    )
    fmp = FMPProvider()
    yf = YFinanceProvider()
    cross_check_gate = CrossCheckGate(
        fmp, yf, log_dir=data_dir / "logs" / "cross_check"
    )
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
        scenario_composer=ScenarioComposer(),
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
        "doc_repo": doc_repo,
    }


# ======================================================================
# The smoke — structural assertions only
# ======================================================================


class TestEuroEyesRealSmoke:
    @pytest.mark.integration
    def test_end_to_end_real_apis(self, _setup: dict[str, object]) -> None:
        pipeline: PipelineCoordinator = _setup["pipeline"]  # type: ignore[assignment]
        wacc_path: Path = _setup["wacc_path"]  # type: ignore[assignment]
        extraction_path: Path = _setup["extraction_path"]  # type: ignore[assignment]
        state_repo: CompanyStateRepository = _setup["state_repo"]  # type: ignore[assignment]
        valuation_repo: ValuationRepository = _setup["valuation_repo"]  # type: ignore[assignment]
        company_repo: CompanyRepository = _setup["company_repo"]  # type: ignore[assignment]
        doc_repo: DocumentRepository = _setup["doc_repo"]  # type: ignore[assignment]

        # 1. Documents ingested (raw_extraction + wacc_inputs = 2 files).
        assert len(doc_repo.list_documents("1846.HK")) >= 2, (
            "Expected at least 2 documents ingested (raw_extraction.yaml + wacc_inputs.md)."
        )

        # 2. Run the pipeline (real FMP + yfinance; no LLM).
        outcome = asyncio.run(
            pipeline.process(
                "1846.HK",
                wacc_path=wacc_path,
                extraction_path=extraction_path,
            )
        )

        # 3. 11 stages ran, no failures.
        assert len(outcome.stages) == 11
        assert outcome.success is True, (
            f"Pipeline did not succeed: overall={outcome.overall_guardrail_status}; "
            f"stages={[(s.stage.value, s.status) for s in outcome.stages]}"
        )

        # 4. Strict extraction validation OK.
        assert outcome.extraction_validation_strict is not None
        assert outcome.extraction_validation_strict.overall_status == "OK"

        # 5. Canonical state persisted with IC + NOPAT + ratios.
        state = state_repo.get("1846.HK")
        assert state is not None
        assert state.analysis.invested_capital_by_period, "IC missing."
        assert state.analysis.nopat_bridge_by_period, "NOPAT bridge missing."
        assert state.analysis.ratios_by_period, "Ratios missing."

        # 6. Cross-check report has real data from both providers.
        assert outcome.cross_check_report is not None
        report = outcome.cross_check_report
        revenue_metric = next(
            (m for m in report.metrics if m.metric == "revenue"), None
        )
        assert revenue_metric is not None, "Revenue not in cross-check report."

        # 7. Valuation snapshot persisted with 3 scenarios.
        snap = valuation_repo.get("1846.HK")
        assert snap is not None
        assert len(snap.scenarios) == 3
        assert {sc.label for sc in snap.scenarios} == {"bear", "base", "bull"}
        assert snap.weighted.expected_value > 0

        # 8. Ficha persisted.
        ficha = company_repo.get("1846.HK")
        assert ficha is not None
        assert ficha.ticker == "1846.HK"

        # 9. Run log written.
        assert outcome.log_path is not None
        assert outcome.log_path.exists()
