"""Unit tests for ingestion.wacc_parser."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.wacc_parser import parse_wacc_inputs

_EUROEYES_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "euroeyes" / "wacc_inputs.md"


def _minimal_wacc_text(
    valuation_date: str = "2025-03-31",
    debt_weight: int = 30,
    equity_weight: int = 70,
    probability_bear: int = 25,
    probability_base: int = 50,
    probability_bull: int = 25,
) -> str:
    return f"""---
ticker: 1846.HK
profile: P1
valuation_date: {valuation_date}
current_price: "12.50"
cost_of_capital:
  risk_free_rate: 3.5
  equity_risk_premium: 6.0
  beta: 1.2
  cost_of_debt_pretax: 4.5
  tax_rate_for_wacc: 16.5
capital_structure:
  debt_weight: {debt_weight}
  equity_weight: {equity_weight}
scenarios:
  bear:
    probability: {probability_bear}
    revenue_cagr_explicit_period: 3
    terminal_growth: 2
    terminal_operating_margin: 15
  base:
    probability: {probability_base}
    revenue_cagr_explicit_period: 8
    terminal_growth: 2.5
    terminal_operating_margin: 18
  bull:
    probability: {probability_bull}
    revenue_cagr_explicit_period: 12
    terminal_growth: 3
    terminal_operating_margin: 22
---

Free-form notes after the frontmatter are ignored.
"""


class TestParseWACCInputs:
    def test_happy_path(self, tmp_path: Path) -> None:
        f = tmp_path / "wacc_inputs.md"
        f.write_text(_minimal_wacc_text())
        w = parse_wacc_inputs(f)
        assert w.ticker == "1846.HK"
        assert w.valuation_date == "2025-03-31"
        assert w.cost_of_capital.beta == Decimal("1.2")
        assert len(w.scenarios) == 3
        # Derived WACC matches the schema-level test (8.6172500)
        assert w.wacc == Decimal("8.6172500")

    def test_date_auto_parsed_by_yaml_normalised(self, tmp_path: Path) -> None:
        """Unquoted 'valuation_date: 2025-03-31' becomes a Python date
        after YAML load; the parser must coerce it back to ISO string."""
        text = _minimal_wacc_text(valuation_date="2025-03-31").replace(
            'current_price: "12.50"', "current_price: 12.50"
        )
        # Note: valuation_date is unquoted → PyYAML returns datetime.date
        f = tmp_path / "wacc_inputs.md"
        f.write_text(text)
        w = parse_wacc_inputs(f)
        assert w.valuation_date == "2025-03-31"

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "wacc_inputs.md"
        f.write_text("Just prose, no frontmatter delimiter.\n")
        with pytest.raises(IngestionError, match="frontmatter delimiter"):
            parse_wacc_inputs(f)

    def test_unclosed_frontmatter_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "wacc_inputs.md"
        f.write_text("---\nticker: X\nprofile: P1\n# no closing delim\n")
        with pytest.raises(IngestionError, match="not closed"):
            parse_wacc_inputs(f)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "wacc_inputs.md"
        f.write_text("---\nticker: [unclosed\n---\n")
        with pytest.raises(IngestionError, match="not valid YAML"):
            parse_wacc_inputs(f)

    def test_non_dict_frontmatter_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "wacc_inputs.md"
        f.write_text("---\n- just\n- a\n- list\n---\n")
        with pytest.raises(IngestionError, match="must be a YAML mapping"):
            parse_wacc_inputs(f)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(IngestionError, match="Cannot read"):
            parse_wacc_inputs(tmp_path / "nonexistent.md")

    def test_schema_validation_error_propagates(self, tmp_path: Path) -> None:
        """Schema errors (e.g., probabilities don't sum) come through as
        ValidationError, not IngestionError, so callers can surface a
        rich message."""
        f = tmp_path / "wacc_inputs.md"
        f.write_text(
            _minimal_wacc_text(probability_bear=10, probability_base=10, probability_bull=10)
        )
        with pytest.raises(ValidationError, match="sum to 30"):
            parse_wacc_inputs(f)

    def test_euroeyes_fixture_loads(self) -> None:
        """The fixture ships with the repo; test guards against regressions."""
        assert _EUROEYES_FIXTURE.exists(), "EuroEyes WACC fixture missing"
        w = parse_wacc_inputs(_EUROEYES_FIXTURE)
        assert w.ticker == "1846.HK"
        assert len(w.scenarios) == 3
        assert set(w.scenarios) == {"bear", "base", "bull"}
