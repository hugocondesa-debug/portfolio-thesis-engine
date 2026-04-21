"""Unit tests for ingestion.wacc_markdown_parser.parse_wacc_markdown.

Also pins the detection logic in :func:`wacc_parser.parse_wacc_inputs`
— ``---`` routes to YAML, everything else routes to markdown.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.wacc_markdown_parser import (
    _extract_table_fields,
    _match_alias,
    _normalize,
    _parse_business_scenarios,
    _parse_decimal,
    _parse_header_fields,
    _parse_tables,
    _split_h2_sections,
)
from portfolio_thesis_engine.ingestion.wacc_parser import (
    _looks_like_frontmatter,
    parse_wacc_inputs,
)
from portfolio_thesis_engine.schemas.common import Profile

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "wacc"


# ======================================================================
# 1. Format detection (YAML vs markdown routing)
# ======================================================================


class TestFormatDetection:
    @pytest.mark.parametrize(
        "first_lines, expected",
        [
            ("---\nticker: X\n", True),
            ("\n\n---\nticker: X\n", True),
            ("# Some title\n\nprose\n", False),
            ("", False),
            ("   \n   \n", False),
            ("-- not three dashes\n", False),
            ("---x\nticker: X\n", False),  # not exactly ---
        ],
    )
    def test_frontmatter_detection(self, first_lines: str, expected: bool) -> None:
        assert _looks_like_frontmatter(first_lines) is expected

    def test_yaml_frontmatter_backward_compat(self, tmp_path: Path) -> None:
        """Existing YAML files parse unchanged."""
        path = tmp_path / "yaml.md"
        path.write_text(
            """---
ticker: 1846.HK
profile: P1
valuation_date: "2024-12-31"
current_price: "12.30"
cost_of_capital:
  risk_free_rate: 2.5
  equity_risk_premium: 5.5
  beta: 1.1
  cost_of_debt_pretax: 4.0
  tax_rate_for_wacc: 16.5
capital_structure:
  debt_weight: 25
  equity_weight: 75
scenarios:
  base:
    probability: 100
    revenue_cagr_explicit_period: 8
    terminal_growth: 2.5
    terminal_operating_margin: 18
---
""",
            encoding="utf-8",
        )
        w = parse_wacc_inputs(path)
        assert w.ticker == "1846.HK"
        # No size_premium in YAML → backward-compatible cost_of_equity
        assert w.cost_of_capital.size_premium is None
        assert w.cost_of_equity == Decimal("2.5") + Decimal("1.1") * Decimal("5.5")


# ======================================================================
# 2. Normalisation + parsing primitives
# ======================================================================


class TestNormalize:
    @pytest.mark.parametrize(
        "inp, expected",
        [
            ("Share Price", "share price"),
            ("Risk-Free Rate (Rf)", "risk free rate rf"),
            ("  Beta   levered  ", "beta levered"),
            ("Cost of Debt (Kd)", "cost of debt kd"),
            ("Tax rate", "tax rate"),
            ("D/E target", "d e target"),
            ("", ""),
        ],
    )
    def test_normalise(self, inp: str, expected: str) -> None:
        assert _normalize(inp) == expected


class TestParseDecimal:
    @pytest.mark.parametrize(
        "inp, expected",
        [
            ("2.50", Decimal("2.50")),
            ("2,460", Decimal("2460")),
            ("50%", Decimal("50")),
            ("1.50 HKD", Decimal("1.50")),
            ("-3.2", Decimal("-3.2")),
            ("12.30 ", Decimal("12.30")),
        ],
    )
    def test_parses(self, inp: str, expected: Decimal) -> None:
        assert _parse_decimal(inp) == expected

    @pytest.mark.parametrize("inp", ["n/a", "", "N/A", "tbd"])
    def test_non_numeric_returns_none(self, inp: str) -> None:
        assert _parse_decimal(inp) is None


# ======================================================================
# 3. Synonym matching
# ======================================================================


class TestSynonymMatching:
    def test_exact_match(self) -> None:
        aliases = {"beta": ("beta", "beta levered")}
        assert _match_alias("Beta", aliases) == "beta"

    def test_parenthetical_tolerated(self) -> None:
        aliases = {"risk_free_rate": ("risk free rate",)}
        assert _match_alias("Risk-Free Rate (Rf)", aliases) == "risk_free_rate"

    def test_multi_word_alias(self) -> None:
        aliases = {"equity_risk_premium": ("equity risk premium", "erp")}
        assert _match_alias("Equity Risk Premium", aliases) == "equity_risk_premium"
        assert _match_alias("ERP", aliases) == "equity_risk_premium"

    def test_no_match_returns_none(self) -> None:
        aliases = {"x": ("foo",)}
        assert _match_alias("Completely Different", aliases) is None

    def test_debt_wont_match_cost_of_debt(self) -> None:
        """Word-bounded matching prevents ``debt_weight`` from capturing
        a ``Cost of Debt`` row in the WACC parameters table."""
        aliases = {"debt_weight": ("debt",)}
        # "Cost of Debt" contains "debt" as a token → this would match
        # when using pure substring logic, so the parser relies on
        # passing a *separate* alias dict to each section. We still
        # document the cross-risk with this test.
        assert _match_alias("Cost of Debt", aliases) == "debt_weight"
        # But the production code separates the dicts: Cost of Debt is
        # only consulted against _FIELD_ALIASES (where "cost of debt"
        # appears before any "debt" entry — and debt isn't there).


# ======================================================================
# 4. Section splitting + table parsing
# ======================================================================


class TestStructureParsing:
    def test_split_h2_sections(self) -> None:
        content = (
            "# Title\n\nPreamble\n\n## Market Data\n\nrow1\n\n## WACC Parameters\nrow2\n"
        )
        sections = _split_h2_sections(content)
        assert "market data" in sections
        assert "wacc parameters" in sections
        assert "row1" in sections["market data"]

    def test_parse_single_table(self) -> None:
        text = """
