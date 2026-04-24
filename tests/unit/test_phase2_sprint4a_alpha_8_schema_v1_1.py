"""Sprint 4A-alpha.8 — schema v1.1 hybrid scenario_relevance + backward compat.

Covers:

1. :class:`ScenarioBucket` enum shape.
2. :func:`infer_bucket_from_name` / :class:`Scenario.resolved_bucket` inference rules.
3. :func:`expand_scenario_relevance` bucket expansion.
4. EuroEyes production yamls still validate with v1.1 schemas.
5. :func:`validate_scenario_cross_reference` warning generation.
6. Production yaml parsing round-trip.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from portfolio_thesis_engine.briefing.leading_indicators import (
    IndicatorDataSource,
    IndicatorEnvironment,
    IndicatorSensitivity,
    LeadingIndicator,
    LeadingIndicatorsLoader,
    LeadingIndicatorsSet,
)
from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.dcf.schemas import (
    DCFProfile,
    Scenario,
    ScenarioSet,
)
from portfolio_thesis_engine.forecast.capital_allocation_consumer import (
    load_capital_allocation,
)
from portfolio_thesis_engine.schemas.scenario_bucket import (
    ScenarioBucket,
    infer_bucket_from_name,
)
from portfolio_thesis_engine.validation import (
    expand_scenario_relevance,
    validate_scenario_cross_reference,
)


# ======================================================================
# ScenarioBucket enum
# ======================================================================
class TestScenarioBucketEnum:
    def test_P2_S4A_ALPHA_8_BUCKET_01_enum_has_four_values(self):
        assert {b.value for b in ScenarioBucket} == {"BASE", "BULL", "BEAR", "TAIL"}

    def test_P2_S4A_ALPHA_8_BUCKET_02_enum_string_valued(self):
        assert ScenarioBucket.BASE.value == "BASE"
        assert isinstance(ScenarioBucket.BULL, str)


# ======================================================================
# Bucket inference (name-based + explicit override)
# ======================================================================
class TestScenarioBucketInference:
    def test_P2_S4A_ALPHA_8_INFER_01_base_prefix_resolves_to_base(self):
        assert (
            Scenario(name="base", probability=Decimal("0.3")).resolved_bucket
            == ScenarioBucket.BASE
        )

    def test_P2_S4A_ALPHA_8_INFER_02_bull_prefix_resolves_to_bull(self):
        assert (
            Scenario(
                name="bull_operational", probability=Decimal("0.15")
            ).resolved_bucket
            == ScenarioBucket.BULL
        )

    def test_P2_S4A_ALPHA_8_INFER_03_bear_prefix_resolves_to_bear(self):
        assert (
            Scenario(
                name="bear_structural", probability=Decimal("0.15")
            ).resolved_bucket
            == ScenarioBucket.BEAR
        )

    def test_P2_S4A_ALPHA_8_INFER_04_takeover_prefix_resolves_to_tail(self):
        assert (
            Scenario(name="takeover_floor", probability=Decimal("0.1")).resolved_bucket
            == ScenarioBucket.TAIL
        )

    def test_P2_S4A_ALPHA_8_INFER_05_m_and_a_accelerated_resolves_to_bull(self):
        assert (
            Scenario(
                name="m_and_a_accelerated", probability=Decimal("0.06")
            ).resolved_bucket
            == ScenarioBucket.BULL
        )

    def test_P2_S4A_ALPHA_8_INFER_06_explicit_overrides_inference(self):
        """Explicit ``bucket`` wins over name-based inference."""
        scen = Scenario(
            name="bull_operational",
            probability=Decimal("0.15"),
            bucket=ScenarioBucket.TAIL,
        )
        assert scen.resolved_bucket == ScenarioBucket.TAIL

    def test_P2_S4A_ALPHA_8_INFER_07_unknown_name_defaults_to_bull(self):
        assert (
            Scenario(
                name="custom_scenario_x", probability=Decimal("0.1")
            ).resolved_bucket
            == ScenarioBucket.BULL
        )

    def test_P2_S4A_ALPHA_8_INFER_08_tail_prefix_also_tail(self):
        assert infer_bucket_from_name("tail_recession") == ScenarioBucket.TAIL
        assert infer_bucket_from_name("fire_sale") == ScenarioBucket.TAIL

    def test_P2_S4A_ALPHA_8_INFER_09_case_insensitive(self):
        assert infer_bucket_from_name("BASE") == ScenarioBucket.BASE
        assert infer_bucket_from_name("Bear_Case") == ScenarioBucket.BEAR


# ======================================================================
# expand_scenario_relevance
# ======================================================================
def _scenario_set() -> ScenarioSet:
    return ScenarioSet(
        target_ticker="TEST",
        valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        base_year="FY2024",
        scenarios=[
            Scenario(name="base", probability=Decimal("0.32")),
            Scenario(name="bull_operational", probability=Decimal("0.15")),
            Scenario(name="bull_re_rating", probability=Decimal("0.15")),
            Scenario(name="bear_structural", probability=Decimal("0.15")),
            Scenario(name="bear_prc_delay", probability=Decimal("0.13")),
            Scenario(name="takeover_floor", probability=Decimal("0.10")),
        ],
    )


class TestExpandScenarioRelevance:
    def test_P2_S4A_ALPHA_8_EXPAND_01_generic_bull_expands_to_all_bulls(self):
        result = expand_scenario_relevance(["BULL"], _scenario_set())
        assert "bull_operational" in result
        assert "bull_re_rating" in result
        assert "base" not in result

    def test_P2_S4A_ALPHA_8_EXPAND_02_specific_name_passes_through(self):
        assert expand_scenario_relevance(
            ["bear_prc_delay"], _scenario_set()
        ) == ["bear_prc_delay"]

    def test_P2_S4A_ALPHA_8_EXPAND_03_mixed_references_both_resolve(self):
        result = expand_scenario_relevance(["BASE", "bear_prc_delay"], _scenario_set())
        assert "base" in result
        assert "bear_prc_delay" in result
        assert "bull_operational" not in result

    def test_P2_S4A_ALPHA_8_EXPAND_04_unknown_specific_name_dropped(self):
        assert expand_scenario_relevance(["nonexistent"], _scenario_set()) == []

    def test_P2_S4A_ALPHA_8_EXPAND_05_tail_bucket_expands_to_takeover(self):
        result = expand_scenario_relevance(["TAIL"], _scenario_set())
        assert "takeover_floor" in result

    def test_P2_S4A_ALPHA_8_EXPAND_06_sorted_and_deduped(self):
        """Duplicates (from a bucket + explicit name) collapse; output sorted."""
        result = expand_scenario_relevance(
            ["BULL", "bull_operational"], _scenario_set()
        )
        assert result == ["bull_operational", "bull_re_rating"]


# ======================================================================
# Cross-reference validator
# ======================================================================
def _indicator(
    name: str, scenario_relevance: list[str]
) -> LeadingIndicator:
    return LeadingIndicator(
        name=name,
        category="CURRENCY",
        data_source=IndicatorDataSource(type="MANUAL"),
        sensitivity=IndicatorSensitivity(type="QUALITATIVE"),
        current_environment=IndicatorEnvironment(data_date=None),
        scenario_relevance=scenario_relevance,
    )


def _leading_set(*indicators: LeadingIndicator) -> LeadingIndicatorsSet:
    return LeadingIndicatorsSet(
        target_ticker="TEST",
        indicators=list(indicators),
    )


class TestCrossReferenceValidator:
    def test_P2_S4A_ALPHA_8_CROSSREF_01_valid_references_no_warnings(self):
        ind = _indicator("ok", ["base", "bull_operational"])
        warnings = validate_scenario_cross_reference(
            _leading_set(ind), _scenario_set()
        )
        assert warnings == []

    def test_P2_S4A_ALPHA_8_CROSSREF_02_invalid_name_produces_warning(self):
        ind = _indicator("typo", ["base", "bull_oprational"])
        warnings = validate_scenario_cross_reference(
            _leading_set(ind), _scenario_set()
        )
        assert len(warnings) == 1
        assert "bull_oprational" in warnings[0]
        assert "typo" in warnings[0]

    def test_P2_S4A_ALPHA_8_CROSSREF_03_generic_bucket_always_valid(self):
        """BASE/BULL/BEAR/TAIL never produce warnings even against an
        empty scenario set (they resolve to zero matches but aren't
        flagged as unknown names)."""
        empty_set = ScenarioSet(
            target_ticker="T",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[],
        )
        ind = _indicator(
            "generic_only", ["BASE", "BULL", "BEAR", "TAIL"]
        )
        warnings = validate_scenario_cross_reference(
            _leading_set(ind), empty_set
        )
        assert warnings == []

    def test_P2_S4A_ALPHA_8_CROSSREF_04_none_inputs_return_no_warnings(self):
        warnings = validate_scenario_cross_reference(None, _scenario_set())
        assert warnings == []


# ======================================================================
# Backward compatibility — EuroEyes production yamls
# ======================================================================
class TestSchemaBackwardCompat:
    def test_P2_S4A_ALPHA_8_BC_01_euroeyes_scenarios_loads(self):
        scenario_set = load_scenarios("1846.HK")
        assert scenario_set is not None
        assert len(scenario_set.scenarios) == 7

    def test_P2_S4A_ALPHA_8_BC_02_euroeyes_all_buckets_infer(self):
        scenario_set = load_scenarios("1846.HK")
        assert scenario_set is not None
        valid = {
            ScenarioBucket.BASE,
            ScenarioBucket.BULL,
            ScenarioBucket.BEAR,
            ScenarioBucket.TAIL,
        }
        for scen in scenario_set.scenarios:
            assert scen.resolved_bucket in valid

    def test_P2_S4A_ALPHA_8_BC_03_euroeyes_leading_indicators_loads(self):
        loader = LeadingIndicatorsLoader()
        indicators = loader.load_company("1846.HK")
        assert indicators is not None
        assert len(indicators.indicators) == 7

    def test_P2_S4A_ALPHA_8_BC_04_euroeyes_bucket_map_exact(self):
        """Exact bucket inference for the live EuroEyes scenario set.
        Guards against any regression in the inference rules."""
        scenario_set = load_scenarios("1846.HK")
        assert scenario_set is not None
        actual = {s.name: s.resolved_bucket for s in scenario_set.scenarios}
        assert actual == {
            "base": ScenarioBucket.BASE,
            "bull_operational": ScenarioBucket.BULL,
            "bull_re_rating": ScenarioBucket.BULL,
            "bear_structural": ScenarioBucket.BEAR,
            "bear_prc_delay": ScenarioBucket.BEAR,
            "takeover_floor": ScenarioBucket.TAIL,
            "m_and_a_accelerated": ScenarioBucket.BULL,
        }


# ======================================================================
# Production yaml parse round-trip
# ======================================================================
class TestProductionYAMLValidation:
    def test_P2_S4A_ALPHA_8_PROD_01_scenarios_yaml_validates(self):
        path = Path("data/yamls/companies/1846-HK/scenarios.yaml")
        assert path.exists()
        data = yaml.safe_load(path.read_text())
        scenario_set = ScenarioSet.model_validate(data)
        assert scenario_set.target_ticker == "1846.HK"

    def test_P2_S4A_ALPHA_8_PROD_02_leading_indicators_yaml_validates(self):
        path = Path("data/yamls/companies/1846-HK/leading_indicators.yaml")
        assert path.exists()
        loader = LeadingIndicatorsLoader()
        result = loader.load_company("1846.HK")
        assert result is not None
        # All specific names cross-reference against the real scenario set.
        scenario_set = load_scenarios("1846.HK")
        assert scenario_set is not None
        warnings = validate_scenario_cross_reference(result, scenario_set)
        assert warnings == []

    def test_P2_S4A_ALPHA_8_PROD_03_capital_allocation_yaml_validates(self):
        result = load_capital_allocation("1846.HK")
        assert result is not None


# ======================================================================
# Hybrid scenario_relevance round-trip (generic bucket yaml)
# ======================================================================
class TestHybridScenarioRelevanceYAML:
    def test_P2_S4A_ALPHA_8_HYBRID_01_generic_bucket_yaml_validates(self):
        """A leading_indicators document using BASE/BULL directly
        validates and preserves the bucket strings on round-trip."""
        raw = yaml.safe_load(
            """
            target_ticker: TEST.XX
            last_updated: 2026-04-24T00:00:00Z
            sector_taxonomy: test.sector
            source_documents_referenced: []
            indicators:
              - name: test_indicator
                category: CURRENCY
                relevance: [MARGIN]
                data_source:
                  type: MANUAL
                sensitivity:
                  type: QUALITATIVE
                  interpretation: test
                current_environment:
                  trend: STABLE
                  recent_volatility: LOW
                  direction: NEUTRAL
                  data_date: 2026-04-24
                scenario_relevance: [BASE, BULL]
                confidence: MEDIUM
            """
        )
        parsed = LeadingIndicatorsSet.model_validate(raw)
        assert parsed.indicators[0].scenario_relevance == ["BASE", "BULL"]

    def test_P2_S4A_ALPHA_8_HYBRID_02_mixed_scenario_relevance(self):
        """Generic bucket + specific name coexist in one list."""
        ind = _indicator("mixed", ["BULL", "base"])
        scenario_set = _scenario_set()
        expanded = expand_scenario_relevance(
            ind.scenario_relevance, scenario_set
        )
        assert set(expanded) == {
            "base",
            "bull_operational",
            "bull_re_rating",
        }
