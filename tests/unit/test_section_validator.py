"""Unit tests for section_extractor Pass 3 (validator)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.ingestion.base import IngestedDocument
from portfolio_thesis_engine.llm.base import LLMResponse
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult,
    StructuredSection,
    ValidationIssue,
)
from portfolio_thesis_engine.section_extractor.p1_extractor import (
    P1IndustrialExtractor,
)
from portfolio_thesis_engine.section_extractor.tools import (
    BALANCE_SHEET_TOOL_NAME,
    CASH_FLOW_TOOL_NAME,
    INCOME_STATEMENT_TOOL_NAME,
    REPORT_SECTIONS_TOOL_NAME,
)
from portfolio_thesis_engine.section_extractor.validator import (
    ExtractionValidator,
    _sum_by_category,
)

# ----------------------------------------------------------------------
# Section factories — build StructuredSection quickly for individual checks
# ----------------------------------------------------------------------


def _is_section(
    line_items: list[dict] | None = None,
    currency: str = "HKD",
    fiscal_period: str = "FY2024",
) -> StructuredSection:
    parsed = {
        "fiscal_period": fiscal_period,
        "currency": currency,
        "currency_unit": "millions",
        "line_items": line_items
        or [
            {"label": "Revenue", "value_current": 100, "category": "revenue"},
            {"label": "COGS", "value_current": -60, "category": "cost_of_sales"},
            {"label": "Opex", "value_current": -20, "category": "opex"},
            {
                "label": "Operating income",
                "value_current": 20,
                "category": "operating_income",
            },
        ],
    }
    return StructuredSection(
        section_type="income_statement",
        title="IS",
        content="",
        parsed_data=parsed,
        fiscal_period=fiscal_period,
    )


def _bs_section(
    assets: float = 500,
    liabilities: float = 200,
    equity: float = 300,
    currency: str = "HKD",
    fiscal_period: str = "FY2024",
) -> StructuredSection:
    parsed = {
        "as_of_date": "2024-12-31",
        "currency": currency,
        "currency_unit": "millions",
        "line_items": [
            {
                "label": "Total assets",
                "value_current": assets,
                "category": "total_assets",
            },
            {
                "label": "Total liabilities",
                "value_current": liabilities,
                "category": "total_liabilities",
            },
            {
                "label": "Total equity",
                "value_current": equity,
                "category": "total_equity",
            },
        ],
    }
    return StructuredSection(
        section_type="balance_sheet",
        title="BS",
        content="",
        parsed_data=parsed,
        fiscal_period=fiscal_period,
    )


def _cf_section(
    cfo: float = 30,
    cfi: float = -15,
    cff: float = -5,
    delta: float = 10,
    currency: str = "HKD",
    fiscal_period: str = "FY2024",
) -> StructuredSection:
    parsed = {
        "fiscal_period": fiscal_period,
        "currency": currency,
        "currency_unit": "millions",
        "line_items": [
            {"label": "CFO", "value_current": cfo, "category": "cfo"},
            {"label": "CFI", "value_current": cfi, "category": "cfi"},
            {"label": "CFF", "value_current": cff, "category": "cff"},
            {
                "label": "Net change",
                "value_current": delta,
                "category": "net_change_in_cash",
            },
        ],
    }
    return StructuredSection(
        section_type="cash_flow",
        title="CF",
        content="",
        parsed_data=parsed,
        fiscal_period=fiscal_period,
    )


def _result(sections: list[StructuredSection]) -> ExtractionResult:
    return ExtractionResult(
        doc_id="1846-HK/annual_report/doc.md",
        ticker="1846-HK",
        fiscal_period="FY2024",
        sections=sections,
    )


# ======================================================================
# _sum_by_category helper
# ======================================================================


class TestSumByCategory:
    def test_groups_and_sums(self) -> None:
        items = [
            {"label": "A", "value_current": 10, "category": "revenue"},
            {"label": "B", "value_current": 5, "category": "revenue"},
            {"label": "C", "value_current": -3, "category": "opex"},
        ]
        assert _sum_by_category(items) == {
            "revenue": Decimal("15"),
            "opex": Decimal("-3"),
        }

    def test_skips_items_with_no_category_or_value(self) -> None:
        items = [
            {"label": "A", "value_current": 10, "category": "revenue"},
            {"label": "B"},  # no category/value
            {"label": "C", "category": "opex"},  # no value
        ]
        assert _sum_by_category(items) == {"revenue": Decimal("10")}

    def test_preserves_decimal_precision(self) -> None:
        items = [{"label": "A", "value_current": 123.456789, "category": "revenue"}]
        assert _sum_by_category(items)["revenue"] == Decimal("123.456789")


# ======================================================================
# Core sections present
# ======================================================================


class TestCoreSectionsPresent:
    def test_all_present_no_issues(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(_result([_is_section(), _bs_section(), _cf_section()]))
        severities = [i.severity for i in issues]
        assert "FATAL" not in severities

    def test_missing_is_flagged_fatal(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(_result([_bs_section(), _cf_section()]))
        fatal_msgs = [i.message for i in issues if i.severity == "FATAL"]
        assert any("income_statement" in m for m in fatal_msgs)

    def test_all_missing_yields_three_fatals(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(_result([]))
        fatal_count = sum(1 for i in issues if i.severity == "FATAL")
        assert fatal_count == 3


# ======================================================================
# Fiscal period consistency
# ======================================================================


class TestFiscalPeriodConsistency:
    def test_single_period_ok(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(_result([_is_section(), _bs_section(), _cf_section()]))
        assert not any("fiscal period" in i.message.lower() for i in issues)

    def test_two_periods_tolerated(self) -> None:
        """Current + prior is fine — we don't flag that."""
        validator = ExtractionValidator()
        is_s = _is_section(fiscal_period="FY2024")
        bs_s = _bs_section(fiscal_period="FY2023")  # prior
        cf_s = _cf_section(fiscal_period="FY2024")
        issues = validator.validate(_result([is_s, bs_s, cf_s]))
        assert not any("fiscal period" in i.message.lower() for i in issues)

    def test_three_periods_flagged_warn(self) -> None:
        validator = ExtractionValidator()
        is_s = _is_section(fiscal_period="FY2024")
        bs_s = _bs_section(fiscal_period="FY2023")
        cf_s = _cf_section(fiscal_period="H1 2024")
        issues = validator.validate(_result([is_s, bs_s, cf_s]))
        warns = [i for i in issues if i.severity == "WARN" and "periods" in i.message.lower()]
        assert len(warns) == 1
        assert "periods" in warns[0].details