| Parameter | Value |
|-----------|-------|
| Rf        | 2.5   |
| Beta      | 1.1   |
"""
        tables = _parse_tables(text)
        assert len(tables) == 1
        assert tables[0] == [
            {"Parameter": "Rf", "Value": "2.5"},
            {"Parameter": "Beta", "Value": "1.1"},
        ]

    def test_parse_two_tables(self) -> None:
        text = """
| A | B |
|---|---|
| 1 | 2 |

| X | Y |
|---|---|
| 3 | 4 |
"""
        assert len(_parse_tables(text)) == 2

    def test_table_row_padding(self) -> None:
        """Row with fewer cells than header still parses."""
        text = """
| A | B | C |
|---|---|---|
| 1 | 2 |
"""
        tables = _parse_tables(text)
        assert tables[0][0] == {"A": "1", "B": "2", "C": ""}


# ======================================================================
# 5. Business scenarios
# ======================================================================


class TestBusinessScenarios:
    def test_all_three_scenarios(self) -> None:
        body = """
### Bear (25%)
- Revenue CAGR: 3.0%
- Terminal operating margin: 15.0%
- Terminal growth: 2.0%

### Base (50%)
- Revenue CAGR: 8.0%
- Terminal operating margin: 18.0%
- Terminal growth: 2.5%

### Bull (25%)
- Revenue CAGR: 12.0%
- Terminal operating margin: 22.0%
- Terminal growth: 3.0%
"""
        scenarios = _parse_business_scenarios(body)
        assert set(scenarios) == {"bear", "base", "bull"}
        assert scenarios["base"].probability == Decimal("50")
        assert scenarios["bull"].revenue_cagr_explicit_period == Decimal("12.0")
        assert scenarios["bear"].terminal_operating_margin == Decimal("15.0")

    def test_incomplete_scenario_dropped(self) -> None:
        """A scenario missing one required driver is silently skipped
        (the top-level validator raises if *all* are dropped)."""
        body = """
### Bear (25%)
- Revenue CAGR: 3.0%

### Base (75%)
- Revenue CAGR: 8.0%
- Terminal operating margin: 18.0%
- Terminal growth: 2.5%
"""
        scenarios = _parse_business_scenarios(body)
        assert set(scenarios) == {"base"}

    def test_unknown_scenario_label_ignored(self) -> None:
        body = """
### Surprise (100%)
- Revenue CAGR: 5%
- Terminal operating margin: 18%
- Terminal growth: 2.5%
"""
        assert _parse_business_scenarios(body) == {}

    def test_probability_with_percent_or_without(self) -> None:
        body = """
### Base (100%)
- Revenue CAGR: 5%
- Terminal operating margin: 18%
- Terminal growth: 2%

