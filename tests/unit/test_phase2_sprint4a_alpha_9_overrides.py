"""Sprint 4A-alpha.9 — ScenarioDriverOverride input aliases + fade horizon shorthand.

Covers:

- ``target`` → ``target_terminal`` :class:`AliasChoices` resolution.
- ``fade_to_terminal_over_years`` integer shorthand (1–10) and its
  mutual exclusion with ``fade_pattern``.
- Serialisation always emits canonical field names.
- Existing EuroEyes scenarios.yaml continues to validate unchanged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.dcf.schemas import ScenarioDriverOverride


# ======================================================================
# target_terminal alias
# ======================================================================
class TestTargetAlias:
    def test_P2_S4A_ALPHA_9_TARGET_01_canonical_still_works(self):
        override = ScenarioDriverOverride(target_terminal=Decimal("0.23"))
        assert override.target_terminal == Decimal("0.23")

    def test_P2_S4A_ALPHA_9_TARGET_02_alias_populates_canonical(self):
        override = ScenarioDriverOverride.model_validate({"target": 0.23})
        assert override.target_terminal == Decimal("0.23")

    def test_P2_S4A_ALPHA_9_TARGET_03_canonical_via_model_validate(self):
        override = ScenarioDriverOverride.model_validate(
            {"target_terminal": 0.23}
        )
        assert override.target_terminal == Decimal("0.23")

    def test_P2_S4A_ALPHA_9_TARGET_04_serialization_uses_canonical(self):
        """``model_dump`` / YAML roundtrip must emit ``target_terminal``,
        never the ``target`` alias."""
        override = ScenarioDriverOverride.model_validate({"target": 0.23})
        dumped = override.model_dump()
        assert "target_terminal" in dumped
        assert dumped["target_terminal"] == Decimal("0.23")
        assert "target" not in dumped


# ======================================================================
# fade_to_terminal_over_years shorthand
# ======================================================================
class TestFadeShorthand:
    def test_P2_S4A_ALPHA_9_FADE_01_sets_integer_horizon(self):
        override = ScenarioDriverOverride(fade_to_terminal_over_years=3)
        assert override.fade_to_terminal_over_years == 3
        # fade_pattern is orthogonal; remains None when only the horizon
        # is specified.
        assert override.fade_pattern is None

    def test_P2_S4A_ALPHA_9_FADE_02_fade_pattern_alone_still_works(self):
        override = ScenarioDriverOverride(fade_pattern="LINEAR")
        assert override.fade_pattern == "LINEAR"
        assert override.fade_to_terminal_over_years is None

    def test_P2_S4A_ALPHA_9_FADE_03_both_raises(self):
        with pytest.raises(ValidationError, match="Cannot specify both"):
            ScenarioDriverOverride(
                fade_to_terminal_over_years=3, fade_pattern="LINEAR"
            )

    def test_P2_S4A_ALPHA_9_FADE_04_out_of_range_low_raises(self):
        with pytest.raises(ValidationError, match="between 1 and 10"):
            ScenarioDriverOverride(fade_to_terminal_over_years=0)

    def test_P2_S4A_ALPHA_9_FADE_05_out_of_range_high_raises(self):
        with pytest.raises(ValidationError, match="between 1 and 10"):
            ScenarioDriverOverride(fade_to_terminal_over_years=11)

    def test_P2_S4A_ALPHA_9_FADE_06_boundary_values_ok(self):
        """1 and 10 are the accepted inclusive bounds."""
        assert (
            ScenarioDriverOverride(
                fade_to_terminal_over_years=1
            ).fade_to_terminal_over_years
            == 1
        )
        assert (
            ScenarioDriverOverride(
                fade_to_terminal_over_years=10
            ).fade_to_terminal_over_years
            == 10
        )


# ======================================================================
# Combined usage
# ======================================================================
class TestCombinedUsage:
    def test_P2_S4A_ALPHA_9_COMBO_01_all_analyst_shortcuts(self):
        """``target`` alias + ``fade_to_terminal_over_years`` together."""
        override = ScenarioDriverOverride.model_validate(
            {
                "current": 0.1756,
                "target": 0.23,
                "fade_to_terminal_over_years": 3,
            }
        )
        assert override.current == Decimal("0.1756")
        assert override.target_terminal == Decimal("0.23")
        assert override.fade_to_terminal_over_years == 3
        assert override.fade_pattern is None

    def test_P2_S4A_ALPHA_9_COMBO_02_euroeyes_scenarios_still_validate(self):
        scenario_set = load_scenarios("1846.HK")
        assert scenario_set is not None
        assert len(scenario_set.scenarios) == 7

    def test_P2_S4A_ALPHA_9_COMBO_03_roundtrip_preserves_canonical(self):
        """Input via alias + shorthand → dump → re-validate → same values."""
        source = {
            "current": 0.1756,
            "target": 0.23,
            "fade_to_terminal_over_years": 3,
        }
        first = ScenarioDriverOverride.model_validate(source)
        dumped = first.model_dump()
        second = ScenarioDriverOverride.model_validate(dumped)
        assert second.target_terminal == first.target_terminal
        assert second.fade_to_terminal_over_years == first.fade_to_terminal_over_years
        assert "target" not in dumped  # canonical-only output
