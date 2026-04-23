"""Phase 1.5.12 regression tests — narrative structured types,
metadata flexibility, segments + KPI blocks, note/EPS adjustments,
display adaptations.

21 tests per the 1.5.12 scope.

Narrative backward-compat (7):
- ``test_narrative_item_plain_str_backward_compat``
- ``test_narrative_item_structured_dict_loaded``
- ``test_risk_item_plain_str_backward_compat``
- ``test_risk_item_structured_loaded``
- ``test_guidance_item_legacy_dict_without_metric_field``
- ``test_guidance_item_structured_with_metric``
- ``test_capital_allocation_item_backward_compat``

Metadata flexibility (3):
- ``test_audit_status_case_insensitive``
- ``test_preliminary_flag_false_becomes_none``
- ``test_preliminary_flag_true_rejected_without_details``

Segments / KPI blocks (4):
- ``test_segments_dict_to_block``
- ``test_segments_list_legacy_compat``
- ``test_operational_kpis_dict_to_block``
- ``test_operational_kpis_list_legacy_compat``

Notes / EPS (3):
- ``test_note_source_pages_int_wrapped_to_list``
- ``test_note_source_pages_list_passes_through``
- ``test_eps_source_note_accepted``

Display (3):
- ``test_display_narrative_structured_renders_source_attribution``
- ``test_display_narrative_plain_str_renders_as_bullet``
- ``test_display_segments_block_renders_as_table``

EuroEyes AR 2024 regression (1 smoke — existing fixture still validates):
- ``test_euroeyes_ar_2024_still_validates``
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.cli import show_cmd
from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
    parse_raw_extraction,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    CapitalAllocationItem,
    DocumentMetadata,
    DocumentType,
    EarningsPerShare,
    ExtractionType,
    GuidanceItem,
    NarrativeContent,
    NarrativeItem,
    Note,
    OperationalKPIsBlock,
    PreliminaryFlag,
    RawExtraction,
    RiskItem,
    SegmentsBlock,
)
from portfolio_thesis_engine.schemas.common import Currency


# ======================================================================
# Narrative backward-compat
# ======================================================================


class TestNarrativeBackwardCompat:
    def test_narrative_item_plain_str_backward_compat(self) -> None:
        n = NarrativeContent(key_themes=["AI-driven growth"])
        assert len(n.key_themes) == 1
        item = n.key_themes[0]
        assert isinstance(item, NarrativeItem)
        assert item.text == "AI-driven growth"
        assert item.source is None

    def test_narrative_item_structured_dict_loaded(self) -> None:
        n = NarrativeContent(
            key_themes=[
                {
                    "text": "Record revenue",
                    "tag": "theme: Record revenue",
                    "supporting_facts": ["HK$377.1m (+2.4%)"],
                    "source": "MD&A Highlights",
                    "page": 14,
                    "confidence": "high",
                }
            ]
        )
        item = n.key_themes[0]
        assert item.tag == "theme: Record revenue"
        assert item.supporting_facts == ["HK$377.1m (+2.4%)"]
        assert item.source == "MD&A Highlights"
        assert item.page == 14
        assert item.confidence == "high"

    def test_risk_item_plain_str_backward_compat(self) -> None:
        n = NarrativeContent(risks_mentioned=["FX volatility"])
        assert isinstance(n.risks_mentioned[0], RiskItem)
        assert n.risks_mentioned[0].risk == "FX volatility"

    def test_risk_item_structured_loaded(self) -> None:
        n = NarrativeContent(
            risks_mentioned=[
                {
                    "risk": "Regulatory change",
                    "detail": "NMPA approval pending for Germany",
                    "severity": "medium",
                    "source": "Risk factors §3.2",
                    "page": 42,
                }
            ]
        )
        r = n.risks_mentioned[0]
        assert r.severity == "medium"
        assert r.page == 42

    def test_guidance_item_legacy_dict_without_metric_field(self) -> None:
        """Claude.ai extractor emits {guidance, statement, period,
        source} — the validator maps guidance→metric."""
        n = NarrativeContent(
            guidance_changes=[
                {
                    "guidance": "Revenue growth 10-15 %",
                    "statement": "Management guides revenue up 10-15 % through 2028",
                    "period": "2025-2028",
                    "source": "Investor day slide 28",
                }
            ]
        )
        g = n.guidance_changes[0]
        assert g.metric == "Revenue growth 10-15 %"
        assert g.statement.startswith("Management guides")
        assert g.period == "2025-2028"

    def test_guidance_item_structured_with_metric(self) -> None:
        n = NarrativeContent(
            guidance_changes=[
                {
                    "metric": "Operating margin",
                    "direction": "up",
                    "value": "18-20 %",
                    "period": "FY2025",
                    "statement": "Target mid-cycle margin",
                    "source": "Q1 press release",
                }
            ]
        )
        g = n.guidance_changes[0]
        assert g.metric == "Operating margin"
        assert g.direction == "up"

    def test_capital_allocation_item_backward_compat(self) -> None:
        # Plain str promoted to area="General" + detail=str.
        n = NarrativeContent(
            capital_allocation_comments=["Shareholders first; dividends maintained"]
        )
        c = n.capital_allocation_comments[0]
        assert isinstance(c, CapitalAllocationItem)
        assert c.area == "General"
        assert c.detail == "Shareholders first; dividends maintained"

        # Dict shape without area → mapped via 'category'.
        n2 = NarrativeContent(
            capital_allocation_comments=[
                {
                    "category": "Organic capex",
                    "detail": "HK$120m new clinic rollout",
                    "amount": "HK$120m",
                    "period": "FY2025",
                }
            ]
        )
        c2 = n2.capital_allocation_comments[0]
        assert c2.area == "Organic capex"
        assert c2.amount == "HK$120m"


# ======================================================================
# Metadata flexibility
# ======================================================================


class TestMetadataFlex:
    def test_audit_status_case_insensitive(self) -> None:
        # Uppercase from the Claude.ai extractor still resolves.
        assert AuditStatus("UNAUDITED") == AuditStatus.UNAUDITED
        assert AuditStatus("Audited") == AuditStatus.AUDITED
        assert AuditStatus("REVIEWED") == AuditStatus.REVIEWED

    def test_preliminary_flag_false_becomes_none(self) -> None:
        meta = DocumentMetadata(
            ticker="TST",
            company_name="Test Co",
            document_type=DocumentType.ANNUAL_REPORT,
            extraction_type=ExtractionType.NUMERIC,
            reporting_currency=Currency.USD,
            unit_scale="units",
            extraction_date="2025-01-01",
            fiscal_periods=[
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True}
            ],
            audit_status=AuditStatus.AUDITED,
            preliminary_flag=False,
        )
        assert meta.preliminary_flag is None

    def test_preliminary_flag_true_rejected_without_details(self) -> None:
        with pytest.raises(ValidationError, match="preliminary_flag: true"):
            DocumentMetadata(
                ticker="TST",
                company_name="Test Co",
                document_type=DocumentType.PRELIMINARY_RESULTS,
                extraction_type=ExtractionType.NUMERIC,
                reporting_currency=Currency.USD,
                unit_scale="units",
                extraction_date="2025-01-01",
                fiscal_periods=[
                    {
                        "period": "FY2025-prelim",
                        "end_date": "2025-12-31",
                        "is_primary": True,
                    }
                ],
                audit_status=AuditStatus.UNAUDITED,
                preliminary_flag=True,
            )


# ======================================================================
# Segments / KPI blocks
# ======================================================================


class TestSegmentsKPIBlocks:
    def _raw_payload(self) -> dict:
        return {
            "metadata": {
                "ticker": "TST",
                "company_name": "Test Co",
                "document_type": "annual_report",
                "extraction_type": "numeric",
                "reporting_currency": "USD",
                "unit_scale": "units",
                "extraction_date": "2025-01-01",
                "fiscal_periods": [
                    {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True}
                ],
            },
            "income_statement": {
                "FY2024": {
                    "line_items": [{"order": 1, "label": "Revenue", "value": "1000"}],
                }
            },
            "balance_sheet": {
                "FY2024": {
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

    def test_segments_dict_to_block(self) -> None:
        payload = self._raw_payload()
        payload["segments"] = {
            "by_geography": {
                "H1_2025": {
                    "Germany": {"revenue": "500", "ebitda": "120"},
                    "China": {"revenue": "300", "ebitda": "60"},
                }
            },
            "segment_meta": {
                "reporting_basis": "IFRS 8",
                "segments_identified": ["Germany", "China"],
                "codm": "CFO",
            },
        }
        raw = RawExtraction.model_validate(payload)
        assert isinstance(raw.segments, SegmentsBlock)
        assert raw.segments.by_geography is not None
        assert (
            raw.segments.by_geography["H1_2025"]["Germany"]["revenue"] == "500"
        )
        assert raw.segments.segment_meta is not None
        assert raw.segments.segment_meta.codm == "CFO"

    def test_segments_list_legacy_compat(self) -> None:
        payload = self._raw_payload()
        payload["segments"] = [
            {
                "period": "FY2024",
                "segment_type": "geography",
                "segments": [
                    {
                        "segment_name": "Germany",
                        "metrics": {"revenue": "500"},
                    }
                ],
            }
        ]
        raw = RawExtraction.model_validate(payload)
        # Legacy form wrapped into SegmentsBlock.legacy_periods.
        assert isinstance(raw.segments, SegmentsBlock)
        assert len(raw.segments.legacy_periods) == 1
        assert raw.segments.legacy_periods[0].period == "FY2024"

    def test_operational_kpis_dict_to_block(self) -> None:
        payload = self._raw_payload()
        payload["operational_kpis"] = {
            "metrics": {
                "total_clinics": {"H1_2025": 47, "H1_2024": 45},
                "total_revenue_hkd": {"H1_2025": "377.1M"},
            },
            "metric_sources": {"total_clinics": "MD&A §2"},
        }
        raw = RawExtraction.model_validate(payload)
        assert isinstance(raw.operational_kpis, OperationalKPIsBlock)
        assert raw.operational_kpis.metrics["total_clinics"]["H1_2025"] == 47
        assert raw.operational_kpis.metric_sources["total_clinics"] == "MD&A §2"

    def test_operational_kpis_list_legacy_compat(self) -> None:
        payload = self._raw_payload()
        payload["operational_kpis"] = [
            {
                "metric_label": "Headcount",
                "source": "MD&A",
                "values": {"FY2024": "850"},
            }
        ]
        raw = RawExtraction.model_validate(payload)
        assert isinstance(raw.operational_kpis, OperationalKPIsBlock)
        assert len(raw.operational_kpis.legacy_kpis) == 1
        assert raw.operational_kpis.legacy_kpis[0].metric_label == "Headcount"


# ======================================================================
# Notes + EPS
# ======================================================================


class TestNotesAndEPS:
    def test_note_source_pages_int_wrapped_to_list(self) -> None:
        note = Note(title="Test note", source_pages=14)
        assert note.source_pages == [14]

    def test_note_source_pages_list_passes_through(self) -> None:
        note = Note(title="Test note", source_pages=[14, 15, 16])
        assert note.source_pages == [14, 15, 16]

    def test_eps_source_note_accepted(self) -> None:
        # Int (common extractor output) coerced to str.
        eps = EarningsPerShare(
            basic_value=Decimal("2.5"),
            basic_unit="HK cents",
            source_note=13,
        )
        assert eps.source_note == "13"
        # Str passes through.
        eps2 = EarningsPerShare(source_note="13(a)")
        assert eps2.source_note == "13(a)"


# ======================================================================
# Display
# ======================================================================


class TestDisplayNarrativeSegments:
    def test_display_narrative_structured_renders_source_attribution(
        self,
    ) -> None:
        narrative = NarrativeContent(
            key_themes=[
                {
                    "text": "Group revenue reached HK$377.1m (+2.4%)",
                    "tag": "theme: Record revenue",
                    "source": "MD&A Highlights",
                    "page": 14,
                }
            ]
        )
        lines = show_cmd.render_narrative_section(narrative)
        joined = "\n".join(lines)
        assert "Group revenue reached HK$377.1m" in joined
        assert "theme: Record revenue" in joined
        assert "MD&A Highlights" in joined
        assert "p. 14" in joined

    def test_display_narrative_plain_str_renders_as_bullet(self) -> None:
        narrative = NarrativeContent(
            forward_looking_statements=["Targeting 20 % EBITDA margin by FY2027"]
        )
        lines = show_cmd.render_narrative_section(narrative)
        joined = "\n".join(lines)
        assert "Targeting 20 % EBITDA margin by FY2027" in joined
        # No source footnote because plain str has no attribution.
        assert "¹" not in joined

    def test_display_segments_block_renders_as_table(self) -> None:
        block = SegmentsBlock(
            by_geography={
                "FY2024": {
                    "Germany": {"revenue": Decimal("500000000")},
                    "China": {"revenue": Decimal("300000000")},
                }
            }
        )
        table = show_cmd.render_segments_block(block)
        assert table is not None
        # Rich Table exposes headers via .columns[*].header.
        headers = [col.header for col in table.columns]
        assert headers[0] == "Geography"
        assert "FY2024" in headers


# ======================================================================
# EuroEyes AR 2024 regression — existing fixture still validates
# ======================================================================


class TestEuroEyesARRegression:
    def test_euroeyes_ar_2024_still_validates(self) -> None:
        fixture = (
            Path(__file__).parent.parent
            / "fixtures"
            / "euroeyes"
            / "raw_extraction_real_claude_ai_2025.yaml"
        )
        raw = parse_raw_extraction(fixture)
        assert raw.metadata.ticker == "1846.HK"
        # Post-1.5.12: segments / operational_kpis normalise to the new
        # blocks even for the legacy audited fixture.
        assert isinstance(raw.segments, SegmentsBlock)
        assert isinstance(raw.operational_kpis, OperationalKPIsBlock)