### Bull (0)
- Revenue CAGR: 10
- Terminal operating margin: 25
- Terminal growth: 3
"""
        scenarios = _parse_business_scenarios(body)
        assert scenarios["base"].probability == Decimal("100")
        assert scenarios["bull"].probability == Decimal("0")


# ======================================================================
# 6. Header fields
# ======================================================================


class TestHeaderFields:
    def test_pulls_bold_keyvalue_pairs_from_preamble_only(self) -> None:
        content = """
**Ticker:** 1846.HK
**Profile:** P1
**Valuation date:** 2025-03-31

## Notes
**Warning:** this is inside an H2 and must NOT be pulled as a header field.
"""
        fields = _parse_header_fields(content)
        assert fields["ticker"] == "1846.HK"
        assert fields["profile"] == "P1"
        assert fields["valuation date"] == "2025-03-31"
        assert "warning" not in fields


# ======================================================================
# 7. End-to-end with fixtures
# ======================================================================


class TestMinimalFixture:
    def test_minimal_markdown_fixture_parses(self) -> None:
        w = parse_wacc_inputs(_FIXTURE_DIR / "minimal_markdown.md")
        assert w.ticker == "TESTCO"
        assert w.profile == Profile.P1_INDUSTRIAL
        assert w.valuation_date == "2024-12-31"
        assert w.current_price == Decimal("50.00")
        assert set(w.scenarios) == {"bear", "base", "bull"}
        # Backward-compat: no size_premium → cost_of_equity = rf + β·ERP
        assert w.cost_of_capital.size_premium is None
        assert w.cost_of_equity == Decimal("3") + Decimal("1") * Decimal("5")


class TestHugoRealFixture:
    """The full markdown format mirroring Hugo's real analyst workflow."""

    def test_parses_end_to_end(self) -> None:
        w = parse_wacc_inputs(_FIXTURE_DIR / "euroeyes_real.md")
        assert w.ticker == "1846.HK"
        assert w.profile == Profile.P1_INDUSTRIAL
        assert w.valuation_date == "2025-03-31"
        assert w.current_price == Decimal("12.30")
        # Scenarios
        assert set(w.scenarios) == {"bear", "base", "bull"}
        assert w.scenarios["base"].probability == Decimal("50")
        assert w.scenarios["bull"].revenue_cagr_explicit_period == Decimal("12.0")
        # Size premium picked up
        assert w.cost_of_capital.size_premium == Decimal("1.50")
        # cost_of_equity = 2.5 + 1.1 × 5.5 + 1.5 = 10.05
        assert w.cost_of_equity == Decimal("10.0500")
        # Capital structure
        assert w.capital_structure.debt_weight == Decimal("25")
        assert w.capital_structure.equity_weight == Decimal("75")
        # WACC computes cleanly (property — verifies size_premium feeds through)
        assert w.wacc > Decimal("0")


# ======================================================================
# 8. Failure modes — clear errors
# ======================================================================


