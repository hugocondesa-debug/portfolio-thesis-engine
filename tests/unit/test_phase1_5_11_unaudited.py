"""Phase 1.5.11 regression tests — unaudited / preliminary results
support. 10 tests per the 1.5.11 scope doc:

Schema (2):
- ``test_document_type_preliminary_results``
- ``test_audit_status_enum``

Validator (1):
- ``test_validation_relaxed_for_unaudited_missing_notes``

Pipeline (2):
- ``test_cross_check_skipped_for_unaudited``
- ``test_module_a_statutory_fallback_preliminary``

Confidence + display (2):
- ``test_confidence_downgrade_for_unaudited``
- ``test_display_banner_shown_for_unaudited``

--base-period CLI (3):
- ``test_base_period_auto_selects_latest``
- ``test_base_period_latest_audited_skips_unaudited``
- ``test_base_period_explicit_period_selection``
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.coordinator import (
    ExtractionCoordinator,
    _confidence_for_audit_status,
)
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    Profile,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    CanonicalCompanyState,
    CompanyIdentity,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    ModuleAdjustment,
    NOPATBridge,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    DocumentType,
)

from .conftest import build_raw, make_context


# ======================================================================
# Schema (2 tests)
# ======================================================================


class TestSchema:
    def test_document_type_preliminary_results(self) -> None:
        """PRELIMINARY_RESULTS is accepted by DocumentType enum."""
        assert DocumentType.PRELIMINARY_RESULTS.value == "preliminary_results"
        # Backward compat: older preliminary_announcement still exists.
        assert DocumentType.PRELIMINARY_ANNOUNCEMENT.value == "preliminary_announcement"

    def test_audit_status_enum(self) -> None:
        """AuditStatus enum exposes audited / reviewed / unaudited."""
        assert AuditStatus.AUDITED.value == "audited"
        assert AuditStatus.REVIEWED.value == "reviewed"
        assert AuditStatus.UNAUDITED.value == "unaudited"


# ======================================================================
# Validator (1 test)
# ======================================================================


class TestValidatorRelaxation:
    def test_validation_relaxed_for_unaudited_missing_notes(self) -> None:
        """Required notes missing → FAIL for audited, WARN for unaudited."""
        from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
            ExtractionValidator,
        )

        # Build a minimal RawExtraction with notes absent — required
        # completeness checks will fire (profile=P1 has required notes).
        # Swap audit_status and confirm FAIL→WARN demotion.
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Operating profit", "value": "200",
             "is_subtotal": True},
            {"order": 3, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]

        raw_audited = build_raw(is_lines=is_lines, audit_status="audited")
        audited_report = ExtractionValidator().validate_completeness(
            raw_audited, Profile.P1_INDUSTRIAL
        )
        audited_statuses = {r.status for r in audited_report.results if
                            r.check_id.startswith("C.R.")}
        # Required notes missing for audited → at least one FAIL.
        assert "FAIL" in audited_statuses

        raw_unaudited = build_raw(
            is_lines=is_lines,
            audit_status="unaudited",
            document_type="preliminary_results",
        )
        unaudited_report = ExtractionValidator().validate_completeness(
            raw_unaudited, Profile.P1_INDUSTRIAL
        )
        unaudited_statuses = {
            r.status for r in unaudited_report.results
            if r.check_id.startswith("C.R.")
        }
        # Required notes missing for unaudited → WARN, never FAIL.
        assert "FAIL" not in unaudited_statuses
        assert "WARN" in unaudited_statuses


# ======================================================================
# Pipeline cross-check + Module A (2 tests)
# ======================================================================


class TestPipelineUnauditedBehavior:
    @pytest.mark.asyncio
    async def test_cross_check_skipped_for_unaudited(self) -> None:
        """Pipeline cross_check stage returns SKIP (not WARN / FAIL)
        when audit_status=UNAUDITED — external sources won't have the
        data yet."""
        from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
        from portfolio_thesis_engine.pipeline.coordinator import (
            PipelineCoordinator,
            PipelineOutcome,
            PipelineStage,
        )

        raw = build_raw(audit_status="unaudited")
        # Stub coordinator: gate would reject real data but shouldn't
        # be called. Assert by making gate.check raise if invoked.
        gate = MagicMock(spec=CrossCheckGate)
        gate.check = MagicMock(
            side_effect=AssertionError("gate should not be called")
        )

        outcome = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        coord = PipelineCoordinator(
            document_repo=MagicMock(),
            metadata_repo=MagicMock(),
            cross_check_gate=gate,
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        result = await coord._stage_cross_check(
            ticker="TST",
            raw_extraction=raw,
            outcome=outcome,
            skip_cross_check=False,
        )
        assert result is None
        stage = outcome.stages[-1]
        assert stage.stage == PipelineStage.CROSS_CHECK
        assert stage.status == "skip"
        assert "unaudited" in stage.message.lower()

    def test_module_a_statutory_fallback_preliminary(
        self, wacc_inputs
    ) -> None:
        """Module A statutory fallback under unaudited source logs an
        additional message about the preliminary provenance."""
        from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes

        raw = build_raw(audit_status="unaudited")
        ctx = make_context(raw, wacc_inputs)
        # No tax facts → will fall back to statutory.
        module = ModuleATaxes(
            llm=MagicMock(),
            cost_tracker=CostTracker(log_path=Path("/tmp/t_1511.jsonl")),
        )
        module._fallback_to_statutory(ctx, reason="no tax note found")
        combined_logs = " ".join(ctx.estimates_log)
        assert "statutory" in combined_logs.lower()
        assert "unaudited" in combined_logs.lower()


# ======================================================================
# Confidence + display (2 tests)
# ======================================================================


class TestConfidenceAndDisplay:
    def test_confidence_downgrade_for_unaudited(self) -> None:
        """``_confidence_for_audit_status`` caps MEDIUM-LOW for UNAUDITED."""
        assert _confidence_for_audit_status(AuditStatus.AUDITED) == "MEDIUM"
        assert _confidence_for_audit_status(AuditStatus.REVIEWED) == "MEDIUM"
        assert _confidence_for_audit_status(AuditStatus.UNAUDITED) == "MEDIUM-LOW"

    def test_display_banner_shown_for_unaudited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``pte show`` renders the unaudited banner at top of output."""
        from portfolio_thesis_engine.cli import show_cmd
        from portfolio_thesis_engine.ficha import FichaBundle

        period = FiscalPeriod(year=2025, label="FY2025")
        state = CanonicalCompanyState(
            extraction_id="ext1",
            extraction_date=datetime(2026, 3, 15, tzinfo=UTC),
            as_of_date="2025-12-31",
            identity=CompanyIdentity(
                ticker="TST",
                name="Test Co",
                reporting_currency=Currency.USD,
                profile=Profile.P1_INDUSTRIAL,
                fiscal_year_end_month=12,
                country_domicile="US",
                exchange="NYSE",
            ),
            reclassified_statements=[],
            adjustments=AdjustmentsApplied(),
            analysis=AnalysisDerived(
                invested_capital_by_period=[
                    InvestedCapital(
                        period=period,
                        operating_assets=Decimal("0"),
                        operating_liabilities=Decimal("0"),
                        invested_capital=Decimal("0"),
                        financial_assets=Decimal("0"),
                        financial_liabilities=Decimal("0"),
                        equity_claims=Decimal("0"),
                        cross_check_residual=Decimal("0"),
                    )
                ],
                nopat_bridge_by_period=[
                    NOPATBridge(
                        period=period,
                        ebitda=Decimal("0"),
                        operating_taxes=Decimal("0"),
                        nopat=Decimal("0"),
                        financial_income=Decimal("0"),
                        financial_expense=Decimal("0"),
                        non_operating_items=Decimal("0"),
                        reported_net_income=Decimal("0"),
                    )
                ],
                ratios_by_period=[KeyRatios(period=period)],
            ),
            validation=ValidationResults(
                universal_checksums=[
                    ValidationResult(
                        check_id="V.0", name="s", status="PASS", detail="ok"
                    )
                ],
                profile_specific_checksums=[],
                confidence_rating="MEDIUM-LOW",
            ),
            vintage=VintageAndCascade(),
            methodology=MethodologyMetadata(
                extraction_system_version="test",
                profile_applied=Profile.P1_INDUSTRIAL,
                protocols_activated=[],
                audit_status="unaudited",
                preliminary_flag={
                    "pending_audit": True,
                    "expected_audit_date": "2026-06-30",
                    "source_document": "Investor presentation 2026-03-15",
                    "caveat_text": "Pre-audit preliminary figures.",
                },
                source_document_type="preliminary_results",
            ),
        )

        bundle = FichaBundle(
            ticker="TST",
            canonical_state=state,
            valuation_snapshot=None,
            ficha=None,
        )

        buf = io.StringIO()
        test_console = Console(file=buf, width=200, record=True)
        monkeypatch.setattr(show_cmd, "console", test_console)
        show_cmd._render_rich(bundle)
        rendered = buf.getvalue()
        assert "UNAUDITED" in rendered
        assert "Investor presentation 2026-03-15" in rendered
        assert "MEDIUM-LOW" in rendered
        # Identity table shows audit status row.
        assert "Audit status" in rendered


