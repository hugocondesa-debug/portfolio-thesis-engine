"""Phase 1.5.12.1 regression tests — gaps revealed by first real-world
extraction testing (EuroEyes interim H1 2025 + preliminary FY2025).

12 tests:

Note source_pages (1):
- ``test_note_source_pages_none_becomes_empty_list``

SegmentMeta (3):
- ``test_segment_meta_accepts_extra_fields``
- ``test_segments_identified_int_becomes_empty_list``
- ``test_segments_identified_none_becomes_empty_list``

OperationalKPIsBlock.metric_sources (3):
- ``test_metric_sources_list_value_accepted``
- ``test_metric_sources_mixed_values_accepted``
- ``test_metric_sources_invalid_value_rejected``

Structural relaxation for unaudited (5):
- ``test_unaudited_primary_missing_bs_allowed``
- ``test_unaudited_primary_missing_cf_allowed``
- ``test_unaudited_primary_missing_is_rejected``
- ``test_audited_primary_missing_bs_rejected``
- ``test_reviewed_primary_missing_bs_rejected``
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    Note,
    OperationalKPIsBlock,
    RawExtraction,
    SegmentMeta,
)


# ======================================================================
# Note.source_pages
# ======================================================================


class TestNoteSourcePages:
    def test_note_source_pages_none_becomes_empty_list(self) -> None:
        """Synthesized absence notes carry ``source_pages: None``."""
        note = Note(title="Inferred absence note", source_pages=None)
        assert note.source_pages == []


# ======================================================================
# SegmentMeta
# ======================================================================


class TestSegmentMeta:
    def test_segment_meta_accepts_extra_fields(self) -> None:
        """Issuer-specific meta fields survive (extra='allow')."""
        meta = SegmentMeta(
            reporting_basis="IFRS 8",
            segments_identified=["Germany", "China"],
            codm="CFO",
            operating_profit_by_segment_disclosed=False,  # extra
            rationale_no_op_profit="Not disclosed at segment level",  # extra
        )
        assert meta.reporting_basis == "IFRS 8"
        # Extras accessible via model_dump.
        dump = meta.model_dump()
        assert dump["operating_profit_by_segment_disclosed"] is False
        assert "rationale_no_op_profit" in dump

    def test_segments_identified_int_becomes_empty_list(self) -> None:
        """Extractor sometimes emits a count instead of a list — we
        treat the count as insufficient info and coerce to []."""
        meta = SegmentMeta(segments_identified=4)
        assert meta.segments_identified == []

    def test_segments_identified_none_becomes_empty_list(self) -> None:
        meta = SegmentMeta(segments_identified=None)
        assert meta.segments_identified == []


# ======================================================================
# OperationalKPIsBlock.metric_sources
# ======================================================================


class TestOperationalKPIsMetricSources:
    def test_metric_sources_list_value_accepted(self) -> None:
        """Real EuroEyes extractor: primary_notes: ["6", "7", "13"]."""
        block = OperationalKPIsBlock(
            metrics={},
            metric_sources={
                "primary_notes": ["6", "7", "8", "13", "14"],
                "primary_sections": ["MD&A", "Highlights"],
            },
        )
        assert block.metric_sources["primary_notes"] == [
            "6", "7", "8", "13", "14"
        ]
        assert block.metric_sources["primary_sections"] == ["MD&A", "Highlights"]

    def test_metric_sources_mixed_values_accepted(self) -> None:
        block = OperationalKPIsBlock(
            metrics={},
            metric_sources={
                "total_clinics": "MD&A §2",  # str
                "revenue_by_segment": ["Note 3", "Note 4"],  # list
            },
        )
        assert block.metric_sources["total_clinics"] == "MD&A §2"
        assert block.metric_sources["revenue_by_segment"] == ["Note 3", "Note 4"]

    def test_metric_sources_invalid_value_rejected(self) -> None:
        with pytest.raises(
            (ValidationError, ValueError), match="must be str or list"
        ):
            OperationalKPIsBlock(
                metrics={},
                metric_sources={"bad": 42},  # int not allowed
            )


# ======================================================================
# Structural relaxation for unaudited
# ======================================================================


def _base_payload(
    audit_status: str = "audited",
    document_type: str = "annual_report",
    include_bs: bool = True,
    include_cf: bool = True,
    include_is: bool = True,
) -> dict:
    payload: dict = {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test Co",
            "document_type": document_type,
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2025", "end_date": "2025-12-31", "is_primary": True}
            ],
            "audit_status": audit_status,
        },
    }
    if include_is:
        payload["income_statement"] = {
            "FY2025": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "1000"},
                    {
                        "order": 2, "label": "Operating profit",
                        "value": "200", "is_subtotal": True,
                    },
                    {
                        "order": 3, "label": "Profit for the year",
                        "value": "140", "is_subtotal": True,
                    },
                ]
            }
        }
    if include_bs:
        payload["balance_sheet"] = {
            "FY2025": {
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
        }
    if include_cf:
        payload["cash_flow"] = {
            "FY2025": {
                "line_items": [
                    {
                        "order": 1,
                        "label": "Net change in cash",
                        "value": "50",
                        "section": "subtotal",
                        "is_subtotal": True,
                    },
                ]
            }
        }
    return payload


class TestUnauditedStructuralRelaxation:
    def test_unaudited_primary_missing_bs_allowed(self) -> None:
        payload = _base_payload(
            audit_status="unaudited",
            document_type="preliminary_results",
            include_bs=False,
        )
        raw = RawExtraction.model_validate(payload)
        assert raw.metadata.audit_status == AuditStatus.UNAUDITED
        assert "FY2025" not in raw.balance_sheet

    def test_unaudited_primary_missing_cf_allowed(self) -> None:
        payload = _base_payload(
            audit_status="unaudited",
            document_type="preliminary_results",
            include_cf=False,
        )
        raw = RawExtraction.model_validate(payload)
        assert "FY2025" not in raw.cash_flow

    def test_unaudited_primary_missing_is_rejected(self) -> None:
        """IS is always required — core waterfall arithmetic depends
        on it regardless of audit status."""
        payload = _base_payload(
            audit_status="unaudited",
            document_type="preliminary_results",
            include_is=False,
        )
        with pytest.raises(
            ValidationError, match="has no income_statement"
        ):
            RawExtraction.model_validate(payload)

    def test_audited_primary_missing_bs_rejected(self) -> None:
        payload = _base_payload(audit_status="audited", include_bs=False)
        with pytest.raises(
            ValidationError, match="has no balance_sheet"
        ):
            RawExtraction.model_validate(payload)

    def test_reviewed_primary_missing_bs_rejected(self) -> None:
        """REVIEWED (auditor-reviewed interims) still requires BS —
        relaxation is UNAUDITED-only."""
        payload = _base_payload(
            audit_status="reviewed",
            document_type="interim_report",
            include_bs=False,
        )
        with pytest.raises(
            ValidationError, match="has no balance_sheet"
        ):
            RawExtraction.model_validate(payload)
