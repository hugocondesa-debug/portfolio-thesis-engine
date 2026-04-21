"""Unit tests for the ``pte`` CLI.

All command invocations go through :class:`typer.testing.CliRunner` so
there's no subprocess overhead. ``settings.data_dir`` and ``backup_dir``
are monkey-patched per test to isolate filesystem effects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app
from portfolio_thesis_engine.cli.setup_cmd import _touch_gitkeep

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_data_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backup"
    monkeypatch.setattr("portfolio_thesis_engine.shared.config.settings.data_dir", data_dir)
    monkeypatch.setattr("portfolio_thesis_engine.shared.config.settings.backup_dir", backup_dir)


# ======================================================================
# pte setup
# ======================================================================


class TestSetup:
    def test_creates_expected_tree(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["setup"])
        assert result.exit_code == 0, result.output
        data_dir = tmp_path / "data"
        for sub in (
            "yamls/companies",
            "yamls/portfolio/positions",
            "yamls/market_contexts",
            "yamls/library",
            "documents",
        ):
            assert (data_dir / sub).is_dir()
            assert (data_dir / sub / ".gitkeep").is_file()
        assert (tmp_path / "backup").is_dir()

    def test_idempotent_second_run(self) -> None:
        first = runner.invoke(app, ["setup"])
        assert first.exit_code == 0, first.output
        second = runner.invoke(app, ["setup"])
        assert second.exit_code == 0, second.output
        assert "already present" in second.output.lower()

    def test_recreates_missing_directory(self, tmp_path: Path) -> None:
        """If a directory is deleted between runs, setup restores it."""
        runner.invoke(app, ["setup"])
        target = tmp_path / "data" / "documents"
        # Remove the .gitkeep so iterdir returns empty, then rmtree
        import shutil

        shutil.rmtree(target)
        assert not target.exists()
        result = runner.invoke(app, ["setup"])
        assert result.exit_code == 0, result.output
        assert target.is_dir()

    def test_touch_gitkeep_on_empty_dir_creates_file(self, tmp_path: Path) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        assert _touch_gitkeep(d) is True
        assert (d / ".gitkeep").exists()

    def test_touch_gitkeep_on_populated_dir_skips(self, tmp_path: Path) -> None:
        d = tmp_path / "populated"
        d.mkdir()
        (d / "file.txt").write_text("x")
        assert _touch_gitkeep(d) is False
        assert not (d / ".gitkeep").exists()


# ======================================================================
# pte health-check
# ======================================================================


class TestHealthCheck:
    def test_succeeds_after_setup(self) -> None:
        runner.invoke(app, ["setup"])  # create data dirs
        result = runner.invoke(app, ["health-check"])
        assert result.exit_code == 0, result.output
        assert "Health Check" in result.output
        assert "Python" in result.output
        assert "ANTHROPIC_API_KEY" in result.output
        assert "Data directory" in result.output

    def test_warns_when_data_dir_missing_but_does_not_fail(self, tmp_path: Path) -> None:
        # Point data_dir at a path that doesn't exist yet (no setup run)
        result = runner.invoke(app, ["health-check"])
        # Required components (Python, API keys) are OK → exit 0
        assert result.exit_code == 0, result.output
        assert "WARN" in result.output


# ======================================================================
# pte smoke-test
# ======================================================================


class TestSmokeTest:
    def test_mocked_mode_all_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure real-API gate is off regardless of current env
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.smoke_hit_real_apis",
            False,
        )
        result = runner.invoke(app, ["smoke-test"])
        assert result.exit_code == 0, result.output
        assert "4/4 tests passed" in result.output
        assert "Storage roundtrip" in result.output
        assert "Guardrail runner" in result.output
        assert "LLM (mocked)" in result.output
        assert "Embeddings (mocked)" in result.output

    def test_default_help_lists_commands(self) -> None:
        """Typer's --help must enumerate all registered commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "setup" in result.output
        assert "health-check" in result.output
        assert "smoke-test" in result.output
