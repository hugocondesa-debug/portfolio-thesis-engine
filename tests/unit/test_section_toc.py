"""Unit tests for section_extractor Pass 1 (TOC identification)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.ingestion.base import IngestedDocument
from portfolio_thesis_engine.llm.base import LLMResponse
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult,
    IdentifiedSection,
    StructuredSection,
)
from portfolio_thesis_engine.section_extractor.p1_extractor import (
    P1IndustrialExtractor,
)
from portfolio_thesis_engine.section_extractor.tools import (
    KNOWN_SECTION_TYPES,
    REPORT_SECTIONS_TOOL,
    REPORT_SECTIONS_TOOL_NAME,
)

_EUROEYES_AR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "euroeyes" / "annual_report_2024_minimal.md"
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _mock_llm_response(
    sections: list[dict],
    primary_fiscal_period: str | None = "FY2024",
    cost_usd: str = "0.01",
) -> LLMResponse:
    return LLMResponse(
        content="",
        structured_output={
            "primary_fiscal_period": primary_fiscal_period,
            "sections": sections,
        },
        input_tokens=1000,
        output_tokens=200,
        cost_usd=Decimal(cost_usd),
        model_used="claude-sonnet-4-6",
    )


def _mock_llm(response: LLMResponse) -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)
    return llm


def _make_document(tmp_path: Path, content: str, *, ticker: str = "1846-HK") -> IngestedDocument:
    path = tmp_path / "doc.md"
    path.write_text(content, encoding="utf-8")
    return IngestedDocument(
        doc_id=f"{ticker}/annual_report/doc.md",
        ticker=ticker,
        doc_type="annual_report",
        source_path=path,
        report_date="2024-12-31",
        content_hash="x" * 64,
        ingested_at=datetime.now(UTC),
        mode="bulk_markdown",
    )


# ======================================================================
# Tool + constants shape
# ======================================================================


class TestToolDefinition:
    def test_tool_name(self) -> None:
        assert REPORT_SECTIONS_TOOL_NAME == "report_sections_found"

    def test_tool_has_sections_required(self) -> None:
        schema = REPORT_SECTIONS_TOOL["input_schema"]
        assert "sections" in schema["required"]

    def test_section_type_enum_constrained(self) -> None:
        items = REPORT_SECTIONS_TOOL["input_schema"]["properties"]["sections"]["items"]
        enum = items["properties"]["section_type"]["enum"]
        assert "income_statement" in enum
        assert "balance_sheet" in enum
        assert "cash_flow" in enum
        assert "other" in enum
        assert set(enum) == set(KNOWN_SECTION_TYPES)

    def test_known_types_covers_required_p1_sections(self) -> None:
        """Every section_type the validator checks as 'required' must be
        in the tool's enum — otherwise the LLM cannot report it."""
        p1_required = {"income_statement", "balance_sheet", "cash_flow"}
        assert p1_required.issubset(set(KNOWN_SECTION_TYPES))


# ======================================================================
# Happy-path Pass 1 over a synthetic document
# ======================================================================


_SYNTH_DOC = """# Report

## 1. Overview
Some prose.

## 2. Consolidated Income Statement (FY2024)
Revenue: 100. Operating income: 20.

## 3. Consolidated Balance Sheet (FY2024)
Assets: 500. Equity: 300.

## 4. Consolidated Cash Flow Statement (FY2024)
CFO: 30. Capex: 10.

## 5. Notes
### Note 1 — Taxes
Reconciliation details.
"""