# ======================================================================
# Currency consistency across IS / BS / CF
# ======================================================================


class TestCurrencyConsistency:
    def test_matching_currencies_no_issue(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(
            _result(
                [
                    _is_section(currency="HKD"),
                    _bs_section(currency="HKD"),
                    _cf_section(currency="HKD"),
                ]
            )
        )
        assert not any("currencies" in i.message.lower() for i in issues)

    def test_mismatched_core_currencies_fatal(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(
            _result(
                [
                    _is_section(currency="HKD"),
                    _bs_section(currency="USD"),
                    _cf_section(currency="HKD"),
                ]
            )
        )
        fatals = [i for i in issues if i.severity == "FATAL"]
        assert any("different currencies" in i.message for i in fatals)


# ======================================================================
# IS arithmetic
# ======================================================================


class TestISArithmetic:
    def test_balanced_is_no_issue(self) -> None:
        """Revenue 100 + COGS (-60) + Opex (-20) = 20 = operating_income."""
        validator = ExtractionValidator()
        issues = validator.validate(_result([_is_section(), _bs_section(), _cf_section()]))
        assert not any("IS arithmetic" in i.message for i in issues)

    def test_is_unbalanced_warn(self) -> None:
        # 100 - 60 - 20 = 20; reported op_income = 40 → 100% off
        line_items = [
            {"label": "Revenue", "value_current": 100, "category": "revenue"},
            {"label": "COGS", "value_current": -60, "category": "cost_of_sales"},
            {"label": "Opex", "value_current": -20, "category": "opex"},
            {
                "label": "Operating income",
                "value_current": 40,
                "category": "operating_income",
            },
        ]
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(line_items), _bs_section(), _cf_section()])
        )
        arith = [i for i in issues if "IS arithmetic" in i.message]
        assert len(arith) == 1
        assert arith[0].severity == "WARN"

    def test_is_missing_revenue_skipped_info(self) -> None:
        line_items = [
            {
                "label": "Operating income",
                "value_current": 40,
                "category": "operating_income",
            },
        ]
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(line_items), _bs_section(), _cf_section()])
        )
        assert any(i.severity == "INFO" and "revenue" in i.message for i in issues)