# ======================================================================
# --base-period CLI (3 tests)
# ======================================================================


class TestBasePeriodCLI:
    def _write_raw_yaml(
        self, path: Path, audit: str, period: str = "FY2024"
    ) -> None:
        path.write_text(
            f"""metadata:
  ticker: TST
  company_name: Test Co
  document_type: annual_report
  extraction_type: numeric
  reporting_currency: USD
  unit_scale: units
  extraction_date: "2025-01-01"
  audit_status: {audit}
  fiscal_periods:
    - period: {period}
      end_date: "2024-12-31"
      is_primary: true
income_statement:
  {period}:
    line_items:
      - order: 1
        label: Revenue
        value: '1000'
balance_sheet:
  {period}:
    line_items:
      - order: 1
        label: Total assets
        value: '1000'
        section: total_assets
        is_subtotal: true
""",
            encoding="utf-8",
        )

    def test_base_period_auto_selects_latest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AUTO picks the latest (most-recent mtime) candidate."""
        from portfolio_thesis_engine.cli import process_cmd

        data_dir = tmp_path / "TST"
        data_dir.mkdir()
        older = data_dir / "raw_extraction_ar_2024.yaml"
        newer = data_dir / "raw_extraction_preliminary_fy2025.yaml"
        self._write_raw_yaml(older, "audited", period="FY2024")
        self._write_raw_yaml(newer, "unaudited", period="FY2025-preliminary")
        # Bump mtimes so 'newer' actually looks newer.
        import os
        import time

        old_time = time.time() - 1000
        os.utime(older, (old_time, old_time))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # But data_inputs layout expects tmp_path/data_inputs/TST/.
        (tmp_path / "data_inputs").mkdir(exist_ok=True)
        target_dir = tmp_path / "data_inputs" / "TST"
        target_dir.mkdir(exist_ok=True)
        (target_dir / older.name).write_bytes(older.read_bytes())
        (target_dir / newer.name).write_bytes(newer.read_bytes())
        # Preserve mtime relationship.
        os.utime(target_dir / older.name, (old_time, old_time))

        monkeypatch.setattr(
            process_cmd, "DocumentRepository", lambda *a, **k: MagicMock(
                list_documents=lambda ticker: []
            )
        )
        resolved = process_cmd._select_extraction_by_base_period(
            "TST", None, process_cmd._BASE_PERIOD_AUTO
        )
        assert resolved.name == "raw_extraction_preliminary_fy2025.yaml"

    def test_base_period_latest_audited_skips_unaudited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LATEST-AUDITED skips unaudited files even when they're newer."""
        from portfolio_thesis_engine.cli import process_cmd

        (tmp_path / "data_inputs" / "TST").mkdir(parents=True)
        target_dir = tmp_path / "data_inputs" / "TST"
        audited = target_dir / "raw_extraction_ar_2024.yaml"
        unaudited = target_dir / "raw_extraction_preliminary_fy2025.yaml"
        self._write_raw_yaml(audited, "audited", period="FY2024")
        self._write_raw_yaml(unaudited, "unaudited", period="FY2025-preliminary")
        # Unaudited is newer by mtime.
        import os
        import time

        old = time.time() - 1000
        os.utime(audited, (old, old))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(
            process_cmd, "DocumentRepository", lambda *a, **k: MagicMock(
                list_documents=lambda ticker: []
            )
        )
        resolved = process_cmd._select_extraction_by_base_period(
            "TST", None, process_cmd._BASE_PERIOD_LATEST_AUDITED
        )
        # Must skip the unaudited file and pick the audited one.
        assert resolved.name == "raw_extraction_ar_2024.yaml"

    def test_base_period_explicit_period_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit period label matches on filename stem OR primary
        period."""
        from portfolio_thesis_engine.cli import process_cmd

        target_dir = tmp_path / "data_inputs" / "TST"
        target_dir.mkdir(parents=True)
        a = target_dir / "raw_extraction_ar_2024.yaml"
        b = target_dir / "raw_extraction_preliminary_fy2025.yaml"
        self._write_raw_yaml(a, "audited", period="FY2024")
        self._write_raw_yaml(b, "unaudited", period="FY2025-preliminary")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(
            process_cmd, "DocumentRepository", lambda *a, **k: MagicMock(
                list_documents=lambda ticker: []
            )
        )
        resolved = process_cmd._select_extraction_by_base_period(
            "TST", None, "FY2024"
        )
        assert resolved.name == "raw_extraction_ar_2024.yaml"
        resolved2 = process_cmd._select_extraction_by_base_period(
            "TST", None, "FY2025-preliminary"
        )
        assert resolved2.name == "raw_extraction_preliminary_fy2025.yaml"
