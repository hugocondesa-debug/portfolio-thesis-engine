"""Unit tests for ``pte cross-check``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app

runner = CliRunner()


_FMP_FUND = {
    "income_statement": [{"revenue": 580, "operatingIncome": 110, "netIncome": 75}],
    "balance_sheet": [
        {
            "totalAssets": 3200,
            "totalStockholdersEquity": 1900,
            "cashAndCashEquivalents": 450,
        }
    ],
    "cash_flow": [{"operatingCashFlow": 135, "capitalExpenditure": -75}],
}
_FMP_KM = {"records": [{"sharesOutstanding": 200, "marketCap": 2500}]}
_YF_FUND = {
    "income_statement": [
        {
            "Total Revenue": 582,
            "Operating Income": 108,
            "Net Income": 76,
        }
    ],
    "balance_sheet": [
        {
            "Total Assets": 3195,
            "Stockholders Equity": 1905,
            "Cash And Cash Equivalents": 449,
        }
    ],
    "cash_flow": [{"Operating Cash Flow": 134, "Capital Expenditure": -74}],
}
_YF_KM = {"records": [{"sharesOutstanding": 199, "marketCap": 2480}]}


@pytest.fixture(autouse=True)
def _isolated_data_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir",
        tmp_path / "data",
    )


@pytest.fixture(autouse=True)
def _mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intercept the provider constructors inside the CLI command so the
    CLI tests never touch real APIs."""
    from portfolio_thesis_engine.cli import cross_check_cmd

    fake_fmp = MagicMock()
    fake_fmp.__aenter__ = AsyncMock(return_value=fake_fmp)
    fake_fmp.__aexit__ = AsyncMock(return_value=None)
    fake_fmp.get_fundamentals = AsyncMock(return_value=_FMP_FUND)
    fake_fmp.get_key_metrics = AsyncMock(return_value=_FMP_KM)
    monkeypatch.setattr(cross_check_cmd, "FMPProvider", lambda: fake_fmp)

    fake_yf = MagicMock()
    fake_yf.get_fundamentals = AsyncMock(return_value=_YF_FUND)
    fake_yf.get_key_metrics = AsyncMock(return_value=_YF_KM)
    monkeypatch.setattr(cross_check_cmd, "YFinanceProvider", lambda: fake_yf)


class TestCrossCheckCLI:
    def test_happy_path_all_pass(self) -> None:
        values = {
            "revenue": "580",
            "operating_income": "110",
            "net_income": "75",
            "total_assets": "3200",
            "total_equity": "1900",
            "cash": "450",
            "operating_cash_flow": "135",
            "capex": "-75",
            "shares_outstanding": "200",
            "market_cap": "2500",
        }
        result = runner.invoke(
            app,
            [
                "cross-check",
                "1846.HK",
                "--period",
                "FY2024",
                "--values-json",
                json.dumps(values),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Overall" in result.output
        assert "PASS" in result.output
        # Table rendered for every metric
        assert "revenue" in result.output
        assert "market_cap" in result.output

    def test_fail_exits_nonzero(self) -> None:
        # Extracted net income 100x too high → FAIL → exit 1
        values = {
            "revenue": "580",
            "net_income": "7500",  # 100x too high
        }
        result = runner.invoke(
            app,
            [
                "cross-check",
                "1846.HK",
                "--period",
                "FY2024",
                "--values-json",
                json.dumps(values),
            ],
        )
        assert result.exit_code == 1
        assert "BLOCK" in result.output

    def test_invalid_values_json_errors(self) -> None:
        result = runner.invoke(
            app,
            [
                "cross-check",
                "1846.HK",
                "--values-json",
                "{not json",
            ],
        )
        assert result.exit_code != 0

    def test_non_numeric_value_errors(self) -> None:
        result = runner.invoke(
            app,
            [
                "cross-check",
                "1846.HK",
                "--values-json",
                json.dumps({"revenue": "not-a-number"}),
            ],
        )
        assert result.exit_code != 0

    def test_override_thresholds_accepted(self) -> None:
        """Override JSON tightens revenue threshold to trigger WARN on
        what would otherwise PASS."""
        values = {"revenue": "582"}
        # 0.34% drift; override PASS to 0.001 (0.1%) so 0.34% → WARN
        override = json.dumps({"per_metric": {"revenue": {"PASS": "0.001", "WARN": "0.01"}}})
        result = runner.invoke(
            app,
            [
                "cross-check",
                "1846.HK",
                "--values-json",
                json.dumps(values),
                "--override-thresholds",
                override,
            ],
        )
        # WARN doesn't block, exit 0, but status is WARN
        assert result.exit_code == 0
        assert "WARN" in result.output

    def test_help_lists_flags(self) -> None:
        result = runner.invoke(app, ["cross-check", "--help"])
        assert result.exit_code == 0
        assert "--period" in result.output
        assert "--values-json" in result.output
        assert "--override-thresholds" in result.output
