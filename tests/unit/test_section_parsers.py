"""Unit tests for section_extractor Pass 2 (per-section parsing)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.ingestion.base import IngestedDocument
from portfolio_thesis_engine.llm.base import LLMResponse
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.section_extractor.p1_extractor import (
    P1IndustrialExtractor,
)
from portfolio_thesis_engine.section_extractor.tools import (
    BALANCE_SHEET_TOOL_NAME,
    CASH_FLOW_TOOL_NAME,
    INCOME_STATEMENT_TOOL_NAME,
    LEASES_TOOL_NAME,
    MDA_TOOL_NAME,
    REPORT_SECTIONS_TOOL_NAME,
    SECTION_TOOLS,
    SEGMENTS_TOOL_NAME,
    TAX_RECON_TOOL_NAME,
)
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

_SYNTH_DOC = """# Report

## 2. Consolidated Income Statement (FY2024)
Revenue: 100. Operating income: 20. Net income: 12.

## 3. Consolidated Balance Sheet (FY2024)
Total assets: 500. Total liabilities: 200. Total equity: 300.

## 4. Consolidated Cash Flow Statement (FY2024)
CFO: 30. CFI: -15. CFF: -5.

## 5. Segment Information
Greater China: Revenue 70. Europe: Revenue 30.

## 6. Notes

### Note 7 — Income Tax Reconciliation
Statutory 16.5%. Effective 20%.

### Note 8 — Leases (IFRS 16)
ROU assets: 100. Lease liabilities: 80.

