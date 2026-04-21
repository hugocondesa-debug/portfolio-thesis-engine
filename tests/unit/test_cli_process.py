"""Unit tests for ``pte process`` (Phase 1.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app
from portfolio_thesis_engine.guardrails.results import AggregatedResults
from portfolio_thesis_engine.pipeline.coordinator import (
    CrossCheckBlocked,
    ExtractionValidationBlocked,
    PipelineError,
    PipelineOutcome,
    PipelineStage,
    StageOutcome,
)
from portfolio_thesis_engine.schemas.common import GuardrailStatus

runner = CliRunner()


def _outcome(
    success: bool = True,
    overall: GuardrailStatus = GuardrailStatus.PASS,
) -> PipelineOutcome:
    now = datetime.now(UTC)
    return PipelineOutcome(
        ticker="1846.HK",
        started_at=now,
        finished_at=now,
        success=success,
        stages=[
            StageOutcome(
                stage=PipelineStage.CHECK_INGESTION,
                status="ok",
                duration_ms=1,
                message="stub",
            )
        ],
        guardrails=AggregatedResults(
            total=1, by_status={overall: 1}, overall=overall, results=[]
        ),
    )


@pytest.fixture(autouse=True)
def _isolated_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir",
        tmp_path / "data",
    )


@pytest.fixture(autouse=True)
def _stub_build_coordinator(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``_build_coordinator`` in the CLI so we never touch the
    real FMP / yfinance / LLM constructors during CLI tests."""
    from portfolio_thesis_engine.cli import process_cmd

    fake_coord = MagicMock()
    monkeypatch.setattr(process_cmd, "_build_coordinator", lambda ticker: fake_coord)
    return fake_coord


@pytest.fixture
def _fake_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stub both resolver helpers so the CLI tests don't need real
    DocumentRepository lookups or ~/data_inputs files."""
    wacc = tmp_path / "wacc_inputs.md"
    wacc.write_text("stub", encoding="utf-8")
    extraction = tmp_path / "raw_extraction.yaml"
    extraction.write_text("stub", encoding="utf-8")

    from portfolio_thesis_engine.cli import process_cmd

    monkeypatch.setattr(
        process_cmd, "_resolve_wacc_path", lambda ticker, explicit: wacc
    )
    monkeypatch.setattr(
        process_cmd,
        "_resolve_extraction_path",
        lambda ticker, explicit: extraction,
    )
    return {"wacc": wacc, "extraction": extraction}


# ======================================================================
# 1. Happy path
# ======================================================================


class TestProcessCLIHappy:
    def test_exit_zero_on_pass(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(return_value=_outcome())
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 0, result.output
        assert "1846.HK" in result.output
        assert "Guardrails" in result.output

    def test_explicit_wacc_and_extraction_paths_used(
        self,
        _stub_build_coordinator: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from portfolio_thesis_engine.cli import process_cmd

        wacc = tmp_path / "wacc.md"
        wacc.write_text("stub", encoding="utf-8")
        extraction = tmp_path / "extraction.yaml"
        extraction.write_text("stub", encoding="utf-8")
        # Un-stub resolvers so the real path-validation code runs.
        monkeypatch.setattr(
            process_cmd, "_resolve_wacc_path", process_cmd._resolve_wacc_path
        )
        monkeypatch.setattr(
            process_cmd,
            "_resolve_extraction_path",
            process_cmd._resolve_extraction_path,
        )
        _stub_build_coordinator.process = AsyncMock(return_value=_outcome())

        result = runner.invoke(
            app,
            [
                "process",
                "1846.HK",
                "--wacc-path",
                str(wacc),
                "--extraction-path",
                str(extraction),
            ],
        )
        assert result.exit_code == 0, result.output

    def test_force_flag_accepted(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(return_value=_outcome())
        result = runner.invoke(app, ["process", "1846.HK", "--force"])
        assert result.exit_code == 0
        kwargs = _stub_build_coordinator.process.await_args.kwargs
        assert kwargs["force"] is True

    def test_skip_cross_check_flag_accepted(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(return_value=_outcome())
        result = runner.invoke(app, ["process", "1846.HK", "--skip-cross-check"])
        assert result.exit_code == 0
        kwargs = _stub_build_coordinator.process.await_args.kwargs
        assert kwargs["skip_cross_check"] is True

    def test_force_cost_override_flag_accepted(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(return_value=_outcome())
        result = runner.invoke(app, ["process", "1846.HK", "--force-cost-override"])
        assert result.exit_code == 0
        kwargs = _stub_build_coordinator.process.await_args.kwargs
        assert kwargs["force_cost_override"] is True


# ======================================================================
# 2. Exit codes
# ======================================================================


class TestProcessCLIExit:
    def test_cross_check_blocked_exit_1(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(
            side_effect=CrossCheckBlocked("overall=FAIL")
        )
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 1
        assert "Cross-check blocked" in result.output

    def test_extraction_validation_blocked_exit_1(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(
            side_effect=ExtractionValidationBlocked("S.BS FAIL")
        )
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 1
        assert "Extraction validation blocked" in result.output

    def test_pipeline_error_exit_2(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(
            side_effect=PipelineError("no documents ingested")
        )
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 2
        assert "Pipeline error" in result.output

    def test_guardrail_fail_exit_2(
        self,
        _stub_build_coordinator: MagicMock,
        _fake_paths: dict[str, Path],
    ) -> None:
        _stub_build_coordinator.process = AsyncMock(
            return_value=_outcome(success=False, overall=GuardrailStatus.FAIL)
        )
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 2

    def test_missing_wacc_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Don't use _fake_paths: let the real resolver try and fail.
        from portfolio_thesis_engine.cli import process_cmd

        monkeypatch.setattr(
            process_cmd.DocumentRepository,
            "list_documents",
            lambda self, ticker: [],
        )
        result = runner.invoke(app, ["process", "1846.HK"])
        assert result.exit_code == 2
        assert "wacc_inputs.md" in result.output


# ======================================================================
# 3. Help surface
# ======================================================================


class TestProcessCLIHelp:
    def test_help_lists_flags(self) -> None:
        result = runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output
        assert "--skip-cross-check" in result.output
        assert "--force-cost-override" in result.output
        assert "--wacc-path" in result.output
        assert "--extraction-path" in result.output
