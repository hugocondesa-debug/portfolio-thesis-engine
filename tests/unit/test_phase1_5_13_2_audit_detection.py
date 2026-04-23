"""Phase 1.5.13.2 regression tests — audit_status detection +
period label qualifier parsing + cross-check skip for REVIEWED.

14 tests:

_peek_audit_metadata 3-tier resolution (6):
- ``test_peek_reads_top_level_audit_status``
- ``test_peek_falls_back_to_primary_period_audit_status``
- ``test_peek_derives_from_interim_document_type``
- ``test_peek_derives_from_preliminary_document_type``
- ``test_peek_derives_from_investor_presentation_type``
- ``test_peek_annual_report_default_audited``

Period label parser + matcher (5):
- ``test_parse_period_label_unqualified``
- ``test_parse_period_label_preliminary_qualifier``
- ``test_parse_period_label_audited_qualifier``
- ``test_match_period_preliminary_matches_unaudited``
- ``test_match_period_qualifier_conflict_rejected``

Integration (2):
- ``test_latest_audited_skips_interim_correctly``
- ``test_explicit_fy2025_preliminary_matches_preliminary_yaml``

Cross-check skip (1):
- ``test_cross_check_skipped_for_reviewed``
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.pipeline.coordinator import (
    PipelineCoordinator,
    PipelineOutcome,
    PipelineStage,
    _audit_from_document_type,
    _match_period,
    _parse_period_label,
    _peek_audit_metadata,
)


def _write_yaml(
    path: Path,
    *,
    document_type: str = "annual_report",
    audit_status: str | None = "audited",
    period: str = "FY2024",
    period_audit_status: str | None = None,
) -> None:
    """Craft a minimal raw_extraction YAML. ``audit_status=None`` writes
    no top-level key; ``period_audit_status`` adds per-period key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta_lines = [
        "metadata:",
        "  ticker: TST",
        "  company_name: Test Co",
        f"  document_type: {document_type}",
        "  extraction_type: numeric",
        "  reporting_currency: USD",
        "  unit_scale: units",
        '  extraction_date: "2025-01-01"',
    ]
    if audit_status is not None:
        meta_lines.append(f"  audit_status: {audit_status}")
    meta_lines.append("  fiscal_periods:")
    meta_lines.append(f"    - period: {period}")
    meta_lines.append('      end_date: "2025-12-31"')
    meta_lines.append("      is_primary: true")
    if period_audit_status is not None:
        meta_lines.append(f"      audit_status: {period_audit_status}")
    body = "\n".join(meta_lines) + "\n"
    body += (
        f"income_statement:\n"
        f"  {period}:\n"
        f"    line_items:\n"
        f"      - order: 1\n"
        f"        label: Revenue\n"
        f"        value: '1000'\n"
        f"balance_sheet:\n"
        f"  {period}:\n"
        f"    line_items:\n"
        f"      - order: 1\n"
        f"        label: Total assets\n"
        f"        value: '1000'\n"
        f"        section: total_assets\n"
        f"        is_subtotal: true\n"
    )
    path.write_text(body, encoding="utf-8")


# ======================================================================
# _peek_audit_metadata — 3-tier resolution
# ======================================================================