## 7. Management Discussion & Analysis
Revenue grew on China volume. Margin up.
"""


# ----------------------------------------------------------------------
# Mocked responses per section type + a TOC that points at every P1 section
# ----------------------------------------------------------------------


def _toc_response() -> LLMResponse:
    return LLMResponse(
        content="",
        structured_output={
            "primary_fiscal_period": "FY2024",
            "sections": [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    "end_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                },
                {
                    "section_type": "balance_sheet",
                    "title": "BS",
                    "start_marker": "## 3. Consolidated Balance Sheet (FY2024)",
                    "end_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                },
                {
                    "section_type": "cash_flow",
                    "title": "CF",
                    "start_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                    "end_marker": "## 5. Segment Information",
                },
                {
                    "section_type": "segments",
                    "title": "Segments",
                    "start_marker": "## 5. Segment Information",
                    "end_marker": "## 6. Notes",
                },
                {
                    "section_type": "notes_taxes",
                    "title": "Taxes",
                    "start_marker": "### Note 7 — Income Tax Reconciliation",
                    "end_marker": "### Note 8 — Leases (IFRS 16)",
                },
                {
                    "section_type": "notes_leases",
                    "title": "Leases",
                    "start_marker": "### Note 8 — Leases (IFRS 16)",
                    "end_marker": "## 7. Management Discussion & Analysis",
                },
                {
                    "section_type": "mda",
                    "title": "MD&A",
                    "start_marker": "## 7. Management Discussion & Analysis",
                },
            ],
        },
        input_tokens=500,
        output_tokens=100,
        cost_usd=Decimal("0.001"),
        model_used="claude-sonnet-4-6",
    )


def _is_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "currency": "HKD",
        "currency_unit": "millions",
        "line_items": [
            {"label": "Revenue", "value_current": 100, "category": "revenue"},
            {
                "label": "Operating income",
                "value_current": 20,
                "category": "operating_income",
            },
            {"label": "Net income", "value_current": 12, "category": "net_income"},
        ],
    }


def _bs_parsed() -> dict:
    return {
        "as_of_date": "2024-12-31",
        "currency": "HKD",
        "currency_unit": "millions",
        "line_items": [
            {"label": "Total assets", "value_current": 500, "category": "total_assets"},
            {
                "label": "Total liabilities",
                "value_current": 200,
                "category": "total_liabilities",
            },
            {"label": "Total equity", "value_current": 300, "category": "total_equity"},
        ],
    }


def _cf_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "currency": "HKD",
        "currency_unit": "millions",
        "line_items": [
            {"label": "CFO", "value_current": 30, "category": "cfo"},
            {"label": "CFI", "value_current": -15, "category": "cfi"},
            {"label": "CFF", "value_current": -5, "category": "cff"},
            {
                "label": "Net change in cash",
                "value_current": 10,
                "category": "net_change_in_cash",
            },
        ],
    }


def _segments_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "segments": [
            {
                "name": "Greater China",
                "dimension": "geography",
                "currency": "HKD",
                "revenue": 70,
            },
            {"name": "Europe", "dimension": "geography", "currency": "EUR", "revenue": 30},
        ],
    }


def _tax_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "statutory_rate_pct": 16.5,
        "effective_rate_pct": 20.0,
        "reconciling_items": [
            {"label": "Non-deductible", "amount": 0.5, "category": "non_deductible"}
        ],
        "reported_tax_expense": 2.4,
    }


def _leases_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "currency": "HKD",
        "currency_unit": "millions",
        "rou_assets_by_category": [{"category": "Medical facilities", "value_current": 100}],
        "lease_liability_movement": {"opening_balance": 70, "closing_balance": 80},
    }


def _mda_parsed() -> dict:
    return {
        "fiscal_period": "FY2024",
        "revenue_drivers": ["volume in China"],
        "margin_commentary": "margin expanded",
    }


PARSE_RESPONSES_BY_TOOL: dict[str, dict] = {
    INCOME_STATEMENT_TOOL_NAME: _is_parsed(),
    BALANCE_SHEET_TOOL_NAME: _bs_parsed(),
    CASH_FLOW_TOOL_NAME: _cf_parsed(),
    SEGMENTS_TOOL_NAME: _segments_parsed(),
    TAX_RECON_TOOL_NAME: _tax_parsed(),
    LEASES_TOOL_NAME: _leases_parsed(),
    MDA_TOOL_NAME: _mda_parsed(),
}


def _dispatch_mock(
    toc: LLMResponse,
    parse_by_tool: dict[str, dict | None] | None = None,
    cost_per_call: str = "0.0005",
) -> MagicMock:
    """Return a MagicMock whose ``complete`` dispatches by tool_name.

    Pass 1 (tool name == ``report_sections_found``) returns the TOC
    response. Pass 2 calls look up their tool name in ``parse_by_tool``
    and return a matching structured_output wrapped in an LLMResponse.
    Unknown tools get ``structured_output=None``.
    """
    parse_by_tool = parse_by_tool or {}
    llm = MagicMock()

    async def complete(request):
        tool_names = [t["name"] for t in (request.tools or [])]
        if REPORT_SECTIONS_TOOL_NAME in tool_names:
            return toc
        for name in tool_names:
            if name in parse_by_tool:
                return LLMResponse(
                    content="",
                    structured_output=parse_by_tool[name],
                    input_tokens=200,
                    output_tokens=50,
                    cost_usd=Decimal(cost_per_call),
                    model_used="claude-sonnet-4-6",
                )
        return LLMResponse(
            content="",
            structured_output=None,
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            model_used="claude-sonnet-4-6",
        )

    llm.complete = AsyncMock(side_effect=complete)
    return llm


def _make_document(tmp_path: Path, content: str) -> IngestedDocument:
    path = tmp_path / "doc.md"
    path.write_text(content, encoding="utf-8")
    return IngestedDocument(
        doc_id="1846-HK/annual_report/doc.md",
        ticker="1846-HK",
        doc_type="annual_report",
        source_path=path,
        report_date="2024-12-31",
        content_hash="x" * 64,
        ingested_at=datetime.now(UTC),
        mode="bulk_markdown",
    )


# ======================================================================
# Dispatch table shape
# ======================================================================


class TestSectionToolsTable:
    def test_covers_7_parseable_sections(self) -> None:
        expected = {
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "segments",
            "notes_leases",
            "notes_taxes",
            "mda",
        }
        assert set(SECTION_TOOLS.keys()) == expected

    def test_each_entry_is_tool_operation_pair(self) -> None:
        for section_type, (tool, operation) in SECTION_TOOLS.items():
            assert tool["name"], f"{section_type}: tool has no name"
            assert operation.startswith("section_parse_"), (
                f"{section_type}: operation should start with section_parse_, got {operation}"
            )

    def test_category_enum_on_is_tool(self) -> None:
        items = SECTION_TOOLS["income_statement"][0]["input_schema"]["properties"]["line_items"][
            "items"
        ]
        enum = items["properties"]["category"]["enum"]
        assert "revenue" in enum
        assert "operating_income" in enum
        assert "tax" in enum


# ======================================================================
# Happy path — Pass 2 fills parsed_data for each parseable section
# ======================================================================


class TestPass2Parsing:
    @pytest.mark.asyncio
    async def test_every_parseable_section_has_parsed_data(self, tmp_path: Path) -> None:
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))

        by_type = {s.section_type: s for s in result.sections}
        # IS/BS/CF/segments/taxes/leases/mda all have parsed_data
        for parseable in (
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "segments",
            "notes_taxes",
            "notes_leases",
            "mda",
        ):
            assert by_type[parseable].parsed_data is not None, (
                f"{parseable} should have parsed_data after Pass 2"
            )

    @pytest.mark.asyncio
    async def test_is_shape_matches_mock(self, tmp_path: Path) -> None:
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        assert is_section.parsed_data["currency"] == "HKD"
        assert is_section.parsed_data["currency_unit"] == "millions"
        line_labels = [li["label"] for li in is_section.parsed_data["line_items"]]
        assert "Revenue" in line_labels
        assert "Net income" in line_labels

    @pytest.mark.asyncio
    async def test_parallel_calls_count_matches_parseable_sections(self, tmp_path: Path) -> None:
        """1 Pass 1 + 7 Pass 2 (one per parseable section type) = 8 calls."""
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert llm.complete.await_count == 8

    @pytest.mark.asyncio
    async def test_each_parse_call_records_distinct_operation(self, tmp_path: Path) -> None:
        """Cost tracker should have one entry per tool type."""
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        operations = {e.operation for e in tracker.session_entries()}
        # Pass 1 operation
        assert "section_toc" in operations
        # 7 Pass 2 operations
        assert operations - {"section_toc"} == {
            "section_parse_is",
            "section_parse_bs",
            "section_parse_cf",
            "section_parse_segments",
            "section_parse_leases",
            "section_parse_tax",
            "section_parse_mda",
        }


# ======================================================================
# Passthrough behaviour
# ======================================================================


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_unparseable_section_kept_with_parsed_data_none(self, tmp_path: Path) -> None:
        """A section type without a SECTION_TOOLS entry keeps its content
        but gets parsed_data=None (no Pass 2 call for it)."""
        only_passthrough_toc = LLMResponse(
            content="",
            structured_output={
                "primary_fiscal_period": "FY2024",
                "sections": [
                    {
                        "section_type": "operating_data",
                        "title": "Ops",
                        "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                    }
                ],
            },
            input_tokens=100,
            output_tokens=20,
            cost_usd=Decimal("0.0005"),
            model_used="claude-sonnet-4-6",
        )
        llm = _dispatch_mock(only_passthrough_toc)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert len(result.sections) == 1
        assert result.sections[0].parsed_data is None
        # Only Pass 1 runs — no Pass 2 call for this section
        assert llm.complete.await_count == 1

    @pytest.mark.asyncio
    async def test_parse_returning_none_preserved(self, tmp_path: Path) -> None:
        """If the LLM fails to invoke the parse tool (structured_output=None),
        the section's parsed_data stays None — not a crash."""
        llm = _dispatch_mock(
            _toc_response(),
            parse_by_tool={INCOME_STATEMENT_TOOL_NAME: None},
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        assert is_section.parsed_data is None


# ======================================================================
# Concurrency
# ======================================================================


class TestConcurrencyBound:
    @pytest.mark.asyncio
    async def test_max_concurrent_semaphore_applied(self, tmp_path: Path) -> None:
        """With max_concurrent=2, at most 2 Pass 2 calls are in flight
        at any moment. We count peak concurrency via a shared counter."""
        in_flight = 0
        peak = 0
        lock = None  # use asyncio.Lock inside complete() lazily

        import asyncio

        async def complete(request):
            nonlocal in_flight, peak, lock
            if lock is None:
                lock = asyncio.Lock()
            tool_names = [t["name"] for t in (request.tools or [])]
            if REPORT_SECTIONS_TOOL_NAME in tool_names:
                return _toc_response()
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                # Simulate LLM latency so multiple calls overlap
                await asyncio.sleep(0.02)
            finally:
                async with lock:
                    in_flight -= 1
            return LLMResponse(
                content="",
                structured_output=PARSE_RESPONSES_BY_TOOL.get(tool_names[0]),
                input_tokens=100,
                output_tokens=20,
                cost_usd=Decimal("0.0005"),
                model_used="claude-sonnet-4-6",
            )

        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=complete)

        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker, max_concurrent=2)
        await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        assert peak <= 2, f"peak concurrency {peak} exceeded max_concurrent=2"