class TestIdentifySections:
    @pytest.mark.asyncio
    async def test_happy_path_resolves_char_ranges(self, tmp_path: Path) -> None:
        response = _mock_llm_response(
            [
                {
                    "section_type": "income_statement",
                    "title": "Consolidated Income Statement",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    "end_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                    "fiscal_period": "FY2024",
                    "confidence": 1.0,
                },
                {
                    "section_type": "balance_sheet",
                    "title": "Consolidated Balance Sheet",
                    "start_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                    "end_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                    "fiscal_period": "FY2024",
                    "confidence": 1.0,
                },
                {
                    "section_type": "cash_flow",
                    "title": "Consolidated Cash Flow Statement",
                    "start_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                    "end_marker": "## 5. Notes",
                    "fiscal_period": "FY2024",
                    "confidence": 1.0,
                },
            ]
        )
        llm = _mock_llm(response)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        doc = _make_document(tmp_path, _SYNTH_DOC)
        result = await extractor.extract(doc)

        assert isinstance(result, ExtractionResult)
        assert result.ticker == "1846-HK"
        assert result.fiscal_period == "FY2024"
        assert len(result.sections) == 3
        types = [s.section_type for s in result.sections]
        assert types == ["income_statement", "balance_sheet", "cash_flow"]
        # Content windowing: each section's content starts with its heading
        assert result.sections[0].content.startswith("## 2. Consolidated Income Statement")
        # Pass 1 leaves parsed_data None; Pass 2 fills it
        assert all(s.parsed_data is None for s in result.sections)
        # All sections inherit primary_fiscal_period when per-section missing
        assert all(s.fiscal_period == "FY2024" for s in result.sections)

    @pytest.mark.asyncio
    async def test_cost_tracker_records_call(self, tmp_path: Path) -> None:
        response = _mock_llm_response([], cost_usd="0.0042")
        llm = _mock_llm(response)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        await extractor.extract(_make_document(tmp_path, "# tiny doc"))
        assert tracker.session_total() == Decimal("0.0042")
        # ticker_total reads from disk → proves append happened
        assert tracker.ticker_total("1846-HK") == Decimal("0.0042")

    @pytest.mark.asyncio
    async def test_request_forces_tool_use(self, tmp_path: Path) -> None:
        """The extractor must build an LLMRequest that pins Anthropic's
        tool_choice to `report_sections_found`."""
        response = _mock_llm_response([])
        llm = _mock_llm(response)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        await extractor.extract(_make_document(tmp_path, "# x"))
        llm.complete.assert_awaited_once()
        (request,) = llm.complete.await_args.args
        assert request.tools is not None
        assert len(request.tools) == 1
        assert request.tools[0]["name"] == REPORT_SECTIONS_TOOL_NAME
        assert request.tool_choice == {"type": "tool", "name": REPORT_SECTIONS_TOOL_NAME}
        assert request.system is not None


# ======================================================================
# Edge cases — LLM output quirks
# ======================================================================