# ======================================================================
# BS identity
# ======================================================================


class TestBSIdentity:
    def test_balanced_no_issue(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(), _bs_section(500, 200, 300), _cf_section()])
        )
        assert not any("identity" in i.message.lower() for i in issues)

    def test_unbalanced_fatal(self) -> None:
        """assets=500, liab+eq=500 → tolerance breached"""
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(), _bs_section(500, 200, 350), _cf_section()])
        )
        fatals = [i for i in issues if i.severity == "FATAL" and "identity" in i.message]
        assert len(fatals) == 1

    def test_missing_subtotal_warn(self) -> None:
        bs = _bs_section()
        # Strip total_equity from parsed_data
        bs.parsed_data["line_items"] = [
            li for li in bs.parsed_data["line_items"] if li["category"] != "total_equity"
        ]
        validator = ExtractionValidator()
        issues = validator.validate(_result([_is_section(), bs, _cf_section()]))
        warns = [
            i for i in issues if i.severity == "WARN" and "identity check skipped" in i.message
        ]
        assert len(warns) == 1


# ======================================================================
# CF identity
# ======================================================================


class TestCFIdentity:
    def test_balanced_no_issue(self) -> None:
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(), _bs_section(), _cf_section(30, -15, -5, 10)])
        )
        assert not any("Cash-flow" in i.message for i in issues)

    def test_unbalanced_warn(self) -> None:
        """CFO+CFI+CFF = 10 but reported net_change=25 → way off"""
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(), _bs_section(), _cf_section(30, -15, -5, 25)])
        )
        warns = [i for i in issues if i.severity == "WARN" and "Cash-flow" in i.message]
        assert len(warns) == 1

    def test_within_tolerance(self) -> None:
        """CFO+CFI+CFF = 10, reported = 10.1 → 1% off, within 2% tolerance."""
        validator = ExtractionValidator()
        issues = validator.validate(
            _result([_is_section(), _bs_section(), _cf_section(30, -15, -5, 10.1)])
        )
        assert not any("Cash-flow" in i.message for i in issues)


# ======================================================================
# overall_status roll-up
# ======================================================================


class TestOverallStatus:
    def test_empty_issues_yields_pass(self) -> None:
        assert ExtractionValidator.overall_status([]) == GuardrailStatus.PASS

    def test_fatal_beats_warn(self) -> None:
        issues = [
            ValidationIssue(severity="WARN", message="w"),
            ValidationIssue(severity="FATAL", message="f"),
        ]
        assert ExtractionValidator.overall_status(issues) == GuardrailStatus.FAIL

    def test_warn_beats_info(self) -> None:
        issues = [
            ValidationIssue(severity="INFO", message="i"),
            ValidationIssue(severity="WARN", message="w"),
        ]
        assert ExtractionValidator.overall_status(issues) == GuardrailStatus.WARN

    def test_info_only_yields_nota(self) -> None:
        issues = [ValidationIssue(severity="INFO", message="i")]
        assert ExtractionValidator.overall_status(issues) == GuardrailStatus.NOTA


# ======================================================================
# End-to-end — Pass 3 wired into extract()
# ======================================================================


def _toc_response() -> LLMResponse:
    return LLMResponse(
        content="",
        structured_output={
            "primary_fiscal_period": "FY2024",
            "sections": [
                {
                    "section_type": "income_statement",
                    "title": "IS",
                    "start_marker": "## IS",
                    "end_marker": "## BS",
                },
                {
                    "section_type": "balance_sheet",
                    "title": "BS",
                    "start_marker": "## BS",
                    "end_marker": "## CF",
                },
                {
                    "section_type": "cash_flow",
                    "title": "CF",
                    "start_marker": "## CF",
                },
            ],
        },
        input_tokens=200,
        output_tokens=50,
        cost_usd=Decimal("0.001"),
        model_used="claude-sonnet-4-6",
    )


