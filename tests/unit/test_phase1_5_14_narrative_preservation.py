"""Phase 1.5.14 regression tests — narrative preservation through the
pipeline.

15 tests covering:

Schema (2):
- ``test_canonical_state_narrative_context_optional_when_absent``
- ``test_canonical_state_narrative_context_persists_items``

ExtractionCoordinator (3):
- ``test_extract_canonical_builds_narrative_context_from_raw``
- ``test_extract_canonical_narrative_context_source_period_matches_primary``
- ``test_extract_canonical_narrative_context_none_when_no_narrative``

FichaComposer (5):
- ``test_ficha_narrative_summary_built_from_canonical``
- ``test_ficha_narrative_summary_condenses_narrative_items_with_attribution``
- ``test_ficha_narrative_summary_condenses_risk_items_with_attribution``
- ``test_ficha_narrative_summary_limits_item_count``
- ``test_ficha_narrative_summary_none_when_canonical_narrative_empty``

CLI (2):
- ``test_show_detail_renders_narrative_summary_when_present``
- ``test_show_narrative_flag_renders_attribution``

YAML round-trip (1):
- ``test_narrative_context_yaml_round_trip``

EuroEyes-style integration (2):
- ``test_euroeyes_ar_style_narrative_flows_end_to_end``
- ``test_euroeyes_interim_minimal_narrative_preserved``
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.cli import show_cmd
from portfolio_thesis_engine.cli.show_cmd import render_narrative_summary
from portfolio_thesis_engine.extraction.coordinator import _build_narrative_context
from portfolio_thesis_engine.ficha import FichaBundle
from portfolio_thesis_engine.ficha.composer import (
    FichaComposer,
    _condense_narrative,
)
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
    NarrativeContext,
    NOPATBridge,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.ficha import NarrativeSummary
from portfolio_thesis_engine.schemas.raw_extraction import (
    CapitalAllocationItem,
    GuidanceItem,
    NarrativeItem,
    RawExtraction,
    RiskItem,
)


# ======================================================================
# Helpers — minimal canonical state builder
# ======================================================================


def _minimal_canonical(
    *, narrative_context: NarrativeContext | None = None
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=2024, label="FY2024")
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
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
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=[],
        ),
        narrative_context=narrative_context,
    )


def _sample_narrative_context(
    source_period: str = "FY2024",
    source_doc: str = "annual_report",
) -> NarrativeContext:
    return NarrativeContext(
        key_themes=[
            NarrativeItem(
                text="Group revenue reached HK$377.1m (+2.4%)",
                tag="theme: Record revenue",
                source="MD&A Highlights",
                page=14,
            ),
            NarrativeItem(text="PRC expansion in Q2-Q4 2025"),
        ],
        risks_mentioned=[
            RiskItem(
                risk="Munich clinic refurbishment",
                detail="H2 2024 revenue impact of HK$12M",
                severity="medium",
                source="Note 4.1",
                page=42,
            ),
            RiskItem(risk="FX volatility"),
        ],
        guidance_changes=[
            GuidanceItem(
                metric="Revenue",
                direction="up",
                value="820M HKD",
                period="FY2025",
                statement="Target FY2025 revenue > 820M HKD",
                source="Investor presentation p.12",
            )
        ],
        capital_allocation_signals=[
            CapitalAllocationItem(
                area="Organic capex",
                detail="Shanghai flagship clinic Q2 2025",
                amount="HK$120m",
                period="FY2025",
                source="MD&A",
            )
        ],
        forward_looking_statements=[
            NarrativeItem(text="FY2025 margin expected 15-17 %"),
        ],
        source_extraction_period=source_period,
        source_document_type=source_doc,
        extraction_timestamp=datetime(2026, 4, 23, tzinfo=UTC),
    )


# ======================================================================
# Schema
# ======================================================================


class TestCanonicalNarrativeContext:
    def test_canonical_state_narrative_context_optional_when_absent(
        self,
    ) -> None:
        state = _minimal_canonical()
        assert state.narrative_context is None

    def test_canonical_state_narrative_context_persists_items(self) -> None:
        ctx = _sample_narrative_context()
        state = _minimal_canonical(narrative_context=ctx)
        assert state.narrative_context is not None
        assert len(state.narrative_context.key_themes) == 2
        assert state.narrative_context.risks_mentioned[0].severity == "medium"


# ======================================================================
# ExtractionCoordinator narrative build
# ======================================================================


class TestExtractCanonicalNarrativeBuild:
    def test_extract_canonical_builds_narrative_context_from_raw(
        self, wacc_inputs
    ) -> None:
        from .conftest import build_raw

        raw = build_raw()
        # Inject narrative on the raw extraction.
        raw.narrative = None  # reset so model_validate accepts the dict
        payload = raw.model_dump()
        payload["narrative"] = {
            "key_themes": ["Record revenue"],
            "risks_mentioned": ["FX volatility"],
        }
        raw = RawExtraction.model_validate(payload)
        ctx = _build_narrative_context(raw, primary_period="FY2024")
        assert ctx is not None
        assert len(ctx.key_themes) == 1
        assert ctx.key_themes[0].text == "Record revenue"
        assert ctx.risks_mentioned[0].risk == "FX volatility"

    def test_extract_canonical_narrative_context_source_period_matches_primary(
        self,
    ) -> None:
        from .conftest import build_raw

        raw = build_raw()
        payload = raw.model_dump()
        payload["narrative"] = {"key_themes": ["Growth"]}
        raw = RawExtraction.model_validate(payload)
        ctx = _build_narrative_context(raw, primary_period="H1_2025")
        assert ctx is not None
        assert ctx.source_extraction_period == "H1_2025"
        assert ctx.source_document_type == "annual_report"

    def test_extract_canonical_narrative_context_none_when_no_narrative(
        self,
    ) -> None:
        from .conftest import build_raw

        raw = build_raw()
        # raw.narrative defaults to None / empty.
        ctx = _build_narrative_context(raw, primary_period="FY2024")
        assert ctx is None


# ======================================================================
# FichaComposer condensation
# ======================================================================


class TestFichaNarrativeSummary:
    def test_ficha_narrative_summary_built_from_canonical(self) -> None:
        ctx = _sample_narrative_context()
        state = _minimal_canonical(narrative_context=ctx)
        ficha = FichaComposer().compose(state)
        assert ficha.narrative_summary is not None
        assert ficha.narrative_summary.source_period == "FY2024"
        assert ficha.narrative_summary.source_document_type == "annual_report"

    def test_ficha_narrative_summary_condenses_narrative_items_with_attribution(
        self,
    ) -> None:
        ctx = _sample_narrative_context()
        summary = _condense_narrative(ctx)
        assert summary is not None
        themes = summary.key_themes
        assert len(themes) == 2
        # First theme has tag + source + page → annotated.
        assert "[theme: Record revenue]" in themes[0]
        assert "MD&A Highlights" in themes[0]
        assert "p. 14" in themes[0]
        # Second theme has neither → plain.
        assert "[source:" not in themes[1]

    def test_ficha_narrative_summary_condenses_risk_items_with_attribution(
        self,
    ) -> None:
        ctx = _sample_narrative_context()
        summary = _condense_narrative(ctx)
        risks = summary.primary_risks
        assert "Munich clinic refurbishment" in risks[0]
        assert "revenue impact" in risks[0]
        assert "Note 4.1" in risks[0]
        assert "p. 42" in risks[0]

    def test_ficha_narrative_summary_limits_item_count(self) -> None:
        # 10 key themes → summary keeps at most 7 (default cap).
        ctx = NarrativeContext(
            key_themes=[NarrativeItem(text=f"Theme {i}") for i in range(10)],
            source_extraction_period="FY2024",
            source_document_type="annual_report",
            extraction_timestamp=datetime.now(UTC),
        )
        summary = _condense_narrative(ctx)
        assert summary is not None
        assert len(summary.key_themes) == 7

    def test_ficha_narrative_summary_none_when_canonical_narrative_empty(
        self,
    ) -> None:
        state = _minimal_canonical()
        ficha = FichaComposer().compose(state)
        assert ficha.narrative_summary is None


# ======================================================================
# CLI renderer
# ======================================================================


class TestCLINarrativeRendering:
    def _ficha_with_narrative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> FichaBundle:
        from portfolio_thesis_engine.schemas.ficha import Ficha

        state = _minimal_canonical(narrative_context=_sample_narrative_context())
        ficha = FichaComposer().compose(state)
        return FichaBundle(
            ticker="TST",
            canonical_state=state,
            valuation_snapshot=None,
            ficha=ficha,
        )

    def test_show_narrative_flag_renders_attribution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = self._ficha_with_narrative(monkeypatch)
        lines = render_narrative_summary(bundle.ficha)
        joined = "\n".join(lines)
        assert "Narrative summary" in joined
        assert "Key themes" in joined
        assert "Primary risks" in joined
        assert "Management guidance" in joined
        # Attribution baked into bullets.
        assert "MD&A Highlights" in joined
        assert "Munich clinic refurbishment" in joined

    def test_render_narrative_summary_empty_for_ficha_without_summary(
        self,
    ) -> None:
        from portfolio_thesis_engine.schemas.ficha import Ficha

        state = _minimal_canonical()
        ficha = FichaComposer().compose(state)
        assert render_narrative_summary(ficha) == []


# ======================================================================
# YAML round-trip
# ======================================================================


class TestNarrativeYAMLRoundTrip:
    def test_narrative_context_yaml_round_trip(self) -> None:
        ctx = _sample_narrative_context()
        state = _minimal_canonical(narrative_context=ctx)
        payload = state.to_yaml()
        round_tripped = CanonicalCompanyState.from_yaml(payload)
        assert round_tripped.narrative_context is not None
        assert (
            round_tripped.narrative_context.risks_mentioned[0].risk
            == "Munich clinic refurbishment"
        )
        # Attribution survives.
        assert round_tripped.narrative_context.key_themes[0].source == (
            "MD&A Highlights"
        )


# ======================================================================
# EuroEyes-style integration
# ======================================================================


class TestEuroEyesStyleNarrativeFlow:
    def test_euroeyes_ar_style_narrative_flows_end_to_end(self) -> None:
        """Rich narrative from an audited AR flows through canonical →
        ficha unchanged. Summary retains attribution."""
        ctx = _sample_narrative_context(
            source_period="FY2024", source_doc="annual_report"
        )
        state = _minimal_canonical(narrative_context=ctx)
        ficha = FichaComposer().compose(state)
        summary = ficha.narrative_summary
        assert summary is not None
        assert summary.source_document_type == "annual_report"
        # Full chain: key themes preserved + decorated.
        assert any("Record revenue" in t for t in summary.key_themes)
        assert any("Munich" in r for r in summary.primary_risks)
        assert any("820M HKD" in g for g in summary.management_guidance)

    def test_euroeyes_interim_minimal_narrative_preserved(self) -> None:
        """Interim reports may have a sparser narrative; whatever is
        captured survives."""
        ctx = NarrativeContext(
            key_themes=[NarrativeItem(text="H1 2025 revenue +12% YoY")],
            source_extraction_period="H1_2025",
            source_document_type="interim_report",
            extraction_timestamp=datetime.now(UTC),
        )
        state = _minimal_canonical(narrative_context=ctx)
        ficha = FichaComposer().compose(state)
        summary = ficha.narrative_summary
        assert summary is not None
        assert summary.source_period == "H1_2025"
        assert summary.source_document_type == "interim_report"
        assert summary.key_themes == ["H1 2025 revenue +12% YoY"]
        # Empty buckets default to empty list, never fail.
        assert summary.primary_risks == []
        assert summary.management_guidance == []