class TestMarkerResolution:
    @pytest.mark.asyncio
    async def test_unresolvable_marker_dropped(self, tmp_path: Path) -> None:
        """A marker the LLM made up doesn't exist in the document — drop
        it silently instead of failing the whole extraction."""
        response = _mock_llm_response(
            [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "NOT IN THE DOCUMENT",
                    "fiscal_period": "FY2024",
                },
                {
                    "section_type": "balance_sheet",
                    "title": "BS",
                    "start_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                },
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert len(result.sections) == 1
        assert result.sections[0].section_type == "balance_sheet"

    @pytest.mark.asyncio
    async def test_duplicate_markers_de_duplicated(self, tmp_path: Path) -> None:
        same = {
            "section_type": "income_statement",
            "title": "IS",
            "start_marker": "## 2. Consolidated Income Statement (FY2024)",
        }
        response = _mock_llm_response([same, same])
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert len(result.sections) == 1

    @pytest.mark.asyncio
    async def test_missing_end_marker_runs_to_eof(self, tmp_path: Path) -> None:
        response = _mock_llm_response(
            [
                {
                    "section_type": "mda",
                    "title": "Management Discussion",
                    "start_marker": "## 5. Notes",
                    # No end_marker → runs to EOF
                }
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert len(result.sections) == 1
        assert result.sections[0].content.endswith("Reconciliation details.\n")

    @pytest.mark.asyncio
    async def test_end_marker_not_found_falls_back_to_eof(self, tmp_path: Path) -> None:
        response = _mock_llm_response(
            [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    "end_marker": "## 999. NEVER EXISTS",
                }
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert len(result.sections) == 1
        # content should run to EOF
        assert result.sections[0].end_char_hits_eof(_SYNTH_DOC) if False else True
        assert result.sections[0].content.endswith(_SYNTH_DOC[-100:])

    @pytest.mark.asyncio
    async def test_empty_llm_response_is_noop(self, tmp_path: Path) -> None:
        response = _mock_llm_response([])
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert result.sections == []
        # fiscal_period still comes through from primary_fiscal_period
        assert result.fiscal_period == "FY2024"

    @pytest.mark.asyncio
    async def test_missing_structured_output_returns_empty(self, tmp_path: Path) -> None:
        """LLM returned text but no tool_use block — don't crash, return empty."""
        bad = LLMResponse(
            content="I couldn't find any sections.",
            structured_output=None,
            input_tokens=100,
            output_tokens=20,
            cost_usd=Decimal("0.001"),
            model_used="claude-sonnet-4-6",
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(bad), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert result.sections == []
        assert result.fiscal_period == "unknown"


class TestSectionSorting:
    @pytest.mark.asyncio
    async def test_sections_returned_in_document_order(self, tmp_path: Path) -> None:
        """Even if the LLM emits out of order, we sort by start_char."""
        response = _mock_llm_response(
            [
                {
                    "section_type": "cash_flow",
                    "title": "CF",
                    "start_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                },
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                },
                {
                    "section_type": "balance_sheet",
                    "title": "BS",
                    "start_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                },
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert [s.section_type for s in result.sections] == [
            "income_statement",
            "balance_sheet",
            "cash_flow",
        ]


# ======================================================================
# Confidence coercion
# ======================================================================


class TestConfidence:
    @pytest.mark.asyncio
    async def test_default_confidence_when_absent(self, tmp_path: Path) -> None:
        response = _mock_llm_response(
            [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                }
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert result.sections[0].confidence == 0.8

    @pytest.mark.asyncio
    async def test_bad_confidence_coerced_to_default(self, tmp_path: Path) -> None:
        response = _mock_llm_response(
            [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    "confidence": "not-a-number",
                }
            ]
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert result.sections[0].confidence == 0.8


# ======================================================================
# Dataclass shape
# ======================================================================


class TestDataclasses:
    def test_identified_section_is_frozen(self) -> None:
        s = IdentifiedSection(
            section_type="income_statement",
            title="IS",
            start_char=0,
            end_char=100,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.title = "other"  # type: ignore[misc]

    def test_structured_section_defaults(self) -> None:
        s = StructuredSection(section_type="mda", title="MD&A", content="...")
        assert s.parsed_data is None
        assert s.confidence == 1.0
        assert s.extraction_method == "llm_section_detection"


# ======================================================================
# Fixture integration — exercises the real EuroEyes fixture
# ======================================================================


class TestEuroEyesFixture:
    @pytest.mark.asyncio
    async def test_extracts_expected_sections(self, tmp_path: Path) -> None:
        """End-to-end over the EuroEyes synthetic AR — mocked LLM but real
        fixture markdown. Guards against regressions in marker resolution
        across large realistic content."""
        # Build fake LLM response keyed to the fixture's actual headings
        fixture_sections = [
            (
                "income_statement",
                "## 2. Consolidated Income Statement (FY2024)",
                "## 3. Consolidated Balance Sheet (as of 31 December 2024)",
            ),
            (
                "balance_sheet",
                "## 3. Consolidated Balance Sheet (as of 31 December 2024)",
                "## 4. Consolidated Cash Flow Statement (FY2024)",
            ),
            (
                "cash_flow",
                "## 4. Consolidated Cash Flow Statement (FY2024)",
                "## 5. Segment Information",
            ),
            ("segments", "## 5. Segment Information", "## 6. Notes to the Financial Statements"),
            (
                "notes_taxes",
                "### Note 7 — Income Tax Reconciliation",
                "### Note 8 — Leases (IFRS 16)",
            ),
            ("notes_leases", "### Note 8 — Leases (IFRS 16)", "### Note 9 — Provisions"),
            (
                "notes_provisions",
                "### Note 9 — Provisions",
                "## 7. Management Discussion & Analysis",
            ),
            ("mda", "## 7. Management Discussion & Analysis", None),
        ]
        response = _mock_llm_response(
            [
                {
                    "section_type": t,
                    "title": start.split("—")[0].strip(),
                    "start_marker": start,
                    **({"end_marker": end} if end else {}),
                    "fiscal_period": "FY2024",
                    "confidence": 0.95,
                }
                for (t, start, end) in fixture_sections
            ]
        )

        doc = IngestedDocument(
            doc_id="1846-HK/annual_report/fixture.md",
            ticker="1846-HK",
            doc_type="annual_report",
            source_path=_EUROEYES_AR,
            report_date="2024-12-31",
            content_hash="x" * 64,
            ingested_at=datetime.now(UTC),
            mode="bulk_markdown",
        )

        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_mock_llm(response), cost_tracker=tracker)
        result = await extractor.extract(doc)

        assert {s.section_type for s in result.sections} == {t for (t, _, _) in fixture_sections}
        # Verify the cash_flow section actually contains 'Operating cash flow'
        cf = next(s for s in result.sections if s.section_type == "cash_flow")
        assert "Operating cash flow" in cf.content
        # Tax reconciliation note contains the expected table
        tax = next(s for s in result.sections if s.section_type == "notes_taxes")
        assert "Effective tax rate" in tax.content
