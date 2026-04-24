"""Phase 2 Sprint 4A-alpha.5 regression tests — briefing + cost
structure + leading indicators.

Part A — Cost structure analyzer (8 tests)
Part B — Leading indicators framework (6 tests)
Part C — AnalyticalBriefingGenerator (7 tests)
Part D — pte briefing CLI (5 tests)
Part E — EuroEyes starter + schema validation (3 tests)
Integration (3 tests)

Total: 32 tests.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from rich.console import Console

from portfolio_thesis_engine.briefing import (
    AnalyticalBriefingGenerator,
    CostStructureAnalyzer,
    LeadingIndicatorsLoader,
    LeadingIndicatorsSet,
)
from portfolio_thesis_engine.briefing.cost_structure import (
    CostStructureAnalysis,
    _classify_line_label,
)
from portfolio_thesis_engine.briefing.generator import BriefingInputs
from portfolio_thesis_engine.briefing.leading_indicators import (
    IndicatorDataSource,
    IndicatorEnvironment,
    IndicatorSensitivity,
    LeadingIndicator,
    fetch_fred_latest,
)
from portfolio_thesis_engine.cli import briefing_cmd
from portfolio_thesis_engine.schemas.common import Currency, FiscalPeriod, Profile
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
from portfolio_thesis_engine.schemas.historicals import (
    HistoricalPeriodType,
    HistoricalRecord,
)
from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus


# ======================================================================
# Shared fixtures
# ======================================================================
def _is_lines(rev: Decimal, cogs: Decimal, sga: Decimal) -> list[IncomeStatementLine]:
    return [
        IncomeStatementLine(label="Revenue", value=rev),
        IncomeStatementLine(label="Cost of sales", value=-cogs),
        IncomeStatementLine(label="Selling expenses", value=-sga / Decimal("2")),
        IncomeStatementLine(label="Administrative expenses", value=-sga / Decimal("2")),
        IncomeStatementLine(label="Operating profit", value=rev - cogs - sga),
    ]


def _canonical_state(
    period_label: str,
    period_end: date,
    revenue: Decimal,
    cogs: Decimal,
    sga: Decimal,
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=period_end.year, label=period_label)
    return CanonicalCompanyState(
        extraction_id=f"T_{period_label}",
        extraction_date=datetime(2025, 1, 1, tzinfo=UTC),
        as_of_date=period_end.isoformat(),
        identity=CompanyIdentity(
            ticker="T.HK", name="T", reporting_currency=Currency.HKD,
            profile=Profile.P1_INDUSTRIAL, fiscal_year_end_month=12,
            country_domicile="HK", exchange="HKEX",
        ),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=_is_lines(revenue, cogs, sga),
                balance_sheet=[],
                cash_flow=[],
                bs_checksum_pass=True, is_checksum_pass=True, cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[], nopat_bridge_by_period=[], ratios_by_period=[],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(check_id="V.0", name="ok", status="PASS", detail="ok")
            ],
            profile_specific_checksums=[], confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test", profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=["A"], audit_status="audited",
            source_document_type="annual_report",
        ),
    )


def _record(
    period: str, period_end: date, revenue: Decimal, op_income: Decimal, source_id: str
) -> HistoricalRecord:
    return HistoricalRecord(
        period=period,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type=HistoricalPeriodType.ANNUAL,
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=AuditStatus.AUDITED,
        source_canonical_state_id=source_id,
        source_document_type="annual_report",
        source_document_date=period_end,
        revenue=revenue,
        operating_income=op_income,
    )


# ======================================================================
# Part A — Cost structure analyzer
# ======================================================================
class TestPartACostStructure:
    def test_classify_line_label_identifies_standard_lines(self) -> None:
        assert _classify_line_label("Cost of sales") == "cogs"
        assert _classify_line_label("Selling expenses") == "selling"
        assert _classify_line_label("Administrative expenses") == "admin"
        assert _classify_line_label("Depreciation and amortisation") == "d_and_a"
        assert _classify_line_label("Revenue") is None
        assert _classify_line_label("Operating profit") is None

    def test_cost_line_weight_computation(self) -> None:
        state_23 = _canonical_state("FY2023", date(2023, 12, 31),
                                    Decimal("1000"), Decimal("400"), Decimal("300"))
        state_24 = _canonical_state("FY2024", date(2024, 12, 31),
                                    Decimal("1100"), Decimal("440"), Decimal("350"))
        records = [
            _record("FY2023", date(2023, 12, 31), Decimal("1000"), Decimal("300"), "T_FY2023"),
            _record("FY2024", date(2024, 12, 31), Decimal("1100"), Decimal("310"), "T_FY2024"),
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records,
            states={"T_FY2023": state_23, "T_FY2024": state_24},
        )
        cogs = next(cl for cl in result.cost_lines if cl.line_name == "cogs")
        assert cogs.weights_by_period["FY2023"] == Decimal("0.4")
        assert cogs.weights_by_period["FY2024"] == Decimal("0.4")

    def test_yoy_delta_bps_positive_and_negative(self) -> None:
        state_23 = _canonical_state("FY2023", date(2023, 12, 31),
                                    Decimal("1000"), Decimal("400"), Decimal("300"))
        state_24 = _canonical_state("FY2024", date(2024, 12, 31),
                                    Decimal("1100"), Decimal("550"), Decimal("330"))
        records = [
            _record("FY2023", date(2023, 12, 31), Decimal("1000"), Decimal("300"), "T_FY2023"),
            _record("FY2024", date(2024, 12, 31), Decimal("1100"), Decimal("220"), "T_FY2024"),
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records,
            states={"T_FY2023": state_23, "T_FY2024": state_24},
        )
        cogs = next(cl for cl in result.cost_lines if cl.line_name == "cogs")
        # weight 0.4 → 0.5 = +1000 bps
        assert cogs.yoy_delta_bps["FY2024"] == 1000
        # Trend expanded as % → EXPANDING_AS_PERCENT
        assert cogs.trend == "EXPANDING_AS_PERCENT"

    def test_margin_bridge_attribution_sums_to_delta(self) -> None:
        state_23 = _canonical_state("FY2023", date(2023, 12, 31),
                                    Decimal("1000"), Decimal("400"), Decimal("300"))
        state_24 = _canonical_state("FY2024", date(2024, 12, 31),
                                    Decimal("1000"), Decimal("500"), Decimal("400"))
        records = [
            _record("FY2023", date(2023, 12, 31), Decimal("1000"), Decimal("300"), "T_FY2023"),
            _record("FY2024", date(2024, 12, 31), Decimal("1000"), Decimal("100"), "T_FY2024"),
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records,
            states={"T_FY2023": state_23, "T_FY2024": state_24},
        )
        mb = result.margin_bridges[0]
        total = sum(mb.attribution_bps.values()) + mb.residual_bps
        assert total == mb.delta_bps

    def test_margin_bridge_residual_computed(self) -> None:
        state_23 = _canonical_state("FY2023", date(2023, 12, 31),
                                    Decimal("1000"), Decimal("400"), Decimal("300"))
        state_24 = _canonical_state("FY2024", date(2024, 12, 31),
                                    Decimal("1000"), Decimal("500"), Decimal("400"))
        records = [
            _record("FY2023", date(2023, 12, 31), Decimal("1000"), Decimal("300"), "T_FY2023"),
            _record("FY2024", date(2024, 12, 31), Decimal("1000"), Decimal("100"), "T_FY2024"),
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records,
            states={"T_FY2023": state_23, "T_FY2024": state_24},
        )
        # Residual is always populated (may be zero).
        assert hasattr(result.margin_bridges[0], "residual_bps")

    def test_operating_leverage_estimation_with_3_plus_periods(self) -> None:
        # Three periods → OLS produces a slope.
        states = {
            f"T_FY202{y}": _canonical_state(
                f"FY202{y}", date(2020 + y, 12, 31),
                Decimal(str(1000 + y * 100)),
                Decimal(str(400 + y * 30)),
                Decimal(str(300 + y * 20)),
            )
            for y in (3, 4, 5)
        }
        records = [
            _record(
                f"FY202{y}", date(2020 + y, 12, 31),
                Decimal(str(1000 + y * 100)),
                Decimal(str(300 + y * 50)),
                f"T_FY202{y}",
            )
            for y in (3, 4, 5)
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records, states=states
        )
        assert result.operating_leverage_estimate is not None
        assert result.total_fixed_cost_proxy is not None

    def test_graceful_degradation_when_only_aggregate_available(self) -> None:
        # No states provided → analyzer falls back to aggregate records.
        records = [
            _record("FY2023", date(2023, 12, 31), Decimal("1000"), Decimal("300"), "X"),
            _record("FY2024", date(2024, 12, 31), Decimal("1100"), Decimal("220"), "Y"),
        ]
        result = CostStructureAnalyzer().analyze(
            ticker="T.HK", records=records, states=None
        )
        # Margin bridges still work off record aggregates.
        assert result.margin_bridges
        assert result.cost_lines == []
        assert any("line-level" in note for note in result.analysis_notes)

    def test_cost_structure_analysis_schema_serialization(self) -> None:
        result = CostStructureAnalysis(target_ticker="T.HK", periods_analyzed=["FY2024"])
        dumped = result.model_dump()
        reloaded = CostStructureAnalysis.model_validate(dumped)
        assert reloaded.target_ticker == "T.HK"


# ======================================================================
# Part B — Leading indicators framework
# ======================================================================
class TestPartBLeadingIndicators:
    def test_leading_indicator_schema_validates(self) -> None:
        ind = LeadingIndicator(
            name="eur_hkd",
            category="CURRENCY",
            relevance=["MARGIN"],
            data_source=IndicatorDataSource(type="FRED", series_id="DEXEUHK"),
            sensitivity=IndicatorSensitivity(
                type="LINEAR", elasticity="1% → -0.05% margin"
            ),
            current_environment=IndicatorEnvironment(trend="STABLE"),
            confidence="HIGH",
        )
        assert ind.name == "eur_hkd"
        assert ind.data_source.series_id == "DEXEUHK"

    def test_loader_returns_none_when_file_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from portfolio_thesis_engine.shared import config

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        loader = LeadingIndicatorsLoader()
        assert loader.load_company("MISSING.XX") is None

    def test_loader_returns_set_when_file_present(self) -> None:
        """EuroEyes starter should load successfully."""
        loader = LeadingIndicatorsLoader()
        result = loader.load_company("1846.HK")
        assert result is not None
        assert result.target_ticker == "1846.HK"
        assert len(result.indicators) == 5

    def test_sector_default_catalogue_loads(self) -> None:
        loader = LeadingIndicatorsLoader()
        hc_defaults = loader.load_sector_defaults("healthcare_services")
        assert "healthcare_wage_inflation" in hc_defaults

    def test_suggest_missing_identifies_gap(self) -> None:
        loader = LeadingIndicatorsLoader()
        # EuroEyes leading_indicators.yaml has eur_hkd etc. but not
        # medical_consumables_ppi → catalogue suggestion should flag it.
        euroeyes = loader.load_company("1846.HK")
        suggestions = loader.suggest_missing(euroeyes, "healthcare_services")
        assert "medical_consumables_ppi" in suggestions

    def test_fred_fetch_stub_returns_none_when_no_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert fetch_fred_latest("DEXEUHK") is None


# ======================================================================
# Part C — AnalyticalBriefingGenerator
# ======================================================================
class TestPartCGenerator:
    def _inputs(self, **kwargs) -> BriefingInputs:
        return BriefingInputs(ticker="T.HK", **kwargs)

    def test_generate_header_always_present(self) -> None:
        gen = AnalyticalBriefingGenerator(self._inputs())
        md = gen.generate("full")
        assert "# T.HK — Analytical briefing" in md
        assert "Purpose" in md

    def test_purpose_capital_allocation_skips_valuation_scenarios(self) -> None:
        # Even with valuation_result present, capital_allocation skips it.
        fake_vr = MagicMock(scenarios_run=[MagicMock()], stage_1_wacc=Decimal("0.08"),
                            stage_3_wacc=Decimal("0.07"), expected_value_per_share=Decimal("6"))
        gen = AnalyticalBriefingGenerator(self._inputs(valuation_result=fake_vr))
        md = gen.generate("capital_allocation")
        assert "## 11. Valuation scenarios" not in md

    def test_purpose_scenarios_revise_includes_valuation(self) -> None:
        fake_vr = MagicMock(
            scenarios_run=[
                MagicMock(
                    scenario_name="base", scenario_probability=Decimal("1"),
                    methodology_used=MagicMock(value="DCF_3_STAGE"),
                    fair_value_per_share=Decimal("6"),
                )
            ],
            stage_1_wacc=Decimal("0.08"), stage_3_wacc=Decimal("0.07"),
            expected_value_per_share=Decimal("6"),
            implied_upside_downside_pct=Decimal("100"),
        )
        gen = AnalyticalBriefingGenerator(self._inputs(valuation_result=fake_vr))
        md = gen.generate("scenarios_revise")
        assert "## 11. Valuation scenarios" in md

    def test_purpose_full_includes_all_sections(self) -> None:
        gen = AnalyticalBriefingGenerator(self._inputs())
        md = gen.generate("full")
        # Core sections render even without inputs (graceful degradation).
        for header in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8."):
            assert header in md

    def test_graceful_degradation_when_data_missing(self) -> None:
        gen = AnalyticalBriefingGenerator(self._inputs())
        md = gen.generate("full")
        assert "Missing input" in md

    def test_generate_scenarios_generate_purpose_skips_scenarios(self) -> None:
        # scenarios_generate doesn't emit section 11 even with valuation.
        fake_vr = MagicMock(
            scenarios_run=[MagicMock()],
            stage_1_wacc=Decimal("0.08"), stage_3_wacc=Decimal("0.07"),
            expected_value_per_share=Decimal("6"),
        )
        gen = AnalyticalBriefingGenerator(self._inputs(valuation_result=fake_vr))
        md = gen.generate("scenarios_generate")
        assert "## 11. Valuation scenarios" not in md

    def test_leading_indicators_detail_present_when_supplied(self) -> None:
        indicators = LeadingIndicatorsSet(
            target_ticker="T.HK",
            sector_taxonomy="healthcare_services",
            indicators=[
                LeadingIndicator(
                    name="test_ind", category="DEMAND",
                    relevance=["REVENUE"],
                    data_source=IndicatorDataSource(type="MANUAL"),
                    confidence="HIGH",
                )
            ],
        )
        gen = AnalyticalBriefingGenerator(
            self._inputs(leading_indicators=indicators)
        )
        md = gen.generate("full")
        assert "## 12. Leading indicators — detail" in md
        assert "test_ind" in md


# ======================================================================
# Part D — pte briefing CLI
# ======================================================================
class TestPartDCLI:
    def test_cli_briefing_command_runs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "brief.md"
        briefing_cmd._run_briefing(
            "1846.HK", purpose="scenarios_generate", export=out,
            output_stdout=False, include_reverse=False,
        )
        assert out.exists()
        assert "Analytical briefing" in out.read_text()

    def test_cli_briefing_purpose_full_includes_more_sections(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "brief_full.md"
        briefing_cmd._run_briefing(
            "1846.HK", purpose="full", export=out,
            output_stdout=False, include_reverse=True,
        )
        md = out.read_text()
        # Full purpose should include valuation section (DCF data exists for EuroEyes).
        assert "## 11." in md

    def test_cli_briefing_export_custom_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        custom = tmp_path / "custom" / "my_briefing.md"
        briefing_cmd._run_briefing(
            "1846.HK", purpose="scenarios_generate", export=custom,
            output_stdout=False, include_reverse=False,
        )
        assert custom.exists()

    def test_cli_briefing_default_export_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Default export goes to /tmp/<ticker>_briefing_<purpose>.md
        briefing_cmd._run_briefing(
            "1846.HK", purpose="scenarios_generate", export=None,
            output_stdout=False, include_reverse=False,
        )
        default = Path("/tmp/1846-HK_briefing_scenarios_generate.md")
        assert default.exists()

    def test_cli_briefing_output_stdout_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(briefing_cmd, "console", Console(file=buf, width=240))
        briefing_cmd._run_briefing(
            "1846.HK", purpose="scenarios_generate", export=None,
            output_stdout=True, include_reverse=False,
        )
        assert "Analytical briefing" in buf.getvalue()


# ======================================================================
# Part E — EuroEyes starter + schema validation
# ======================================================================
class TestPartEEuroEyes:
    def test_leading_indicators_yaml_schema_validates(self) -> None:
        """EuroEyes YAML round-trips through the Pydantic schema."""
        loader = LeadingIndicatorsLoader()
        result = loader.load_company("1846.HK")
        assert result is not None
        # Re-dump and re-validate to ensure schema conformance.
        dumped = result.model_dump(mode="json")
        reloaded = LeadingIndicatorsSet.model_validate(dumped)
        assert reloaded.target_ticker == "1846.HK"

    def test_leading_indicators_starter_loads_for_euroeyes(self) -> None:
        loader = LeadingIndicatorsLoader()
        result = loader.load_company("1846.HK")
        assert result is not None
        names = {i.name for i in result.indicators}
        assert {"eur_hkd_exchange_rate", "prc_deposit_rate"} <= names

    def test_schema_reference_doc_exists(self) -> None:
        path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "schemas"
            / "leading_indicators_schema_reference.md"
        )
        assert path.exists(), f"Expected schema reference doc at {path}"
        content = path.read_text()
        assert "`leading_indicators.yaml` — schema reference" in content


# ======================================================================
# Integration (EuroEyes end-to-end)
# ======================================================================
class TestIntegration:
    def test_briefing_generates_at_least_180_lines_for_euroeyes(self) -> None:
        """Sanity check that EuroEyes briefing is comprehensive
        (Sprint 2A/2B/3/4A-alpha output all flows through)."""
        briefing_cmd._run_briefing(
            "1846.HK", purpose="full", export=Path("/tmp/int_test.md"),
            output_stdout=False, include_reverse=True,
        )
        md = Path("/tmp/int_test.md").read_text()
        assert len(md.splitlines()) >= 180

    def test_briefing_contains_cost_structure_margin_bridge_for_euroeyes(
        self,
    ) -> None:
        briefing_cmd._run_briefing(
            "1846.HK", purpose="scenarios_generate",
            export=Path("/tmp/int_cost.md"),
            output_stdout=False, include_reverse=False,
        )
        md = Path("/tmp/int_cost.md").read_text()
        assert "FY2023 → FY2024" in md
        assert "Δ -1091 bps" in md or "-1091 bps" in md

    def test_briefing_indicator_detail_for_euroeyes_has_all_five(self) -> None:
        briefing_cmd._run_briefing(
            "1846.HK", purpose="full",
            export=Path("/tmp/int_ind.md"),
            output_stdout=False, include_reverse=False,
        )
        md = Path("/tmp/int_ind.md").read_text()
        for name in (
            "eur_hkd_exchange_rate",
            "eur_cny_exchange_rate",
            "prc_deposit_rate",
            "prc_consumer_confidence",
            "german_healthcare_wage_growth",
        ):
            assert name in md
