"""Phase 1.5.13.3 regression tests — audit-status auto-derivation at
the Pydantic schema layer.

Ensures that :class:`DocumentMetadata` applies the same 3-tier audit-
status resolution the coordinator selector does, so interim /
preliminary YAMLs without top-level ``audit_status`` arrive at the
pipeline with the correct enum value (and subsequently trigger the
cross-check skip introduced in Phase 1.5.11 / 1.5.13.2).

Tests (7):

Schema-level 3-tier (4):
- ``test_interim_yaml_without_top_level_resolves_to_reviewed``
- ``test_preliminary_yaml_resolves_to_unaudited``
- ``test_investor_presentation_resolves_to_unaudited``
- ``test_per_period_audit_status_overrides_document_type_default``

Schema explicit override (1):
- ``test_explicit_top_level_audit_status_wins_over_type_default``

Cross-check integration (2):
- ``test_cross_check_skip_message_differs_for_reviewed_vs_unaudited``
- ``test_cross_check_runs_for_audited_document``
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.pipeline.coordinator import (
    PipelineCoordinator,
    PipelineOutcome,
    PipelineStage,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    RawExtraction,
    audit_status_for_document_type,
)

from .conftest import build_raw


def _payload_without_top_level_audit(
    *, document_type: str, period: str, per_period_audit: str | None = None
) -> dict:
    """Build a RawExtraction payload that does NOT set
    ``metadata.audit_status`` at top level — mirrors real-world Claude.ai
    output for interim / preliminary docs."""
    period_entry = {
        "period": period,
        "end_date": "2025-12-31",
        "is_primary": True,
    }
    if per_period_audit is not None:
        period_entry["audit_status"] = per_period_audit
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test Co",
            "document_type": document_type,
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [period_entry],
            # NOTE: no top-level audit_status.
        },
        "income_statement": {
            period: {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "1000"},
                ]
            }
        },
        "balance_sheet": {
            period: {
                "line_items": [
                    {
                        "order": 1,
                        "label": "Total assets",
                        "value": "1000",
                        "section": "total_assets",
                        "is_subtotal": True,
                    },
                ]
            }
        },
    }


# ======================================================================
# Schema-level 3-tier resolution
# ======================================================================


class TestSchemaAuditDerivation:
    def test_interim_yaml_without_top_level_resolves_to_reviewed(self) -> None:
        payload = _payload_without_top_level_audit(
            document_type="interim_report", period="H1_2025"
        )
        raw = RawExtraction.model_validate(payload)
        # The 3-tier validator should downgrade default AUDITED to
        # REVIEWED based on document_type.
        assert raw.metadata.audit_status == AuditStatus.REVIEWED

    def test_preliminary_yaml_resolves_to_unaudited(self) -> None:
        payload = _payload_without_top_level_audit(
            document_type="preliminary_results", period="FY2025"
        )
        raw = RawExtraction.model_validate(payload)
        assert raw.metadata.audit_status == AuditStatus.UNAUDITED

    def test_investor_presentation_resolves_to_unaudited(self) -> None:
        payload = _payload_without_top_level_audit(
            document_type="investor_presentation", period="FY2025"
        )
        raw = RawExtraction.model_validate(payload)
        assert raw.metadata.audit_status == AuditStatus.UNAUDITED

    def test_per_period_audit_status_overrides_document_type_default(
        self,
    ) -> None:
        """Per-period ``audit_status`` on the primary fiscal period
        wins over the document-type default."""
        payload = _payload_without_top_level_audit(
            document_type="annual_report",  # default would be 'audited'
            period="FY2025",
            per_period_audit="unaudited",  # but primary period says otherwise
        )
        raw = RawExtraction.model_validate(payload)
        assert raw.metadata.audit_status == AuditStatus.UNAUDITED


class TestSchemaExplicitOverride:
    def test_explicit_top_level_audit_status_wins_over_type_default(
        self,
    ) -> None:
        """Top-level explicit ``audit_status`` always wins — a
        restated-but-still-unaudited annual report stays unaudited even
        though the document_type default would be 'audited'."""
        payload = _payload_without_top_level_audit(
            document_type="annual_report", period="FY2025"
        )
        payload["metadata"]["audit_status"] = "unaudited"
        raw = RawExtraction.model_validate(payload)
        assert raw.metadata.audit_status == AuditStatus.UNAUDITED

    def test_audit_status_for_document_type_maps_correctly(self) -> None:
        assert audit_status_for_document_type("annual_report") == "audited"
        assert audit_status_for_document_type("interim_report") == "reviewed"
        assert audit_status_for_document_type("investor_presentation") == "unaudited"
        assert audit_status_for_document_type("unknown_type") == "audited"


# ======================================================================
# Cross-check integration
# ======================================================================


class TestCrossCheckSkipMessages:
    @pytest.mark.asyncio
    async def test_cross_check_skip_message_differs_for_reviewed_vs_unaudited(
        self,
    ) -> None:
        """Both REVIEWED and UNAUDITED skip the cross-check, but the
        stage message identifies the audit status explicitly so the
        log is self-documenting."""
        coord = PipelineCoordinator(
            document_repo=MagicMock(),
            metadata_repo=MagicMock(),
            cross_check_gate=MagicMock(),
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        # REVIEWED branch.
        raw_reviewed = build_raw(
            audit_status="reviewed", document_type="interim_report"
        )
        outcome_r = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        await coord._stage_cross_check(
            ticker="TST",
            raw_extraction=raw_reviewed,
            outcome=outcome_r,
            skip_cross_check=False,
        )
        assert outcome_r.stages[-1].stage == PipelineStage.CROSS_CHECK
        assert outcome_r.stages[-1].status == "skip"
        assert "reviewed" in outcome_r.stages[-1].message.lower()

        # UNAUDITED branch.
        raw_unaudited = build_raw(
            audit_status="unaudited", document_type="preliminary_results"
        )
        outcome_u = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        await coord._stage_cross_check(
            ticker="TST",
            raw_extraction=raw_unaudited,
            outcome=outcome_u,
            skip_cross_check=False,
        )
        assert outcome_u.stages[-1].status == "skip"
        assert "unaudited" in outcome_u.stages[-1].message.lower()
        # And the messages are not identical — each names its own status.
        assert (
            outcome_r.stages[-1].message != outcome_u.stages[-1].message
        )

    @pytest.mark.asyncio
    async def test_cross_check_runs_for_audited_document(self) -> None:
        """Regression: audited documents must still invoke the cross-
        check gate (non-skip path)."""
        from portfolio_thesis_engine.cross_check.base import (
            CrossCheckReport,
            CrossCheckStatus,
        )

        fake_report = CrossCheckReport(
            ticker="TST",
            period="FY2024",
            metrics=[],
            overall_status=CrossCheckStatus.PASS,
            blocking=False,
            generated_at=datetime.now(UTC),
        )
        gate = MagicMock()

        async def _check(**_kwargs: object) -> CrossCheckReport:
            return fake_report

        gate.check = _check
        coord = PipelineCoordinator(
            document_repo=MagicMock(),
            metadata_repo=MagicMock(),
            cross_check_gate=gate,
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        raw_audited = build_raw(
            audit_status="audited", document_type="annual_report"
        )
        outcome = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        result = await coord._stage_cross_check(
            ticker="TST",
            raw_extraction=raw_audited,
            outcome=outcome,
            skip_cross_check=False,
        )
        # Gate actually ran and returned the report.
        assert result is fake_report
        assert outcome.stages[-1].status == "ok"
