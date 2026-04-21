"""Unit tests for ``pte ingest`` via typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app
from portfolio_thesis_engine.cli.ingest_cmd import _split_files

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_data_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir",
        tmp_path / "data",
    )
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.backup_dir",
        tmp_path / "backup",
    )


# ======================================================================
# _split_files helper
# ======================================================================


class TestSplitFiles:
    def test_comma_separated(self) -> None:
        out = _split_files("a.md,b.md, c.md")
        assert [p.name for p in out] == ["a.md", "b.md", "c.md"]

    def test_empty_segments_dropped(self) -> None:
        out = _split_files("a.md,,b.md,")
        assert len(out) == 2

    def test_single_path(self) -> None:
        out = _split_files("a.md")
        assert len(out) == 1


# ======================================================================
# CLI invocation
# ======================================================================


class TestIngestCLI:
    def _make_files(self, tmp_path: Path) -> tuple[Path, Path]:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        wacc = tmp_path / "wacc_inputs.md"
        wacc.write_text(
            "---\nticker: 1846.HK\nprofile: P1\n"
            'valuation_date: "2025-03-31"\n'
            'current_price: "12.50"\n'
            "cost_of_capital:\n"
            "  risk_free_rate: 3.5\n"
            "  equity_risk_premium: 6.0\n"
            "  beta: 1.2\n"
            "  cost_of_debt_pretax: 4.5\n"
            "  tax_rate_for_wacc: 16.5\n"
            "capital_structure:\n"
            "  debt_weight: 30\n"
            "  equity_weight: 70\n"
            "scenarios:\n"
            "  base:\n"
            "    probability: 100\n"
            "    revenue_cagr_explicit_period: 8\n"
            "    terminal_growth: 2.5\n"
            "    terminal_operating_margin: 18\n"
            "---\n"
        )
        return ar, wacc

    def test_happy_path(self, tmp_path: Path) -> None:
        ar, wacc = self._make_files(tmp_path)
        result = runner.invoke(
            app,
            [
                "ingest",
                "--ticker",
                "1846.HK",
                "--files",
                f"{ar},{wacc}",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Ingested 2 document(s)" in result.output
        assert "1846-HK" in result.output
        assert "annual_report" in result.output
        assert "wacc_inputs" in result.output

    def test_fatal_validation_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "ingest",
                "--ticker",
                "ACME",
                "--files",
                str(tmp_path / "nonexistent.md"),
            ],
        )
        assert result.exit_code == 1
        assert "Ingestion failed" in result.output

    def test_pre_extracted_exits_with_explanation(self, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        result = runner.invoke(
            app,
            [
                "ingest",
                "--ticker",
                "ACME",
                "--files",
                str(ar),
                "--mode",
                "pre_extracted",
            ],
        )
        assert result.exit_code == 2
        assert "Phase 2" in result.output

    def test_unknown_mode_validated_by_typer(self, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100.\n")
        result = runner.invoke(
            app,
            ["ingest", "--ticker", "ACME", "--files", str(ar), "--mode", "nope"],
        )
        # Coordinator raises ValueError → typer surfaces it as exit != 0
        assert result.exit_code != 0

    def test_empty_files_arg_exits(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["ingest", "--ticker", "ACME", "--files", ",, "],
        )
        assert result.exit_code == 1
        assert "No files provided" in result.output

    def test_profile_flag(self, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        result = runner.invoke(
            app,
            [
                "ingest",
                "--ticker",
                "ACME",
                "--files",
                str(ar),
                "--profile",
                "P3a",
            ],
        )
        assert result.exit_code == 0

    def test_help_lists_flags(self) -> None:
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "--ticker" in result.output
        assert "--files" in result.output
        assert "--mode" in result.output
