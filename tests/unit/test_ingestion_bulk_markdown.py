"""Unit tests for ingestion.bulk_markdown."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.bulk_markdown import (
    BulkMarkdownMode,
    _infer_doc_type,
    _infer_report_date,
)
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository


@pytest.fixture
def doc_repo(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(base_path=tmp_path / "docs")


@pytest.fixture
def mode(doc_repo: DocumentRepository) -> BulkMarkdownMode:
    return BulkMarkdownMode(doc_repo)


# ======================================================================
# Filename heuristics
# ======================================================================


class TestDocTypeInference:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("annual_report_2024.md", "annual_report"),
            ("AR_2024.md", "annual_report"),
            ("company_ar_full.md", "annual_report"),
            ("interim_h1_2025.md", "interim_report"),
            ("Q3_2024.md", "interim_report"),
            ("H1_2025.md", "interim_report"),
            ("q1_update.md", "interim_report"),
            ("wacc_inputs.md", "wacc_inputs"),
            ("random_notes.md", "other"),
        ],
    )
    def test_infer(self, tmp_path: Path, name: str, expected: str) -> None:
        assert _infer_doc_type(tmp_path / name) == expected


class TestReportDateInference:
    def test_annual_year_in_filename(self, tmp_path: Path) -> None:
        assert (
            _infer_report_date(tmp_path / "annual_report_2024.md", "annual_report") == "2024-12-31"
        )

    def test_interim_defaults_to_june(self, tmp_path: Path) -> None:
        assert _infer_report_date(tmp_path / "interim_h1_2025.md", "interim_report") == "2025-06-30"

    def test_wacc_returns_none(self, tmp_path: Path) -> None:
        assert _infer_report_date(tmp_path / "wacc_inputs.md", "wacc_inputs") is None

    def test_no_year_returns_none(self, tmp_path: Path) -> None:
        assert _infer_report_date(tmp_path / "random.md", "other") is None


# ======================================================================
# validate()
# ======================================================================


class TestValidate:
    def test_happy_path(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        f = tmp_path / "annual_report_2024.md"
        f.write_text("# Report\n\nRevenue: 100. Total assets: 500.\n")
        assert mode.validate([f]) == []

    def test_empty_list_fatal(self, mode: BulkMarkdownMode) -> None:
        errors = mode.validate([])
        assert any("FATAL" in e and "no files" in e for e in errors)

    def test_missing_file_fatal(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        errors = mode.validate([tmp_path / "ghost.md"])
        assert any("FATAL" in e and "does not exist" in e for e in errors)

    def test_empty_file_fatal(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("")
        errors = mode.validate([f])
        assert any("FATAL" in e and "empty" in e for e in errors)

    def test_non_utf8_fatal(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_bytes(b"\xff\xfe invalid utf8 bytes")
        errors = mode.validate([f])
        assert any("FATAL" in e and "UTF-8" in e for e in errors)

    def test_non_financial_warn(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        f = tmp_path / "annual_report_2024.md"
        f.write_text("# My cat loves fish\n\nThis is not a financial document.\n")
        errors = mode.validate([f])
        assert any("WARN" in e and "keywords" in e for e in errors)

    def test_wacc_skips_financial_keyword_check(
        self, mode: BulkMarkdownMode, tmp_path: Path
    ) -> None:
        """WACC files don't contain IS/BS/CF prose; keyword sniff skipped."""
        f = tmp_path / "wacc_inputs.md"
        f.write_text("---\nticker: X\nbeta: 1.0\n---\n")
        errors = mode.validate([f])
        assert not any("keywords" in e for e in errors)

    def test_directory_fatal(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        errors = mode.validate([tmp_path])
        assert any("FATAL" in e and "regular file" in e for e in errors)


# ======================================================================
# ingest()
# ======================================================================


class TestIngest:
    def test_happy_roundtrip(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("# AR\nRevenue 100, assets 500.\n")
        result = mode.ingest("ACME", [ar])
        assert result.ticker == "ACME"
        assert len(result.documents) == 1
        d = result.documents[0]
        assert d.ticker == "ACME"
        assert d.doc_type == "annual_report"
        assert d.report_date == "2024-12-31"
        assert d.content_hash.startswith("")  # 64-hex chars, just assert non-empty
        assert len(d.content_hash) == 64
        assert d.source_path.exists()
        assert d.mode == "bulk_markdown"

    def test_ticker_normalisation(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        f = tmp_path / "annual_report_2024.md"
        f.write_text("# AR\nRevenue 100.\n")
        result = mode.ingest("1846.HK", [f])
        # Filesystem path uses the normalised form
        assert result.ticker == "1846-HK"
        assert "1846-HK" in str(result.documents[0].source_path)

    def test_fatal_validation_raises(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        with pytest.raises(IngestionError):
            mode.ingest("ACME", [tmp_path / "ghost.md"])

    def test_non_financial_warning_surfaces_not_raises(
        self, mode: BulkMarkdownMode, tmp_path: Path
    ) -> None:
        f = tmp_path / "annual_report_2024.md"
        f.write_text("# Not a financial doc\nJust prose.\n")
        result = mode.ingest("ACME", [f])
        # Document still ingested; warning in errors list
        assert len(result.documents) == 1
        assert any("WARN" in e for e in result.errors)

    def test_multiple_files_each_registered(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100, assets 500.\n")
        interim = tmp_path / "interim_h1_2025.md"
        interim.write_text("Revenue 60. Cash 200.\n")
        result = mode.ingest("1846.HK", [ar, interim])
        assert len(result.documents) == 2
        types = {d.doc_type for d in result.documents}
        assert types == {"annual_report", "interim_report"}

    def test_stored_name_includes_report_date(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        ar = tmp_path / "annual_report_2024.md"
        ar.write_text("Revenue 100, assets 500.\n")
        result = mode.ingest("1846.HK", [ar])
        assert "2024-12-31" in result.documents[0].source_path.name

    def test_same_content_produces_same_hash(self, mode: BulkMarkdownMode, tmp_path: Path) -> None:
        """Idempotence check downstream relies on content_hash."""
        a = tmp_path / "a" / "annual_report_2024.md"
        b = tmp_path / "b" / "annual_report_2024.md"
        a.parent.mkdir()
        b.parent.mkdir()
        payload = "Revenue 100. Cash 50. Assets 500.\n"
        a.write_text(payload)
        b.write_text(payload)
        ra = mode.ingest("ACME", [a])
        rb = mode.ingest("BETA", [b])
        assert ra.documents[0].content_hash == rb.documents[0].content_hash