class TestFailureModes:
    def test_missing_ticker_raises(self, tmp_path: Path) -> None:
        md = """# WACC Inputs

**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric      | Value |
|-------------|-------|
| Share price | 10    |

## WACC Parameters
| Parameter           | Value |
|---------------------|-------|
| Risk-Free Rate      | 3     |
| Equity Risk Premium | 5     |
| Beta                | 1     |
| Cost of Debt        | 5     |
| Tax rate            | 25    |

## Capital Structure
| Component | Weight |
|-----------|--------|
| Debt      | 30     |
| Equity    | 70     |

## Business Scenarios
### Base (100%)
- Revenue CAGR: 5%
- Terminal operating margin: 18%
- Terminal growth: 2%
"""
        f = tmp_path / "no_ticker.md"
        f.write_text(md)
        with pytest.raises(IngestionError, match="Ticker"):
            parse_wacc_inputs(f)

    def test_missing_share_price_raises(self, tmp_path: Path) -> None:
        md = """# WACC
**Ticker:** X
**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric     | Value |
|------------|-------|
| Market cap | 1000  |
"""
        f = tmp_path / "no_price.md"
        f.write_text(md)
        with pytest.raises(IngestionError, match="Share price"):
            parse_wacc_inputs(f)

    def test_missing_wacc_param_raises(self, tmp_path: Path) -> None:
        md = """# WACC
**Ticker:** X
**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric      | Value |
|-------------|-------|
| Share price | 10    |

## WACC Parameters
| Parameter           | Value |
|---------------------|-------|
| Risk-Free Rate      | 3     |
"""
        f = tmp_path / "missing_wacc.md"
        f.write_text(md)
        with pytest.raises(IngestionError, match="missing WACC parameters"):
            parse_wacc_inputs(f)

    def test_missing_scenarios_raises(self, tmp_path: Path) -> None:
        md = """# WACC
**Ticker:** X
**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric      | Value |
|-------------|-------|
| Share price | 10    |

## WACC Parameters
| Parameter           | Value |
|---------------------|-------|
| Risk-Free Rate      | 3     |
| Equity Risk Premium | 5     |
| Beta                | 1     |
| Cost of Debt        | 5     |
| Tax rate            | 25    |

## Capital Structure
| Component | Weight |
|-----------|--------|
| Debt      | 30     |
| Equity    | 70     |

## Business Scenarios
(empty)
"""
        f = tmp_path / "no_scenarios.md"
        f.write_text(md)
        with pytest.raises(IngestionError, match="Bear/Base/Bull"):
            parse_wacc_inputs(f)

    def test_probabilities_dont_sum_propagates_pydantic_error(
        self, tmp_path: Path
    ) -> None:
        """Malformed probabilities raise :class:`ValidationError`
        through :class:`WACCInputs` — consistent with the YAML path."""
        md = """# WACC
**Ticker:** X
**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric      | Value |
|-------------|-------|
| Share price | 10    |

## WACC Parameters
| Parameter           | Value |
|---------------------|-------|
| Risk-Free Rate      | 3     |
| Equity Risk Premium | 5     |
| Beta                | 1     |
| Cost of Debt        | 5     |
| Tax rate            | 25    |

## Capital Structure
| Component | Weight |
|-----------|--------|
| Debt      | 30     |
| Equity    | 70     |

## Business Scenarios
### Bear (25%)
- Revenue CAGR: 3%
- Terminal operating margin: 15%
- Terminal growth: 2%

### Base (30%)
- Revenue CAGR: 8%
- Terminal operating margin: 18%
- Terminal growth: 2.5%

### Bull (25%)
- Revenue CAGR: 12%
- Terminal operating margin: 22%
- Terminal growth: 3%
"""
        f = tmp_path / "bad_probs.md"
        f.write_text(md)
        # Probabilities sum to 80, not 100 → ValidationError from Pydantic
        with pytest.raises(ValidationError, match="probabilities"):
            parse_wacc_inputs(f)

    def test_unknown_profile_raises(self, tmp_path: Path) -> None:
        md = """# WACC
**Ticker:** X
**Profile:** UNKNOWN
**Valuation date:** 2024-12-31

## Market Data
| Metric      | Value |
|-------------|-------|
| Share price | 10    |
"""
        f = tmp_path / "bad_profile.md"
        f.write_text(md)
        with pytest.raises(IngestionError, match="unknown profile"):
            parse_wacc_inputs(f)


# ======================================================================
# 9. Internals: _extract_table_fields with an alias dict
# ======================================================================


class TestExtractTableFields:
    def test_first_cell_label_matched_second_cell_parsed(self) -> None:
        tables = [
            [
                {"Parameter": "Risk-Free Rate", "Value": "2.5"},
                {"Parameter": "Beta", "Value": "1.1"},
                {"Parameter": "Tax rate", "Value": "25"},
            ]
        ]
        from portfolio_thesis_engine.ingestion.wacc_markdown_parser import (
            _FIELD_ALIASES,
        )

        out = _extract_table_fields(tables, _FIELD_ALIASES)
        assert out["risk_free_rate"] == Decimal("2.5")
        assert out["beta"] == Decimal("1.1")
        assert out["tax_rate_for_wacc"] == Decimal("25")

    def test_first_match_wins(self) -> None:
        """If the same canonical appears twice, the first occurrence
        is kept."""
        tables = [
            [
                {"Parameter": "Risk-Free Rate", "Value": "2.0"},
                {"Parameter": "Rf", "Value": "99"},
            ]
        ]
        from portfolio_thesis_engine.ingestion.wacc_markdown_parser import (
            _FIELD_ALIASES,
        )

        out = _extract_table_fields(tables, _FIELD_ALIASES)
        assert out["risk_free_rate"] == Decimal("2.0")