def _dispatch_mock(
    parse_responses: dict[str, dict],
) -> MagicMock:
    llm = MagicMock()

    async def complete(request):
        tool_names = [t["name"] for t in (request.tools or [])]
        if REPORT_SECTIONS_TOOL_NAME in tool_names:
            return _toc_response()
        for name in tool_names:
            if name in parse_responses:
                return LLMResponse(
                    content="",
                    structured_output=parse_responses[name],
                    input_tokens=50,
                    output_tokens=20,
                    cost_usd=Decimal("0.0005"),
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


def _make_document(tmp_path: Path) -> IngestedDocument:
    content = "# Report\n\n## IS\nIS body\n\n## BS\nBS body\n\n## CF\nCF body\n"
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


class TestEndToEndValidation:
    @pytest.mark.asyncio
    async def test_clean_run_yields_pass(self, tmp_path: Path) -> None:
        responses = {
            INCOME_STATEMENT_TOOL_NAME: _is_section().parsed_data,
            BALANCE_SHEET_TOOL_NAME: _bs_section().parsed_data,
            CASH_FLOW_TOOL_NAME: _cf_section().parsed_data,
        }
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_dispatch_mock(responses), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path))
        assert result.overall_status == GuardrailStatus.PASS
        assert result.issues == []

    @pytest.mark.asyncio
    async def test_bs_identity_breaks_yields_fail(self, tmp_path: Path) -> None:
        bad_bs = _bs_section(500, 200, 350)  # 500 != 550
        responses = {
            INCOME_STATEMENT_TOOL_NAME: _is_section().parsed_data,
            BALANCE_SHEET_TOOL_NAME: bad_bs.parsed_data,
            CASH_FLOW_TOOL_NAME: _cf_section().parsed_data,
        }
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=_dispatch_mock(responses), cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path))
        assert result.overall_status == GuardrailStatus.FAIL
        assert any(i.severity == "FATAL" for i in result.issues)

    @pytest.mark.asyncio
    async def test_missing_core_section_yields_fail(self, tmp_path: Path) -> None:
        """TOC only lists IS + CF; BS absent → core-section FATAL."""
        tweaked_toc = LLMResponse(
            content="",
            structured_output={
                "primary_fiscal_period": "FY2024",
                "sections": [
                    {
                        "section_type": "income_statement",
                        "title": "IS",
                        "start_marker": "## IS",
                    },
                    {
                        "section_type": "cash_flow",
                        "title": "CF",
                        "start_marker": "## CF",
                    },
                ],
            },
            input_tokens=100,
            output_tokens=20,
            cost_usd=Decimal("0.0005"),
            model_used="claude-sonnet-4-6",
        )
        llm = MagicMock()

        async def complete(request):
            tool_names = [t["name"] for t in (request.tools or [])]
            if REPORT_SECTIONS_TOOL_NAME in tool_names:
                return tweaked_toc
            if INCOME_STATEMENT_TOOL_NAME in tool_names:
                return LLMResponse(
                    content="",
                    structured_output=_is_section().parsed_data,
                    input_tokens=50,
                    output_tokens=20,
                    cost_usd=Decimal("0.0005"),
                    model_used="claude-sonnet-4-6",
                )
            if CASH_FLOW_TOOL_NAME in tool_names:
                return LLMResponse(
                    content="",
                    structured_output=_cf_section().parsed_data,
                    input_tokens=50,
                    output_tokens=20,
                    cost_usd=Decimal("0.0005"),
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
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)
        result = await extractor.extract(_make_document(tmp_path))
        assert result.overall_status == GuardrailStatus.FAIL
        fatal_msgs = [i.message for i in result.issues if i.severity == "FATAL"]
        assert any("balance_sheet" in m for m in fatal_msgs)


# ======================================================================
# End-to-end with the real EuroEyes fixture (mocked LLM)
# ======================================================================


_EUROEYES_AR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "euroeyes" / "annual_report_2024_minimal.md"
)


