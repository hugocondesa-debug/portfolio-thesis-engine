"""Unit tests for ``pte validate-extraction``."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app

runner = CliRunner()

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


class TestValidateExtraction:
    def test_clean_fixture_exits_with_warns(self) -> None:
        """The fixture passes strict but has warn-tier inconsistencies
        (primary + next-period reconciliation) plus missing pensions /
        acquisitions recommended notes → exit 1 (not 2)."""
        result = runner.invoke(app, ["validate-extraction", str(_FIXTURE)])
        # exit 1 because warn tier surfaces WARNs + completeness
        # surfaces recommended-missing WARNs
        assert result.exit_code in (0, 1), result.output
        assert "strict" in result.output
        assert "warn" in result.output
        assert "completeness" in result.output

    def test_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["validate-extraction", str(tmp_path / "absent.yaml")]
        )
        assert result.exit_code == 2
        assert "Failed to parse" in result.output

    def test_broken_bs_identity_exits_2(self, tmp_path: Path) -> None:
        """BS identity broken: Assets 500 vs Liab 100 + Equity 100 = 200."""
        broken = tmp_path / "broken.yaml"
        broken.write_text(
            """
metadata:
  ticker: "X"
  company_name: "X"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  fiscal_year: 2024
  extraction_date: "2025-01-01"
  fiscal_periods:
    - period: "FY2024"
      end_date: "2024-12-31"
      is_primary: true
income_statement:
  FY2024:
    line_items:
      - {order: 1, label: "Revenue", value: "100"}
      - {order: 2, label: "Profit for the year", value: "10", is_subtotal: true}
balance_sheet:
  FY2024:
    line_items:
      - {order: 1, label: "Total assets", value: "500", section: "total_assets", is_subtotal: true}
      - {order: 2, label: "Total liabilities", value: "100", section: "total_liabilities", is_subtotal: true}
      - {order: 3, label: "Total equity", value: "100", section: "equity", is_subtotal: true}
""",
            encoding="utf-8",
        )
        result = runner.invoke(app, ["validate-extraction", str(broken)])
        assert result.exit_code == 2
        assert "FAIL" in result.output

    def test_profile_flag_accepted(self) -> None:
        """Unsupported profiles (P2-P6) return SKIP on completeness
        but the command still exits 0/1."""
        result = runner.invoke(
            app, ["validate-extraction", str(_FIXTURE), "--profile", "P2"]
        )
        # P2 → completeness SKIP; warn tier still produces WARNs on
        # the fixture → exit 1.
        assert result.exit_code in (0, 1)

    def test_unknown_profile_exits_2(self) -> None:
        result = runner.invoke(
            app, ["validate-extraction", str(_FIXTURE), "--profile", "BOGUS"]
        )
        assert result.exit_code == 2
        assert "Unknown profile" in result.output

    def test_help_lists_flags(self) -> None:
        result = runner.invoke(app, ["validate-extraction", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
