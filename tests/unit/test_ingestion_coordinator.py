"""Unit tests for ingestion.coordinator + ingestion.pre_extracted stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.ingestion.pre_extracted import PreExtractedMode
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository


@pytest.fixture
def doc_repo(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(base_path=tmp_path / "docs")


@pytest.fixture
def meta_repo(tmp_path: Path) -> MetadataRepository:
    return MetadataRepository(db_path=tmp_path / "meta.sqlite")


@pytest.fixture
def coord(doc_repo: DocumentRepository, meta_repo: MetadataRepository) -> IngestionCoordinator:
    return IngestionCoordinator(doc_repo, meta_repo)


class TestPreExtractedStub:
    def test_ingest_raises_not_implemented(self) -> None:
        mode = PreExtractedMode()
        with pytest.raises(NotImplementedError, match="Phase 2"):
            mode.ingest("ACME", [])

    def test_validate_returns_fatal_message(self) -> None:
        errors = PreExtractedMode().validate([])
        assert errors == ["FATAL: PreExtractedMode is Phase 2, use BulkMarkdownMode"]


class TestCoordinatorDispatch:
    def test_bulk_markdown_path(self, coord: IngestionCoordinator, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        result = coord.ingest("1846.HK", [ar], mode="bulk_markdown")
        assert result.ticker == "1846-HK"
        assert len(result.documents) == 1
        # Metadata upsert happened
        c = coord.metadata_repo.get_company("1846.HK")
        assert c is not None
        assert c.profile == "P1"

    def test_unknown_mode_raises(self, coord: IngestionCoordinator, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown ingestion mode"):
            coord.ingest("ACME", [], mode="nonexistent")

    def test_pre_extracted_raises_not_implemented(self, coord: IngestionCoordinator) -> None:
        with pytest.raises(NotImplementedError):
            coord.ingest("ACME", [], mode="pre_extracted")

    def test_profile_override(self, coord: IngestionCoordinator, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        coord.ingest("ACME", [ar], profile="P2")
        c = coord.metadata_repo.get_company("ACME")
        assert c.profile == "P2"

    def test_custom_modes_injected(
        self,
        doc_repo: DocumentRepository,
        meta_repo: MetadataRepository,
        tmp_path: Path,
    ) -> None:
        """Custom mode table replaces the defaults — useful for tests."""
        custom_coord = IngestionCoordinator(doc_repo, meta_repo, modes={})
        with pytest.raises(ValueError, match="Unknown ingestion mode"):
            custom_coord.ingest("ACME", [], mode="bulk_markdown")

    def test_upsert_preserves_existing_data(
        self, coord: IngestionCoordinator, tmp_path: Path
    ) -> None:
        """Second ingest on same ticker doesn't wipe previously-populated columns."""
        # Seed the ticker with richer metadata
        coord.metadata_repo.add_company("ACME", "Acme Industrial", "P1", "USD", "NYSE")
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100. Cash 50. Assets 500.\n")
        coord.ingest("ACME", [ar])
        c = coord.metadata_repo.get_company("ACME")
        # upsert_company(ticker, profile=...) keeps name/currency/exchange intact
        assert c.name == "Acme Industrial"
        assert c.currency == "USD"
        assert c.exchange == "NYSE"
