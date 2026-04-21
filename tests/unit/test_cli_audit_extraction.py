"""Unit tests for ``pte audit-extraction``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app

runner = CliRunner()

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


@pytest.fixture
def _ingested_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Place a copy of the fixture where the DocumentRepository can
    find it for the ticker."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )
    doc_path = data_dir / "documents" / "1846-HK" / "raw_extraction" / "raw_extraction.yaml"
    doc_path.parent.mkdir(parents=True)
    shutil.copyfile(_FIXTURE, doc_path)
    return doc_path


class TestAuditExtraction:
    def test_resolves_ingested_copy(self, _ingested_extraction: Path) -> None:
        result = runner.invoke(app, ["audit-extraction", "1846.HK"])
        # The fixture should parse + validate; exit 0 or 1 (warns).
        assert result.exit_code in (0, 1), result.output
        assert "Auditing" in result.output

    def test_missing_extraction_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point data_dir at an empty tree so the DocumentRepository
        # sees nothing, and home directory at tmp_path so the default
        # layout also misses.
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.data_dir",
            tmp_path / "data",
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "pathlib.Path.home", classmethod(lambda cls: tmp_path)
        )
        result = runner.invoke(app, ["audit-extraction", "1846.HK"])
        assert result.exit_code == 2
        assert "raw_extraction.yaml" in result.output

    def test_resolves_home_data_inputs_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the doc repo is empty but ``~/data_inputs/{ticker}/
        raw_extraction.yaml`` exists, the resolver picks it up."""
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.data_dir",
            tmp_path / "data",
        )
        monkeypatch.setattr(
            "pathlib.Path.home", classmethod(lambda cls: tmp_path)
        )
        # Copy fixture to tmp's data_inputs layout.
        home_target = tmp_path / "data_inputs" / "1846-HK" / "raw_extraction.yaml"
        home_target.parent.mkdir(parents=True)
        shutil.copyfile(_FIXTURE, home_target)

        result = runner.invoke(app, ["audit-extraction", "1846.HK"])
        assert result.exit_code in (0, 1), result.output

    def test_help_lists_flags(self) -> None:
        result = runner.invoke(app, ["audit-extraction", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