# ======================================================================
# Cost cap
# ======================================================================


class TestCostCap:
    @pytest.mark.asyncio
    async def test_cap_raises_before_toc_if_already_over(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-populate the tracker so total > cap; extractor must raise
        before issuing any LLM call."""
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.llm_max_cost_per_company_usd",
            0.5,
        )
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        tracker.record(
            operation="prior_run",
            model="x",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0.75"),
            ticker="1846-HK",
        )
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)

        with pytest.raises(CostLimitExceededError):
            await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        # No LLM call should have been issued
        assert llm.complete.await_count == 0


# ======================================================================
# Order / content preserved
# ======================================================================


class TestContentPreservation:
    @pytest.mark.asyncio
    async def test_raw_content_unchanged_by_pass_2(self, tmp_path: Path) -> None:
        """Pass 2 must not alter a section's raw content slice."""
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        assert is_section.content.startswith("## 2. Consolidated Income Statement (FY2024)")
        assert "Revenue: 100" in is_section.content

    @pytest.mark.asyncio
    async def test_section_order_stable_after_parallel_parse(self, tmp_path: Path) -> None:
        """asyncio.gather preserves input order even when tasks finish
        out-of-order."""
        llm = _dispatch_mock(_toc_response(), PARSE_RESPONSES_BY_TOOL)
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path, _SYNTH_DOC))
        # Sections come back in the original TOC/document order
        types = [s.section_type for s in result.sections]
        # First three must be IS → BS → CF (as laid out in _SYNTH_DOC)
        assert types[:3] == ["income_statement", "balance_sheet", "cash_flow"]