class TestEuroEyesEndToEnd:
    @pytest.mark.asyncio
    async def test_fixture_all_passes(self, tmp_path: Path) -> None:
        """Full Pass 1+2+3 flow over the EuroEyes fixture with hand-crafted
        Pass 2 responses that respect the arithmetic identities."""
        is_parsed = {
            "fiscal_period": "FY2024",
            "currency": "HKD",
            "currency_unit": "millions",
            "line_items": [
                {"label": "Revenue", "value_current": 580.0, "category": "revenue"},
                {
                    "label": "Cost of sales",
                    "value_current": -290.0,
                    "category": "cost_of_sales",
                },
                {
                    "label": "S&M + G&A + D&A",
                    "value_current": -180.0,
                    "category": "opex",
                },
                {
                    "label": "Operating income",
                    "value_current": 110.0,
                    "category": "operating_income",
                },
                {"label": "Net income", "value_current": 75.0, "category": "net_income"},
            ],
        }
        bs_parsed = {
            "as_of_date": "2024-12-31",
            "currency": "HKD",
            "currency_unit": "millions",
            "line_items": [
                {
                    "label": "Total assets",
                    "value_current": 3200.0,
                    "category": "total_assets",
                },
                {
                    "label": "Total liabilities",
                    "value_current": 1300.0,
                    "category": "total_liabilities",
                },
                {
                    "label": "Total equity",
                    "value_current": 1900.0,
                    "category": "total_equity",
                },
            ],
        }
        cf_parsed = {
            "fiscal_period": "FY2024",
            "currency": "HKD",
            "currency_unit": "millions",
            "line_items": [
                {"label": "CFO", "value_current": 135.0, "category": "cfo"},
                {"label": "CFI", "value_current": -75.0, "category": "cfi"},
                {"label": "CFF", "value_current": -45.0, "category": "cff"},
                {
                    "label": "Net change",
                    "value_current": 15.0,
                    "category": "net_change_in_cash",
                },
            ],
        }

        toc = LLMResponse(
            content="",
            structured_output={
                "primary_fiscal_period": "FY2024",
                "sections": [
                    {
                        "section_type": "income_statement",
                        "title": "IS",
                        "start_marker": "## 2. Consolidated Income Statement (FY2024)",
                        "end_marker": "## 3. Consolidated Balance Sheet (as of 31 December 2024)",
                    },
                    {
                        "section_type": "balance_sheet",
                        "title": "BS",
                        "start_marker": "## 3. Consolidated Balance Sheet (as of 31 December 2024)",
                        "end_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                    },
                    {
                        "section_type": "cash_flow",
                        "title": "CF",
                        "start_marker": "## 4. Consolidated Cash Flow Statement (FY2024)",
                        "end_marker": "## 5. Segment Information",
                    },
                ],
            },
            input_tokens=3000,
            output_tokens=150,
            cost_usd=Decimal("0.012"),
            model_used="claude-sonnet-4-6",
        )

        llm = MagicMock()

        async def complete(request):
            tool_names = [t["name"] for t in (request.tools or [])]
            if REPORT_SECTIONS_TOOL_NAME in tool_names:
                return toc
            payload = {
                INCOME_STATEMENT_TOOL_NAME: is_parsed,
                BALANCE_SHEET_TOOL_NAME: bs_parsed,
                CASH_FLOW_TOOL_NAME: cf_parsed,
            }
            for name in tool_names:
                if name in payload:
                    return LLMResponse(
                        content="",
                        structured_output=payload[name],
                        input_tokens=200,
                        output_tokens=80,
                        cost_usd=Decimal("0.002"),
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
        tracker = CostTracker(log_path=tmp_path / "costs.jsonl")
        extractor = P1IndustrialExtractor(llm=llm, cost_tracker=tracker)

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
        result = await extractor.extract(doc)

        # Pass 1: 3 core sections identified
        assert {s.section_type for s in result.sections} == {
            "income_statement",
            "balance_sheet",
            "cash_flow",
        }
        # Pass 2: all three have parsed_data
        assert all(s.parsed_data is not None for s in result.sections)
        # Pass 3: arithmetic identities hold → no issues → PASS
        assert result.overall_status == GuardrailStatus.PASS, result.issues
        assert result.issues == []
        # Cost tracker captured 1 TOC + 3 per-section = 4 calls
        assert len(tracker.session_entries()) == 4