class TestPeekAuditResolution:
    def test_peek_reads_top_level_audit_status(self, tmp_path: Path) -> None:
        p = tmp_path / "a.yaml"
        _write_yaml(p, audit_status="unaudited", document_type="annual_report")
        audit, doc, period = _peek_audit_metadata(p)
        # Top-level wins even when document_type would imply 'audited'.
        assert audit == "unaudited"
        assert doc == "annual_report"

    def test_peek_falls_back_to_primary_period_audit_status(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "a.yaml"
        # No top-level audit_status; per-period "reviewed" wins.
        _write_yaml(
            p,
            audit_status=None,
            document_type="annual_report",
            period_audit_status="reviewed",
        )
        audit, _doc, _period = _peek_audit_metadata(p)
        assert audit == "reviewed"

    def test_peek_derives_from_interim_document_type(
        self, tmp_path: Path
    ) -> None:
        """Interim reports with no audit_status anywhere default to
        'reviewed' (ISRE 2410)."""
        p = tmp_path / "a.yaml"
        _write_yaml(
            p, audit_status=None, document_type="interim_report",
            period="H1_2025",
        )
        audit, doc, _ = _peek_audit_metadata(p)
        assert audit == "reviewed"
        assert doc == "interim_report"

    def test_peek_derives_from_preliminary_document_type(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "a.yaml"
        _write_yaml(
            p,
            audit_status=None,
            document_type="preliminary_results",
            period="FY2025",
        )
        audit, doc, _ = _peek_audit_metadata(p)
        assert audit == "unaudited"
        assert doc == "preliminary_results"

    def test_peek_derives_from_investor_presentation_type(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "a.yaml"
        _write_yaml(
            p,
            audit_status=None,
            document_type="investor_presentation",
            period="FY2025",
        )
        audit, _, _ = _peek_audit_metadata(p)
        assert audit == "unaudited"

    def test_peek_annual_report_default_audited(self, tmp_path: Path) -> None:
        p = tmp_path / "a.yaml"
        _write_yaml(p, audit_status=None, document_type="annual_report")
        audit, _, _ = _peek_audit_metadata(p)
        assert audit == "audited"

    def test_audit_from_document_type_known_and_unknown(self) -> None:
        assert _audit_from_document_type("annual_report") == "audited"
        assert _audit_from_document_type("interim_report") == "reviewed"
        assert _audit_from_document_type("preliminary_results") == "unaudited"
        assert _audit_from_document_type("investor_presentation") == "unaudited"
        # Unknown types fall back to audited (safest default).
        assert _audit_from_document_type("some_new_doc_type") == "audited"


# ======================================================================
# Period label parser + matcher
# ======================================================================


class TestPeriodLabelParserAndMatcher:
    def test_parse_period_label_unqualified(self) -> None:
        assert _parse_period_label("FY2024") == ("FY2024", None)
        assert _parse_period_label("H1_2025") == ("H1_2025", None)

    def test_parse_period_label_preliminary_qualifier(self) -> None:
        base, q = _parse_period_label("FY2025-preliminary")
        assert base == "FY2025"
        assert q == "preliminary"

    def test_parse_period_label_audited_qualifier(self) -> None:
        assert _parse_period_label("FY2024-audited") == ("FY2024", "audited")
        assert _parse_period_label("FY2024-reviewed") == ("FY2024", "reviewed")
        assert _parse_period_label("FY2024-unaudited") == (
            "FY2024", "unaudited"
        )

    def test_match_period_preliminary_matches_unaudited(self) -> None:
        # Candidate period="FY2025" + audit=unaudited → matches
        # "FY2025-preliminary".
        assert _match_period("unaudited", "FY2025", "FY2025-preliminary")
        # Candidate audit=audited → fails qualifier check.
        assert not _match_period("audited", "FY2025", "FY2025-preliminary")

    def test_match_period_qualifier_conflict_rejected(self) -> None:
        # Target asks for audited FY2024; candidate is unaudited.
        assert not _match_period("unaudited", "FY2024", "FY2024-audited")
        # Target asks for reviewed; candidate is audited.
        assert not _match_period("audited", "H1_2025", "H1_2025-reviewed")
        # Matching base + audit combo succeeds.
        assert _match_period("reviewed", "H1_2025", "H1_2025-reviewed")

    def test_match_period_literal_equality_wins(self) -> None:
        """Some extractions bake the qualifier into the period label
        (e.g. ``period: FY2025-preliminary``). Literal equality still
        matches."""
        assert _match_period(
            "unaudited", "FY2025-preliminary", "FY2025-preliminary"
        )


# ======================================================================
# Integration — EuroEyes-style corpus with correct audit detection
# ======================================================================


class TestLatestAuditedWithInterim:
    def test_latest_audited_skips_interim_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression for the Phase 1.5.13.2 root bug: interim YAMLs
        with only per-period ``audit_status`` used to default to
        'audited' and beat real ARs in ``LATEST-AUDITED``. Now they're
        correctly classified as 'reviewed' (document-type default) and
        skipped."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        base = tmp_path / "data_inputs" / "TST"
        ar = base / "raw_extraction_ar_2024.yaml"
        interim = base / "raw_extraction_interim_h1_2025.yaml"
        _write_yaml(
            ar, document_type="annual_report",
            audit_status="audited", period="FY2024",
        )
        # Interim has NO top-level audit_status — document-type default
        # kicks in.
        _write_yaml(
            interim,
            document_type="interim_report",
            audit_status=None,
            period="H1_2025",
        )
        # Force interim to be newer than AR.
        import os
        import time

        now = time.time()
        os.utime(ar, (now - 1000, now - 1000))
        os.utime(interim, (now, now))

        coord = PipelineCoordinator(
            document_repo=MagicMock(
                list_documents=MagicMock(return_value=[])
            ),
            metadata_repo=MagicMock(),
            cross_check_gate=MagicMock(),
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        outcome = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        selected = coord._select_base_extraction(
            ticker="TST",
            base_period="LATEST-AUDITED",
            outcome=outcome,
        )
        # Must pick the AR, not the interim.
        assert selected == ar


class TestExplicitQualifierSelection:
    def test_explicit_fy2025_preliminary_matches_preliminary_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--base-period FY2025-preliminary`` selects the investor
        presentation YAML (period=FY2025, audit=unaudited) over any
        same-period audited sibling."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        base = tmp_path / "data_inputs" / "TST"
        prelim = base / "raw_extraction_prelim.yaml"
        # Preliminary stores period as clean base 'FY2025' + audit via
        # document-type default (investor_presentation → unaudited).
        _write_yaml(
            prelim,
            document_type="investor_presentation",
            audit_status=None,
            period="FY2025",
        )
        coord = PipelineCoordinator(
            document_repo=MagicMock(
                list_documents=MagicMock(return_value=[])
            ),
            metadata_repo=MagicMock(),
            cross_check_gate=MagicMock(),
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        outcome = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        selected = coord._select_base_extraction(
            ticker="TST",
            base_period="FY2025-preliminary",
            outcome=outcome,
        )
        assert selected == prelim


# ======================================================================
# Cross-check skip for REVIEWED
# ======================================================================


class TestCrossCheckSkipReviewed:
    @pytest.mark.asyncio
    async def test_cross_check_skipped_for_reviewed(
        self, wacc_inputs
    ) -> None:
        """Phase 1.5.13.2 extends the cross-check SKIP-when-no-external-
        source logic from UNAUDITED-only to also include REVIEWED —
        interim reports carry H1 figures that don't map to FMP's
        annual snapshots."""
        from .conftest import build_raw

        raw = build_raw(
            audit_status="reviewed",
            document_type="interim_report",
        )
        gate = MagicMock()
        gate.check = MagicMock(
            side_effect=AssertionError("cross-check gate should not run")
        )
        coord = PipelineCoordinator(
            document_repo=MagicMock(),
            metadata_repo=MagicMock(),
            cross_check_gate=gate,
            extraction_coordinator=MagicMock(),
            state_repo=MagicMock(),
        )
        outcome = PipelineOutcome(
            ticker="TST",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            success=False,
            stages=[],
        )
        result = await coord._stage_cross_check(
            ticker="TST",
            raw_extraction=raw,
            outcome=outcome,
            skip_cross_check=False,
        )
        assert result is None
        stage = outcome.stages[-1]
        assert stage.stage == PipelineStage.CROSS_CHECK
        assert stage.status == "skip"
        assert "reviewed" in stage.message.lower()
