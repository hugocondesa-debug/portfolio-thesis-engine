"""P1 Industrial archetype extractor — Passes 1, 2 and 3.

Pass 1 (TOC identification): one LLM call locates section boundaries.
Pass 2 (per-section parsing): one LLM call per parseable section,
dispatched via the :data:`SECTION_TOOLS` table and parallelised
with :func:`asyncio.gather` bounded by ``max_concurrent``.
Pass 3 (validation): Python-side checks for core sections, fiscal
period consistency, currency consistency, and IS / BS / CF arithmetic.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from portfolio_thesis_engine.ingestion.base import IngestedDocument
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.base import LLMRequest
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.llm.structured import (
    build_tool,
    force_tool_choice,
)
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult,
    IdentifiedSection,
    SectionExtractor,
    StructuredSection,
)
from portfolio_thesis_engine.section_extractor.prompts import (
    SECTION_IDENTIFICATION_SYSTEM_PROMPT,
    SECTION_IDENTIFICATION_USER_PROMPT_TEMPLATE,
    SECTION_SYSTEM_PROMPTS,
    SECTION_USER_PROMPT_TEMPLATE,
)
from portfolio_thesis_engine.section_extractor.tools import (
    REPORT_SECTIONS_TOOL,
    REPORT_SECTIONS_TOOL_NAME,
    SECTION_TOOLS,
)
from portfolio_thesis_engine.section_extractor.validator import ExtractionValidator
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

_DEFAULT_TOC_MODEL = "claude-sonnet-4-6"
_DEFAULT_PARSE_MODEL = "claude-sonnet-4-6"


class P1IndustrialExtractor(SectionExtractor):
    """Section extractor for the P1 Industrial archetype."""

    profile_name = "P1_INDUSTRIAL"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
        model_toc: str = _DEFAULT_TOC_MODEL,
        model_parse: str = _DEFAULT_PARSE_MODEL,
        max_tokens_toc: int = 4096,
        max_tokens_parse: int = 4096,
        max_concurrent: int = 5,
    ) -> None:
        self.llm = llm
        self.cost_tracker = cost_tracker
        self.model_toc = model_toc
        self.model_parse = model_parse
        self.max_tokens_toc = max_tokens_toc
        self.max_tokens_parse = max_tokens_parse
        self.max_concurrent = max_concurrent
        self._validator = ExtractionValidator()

    # ------------------------------------------------------------------
    async def extract(self, document: IngestedDocument) -> ExtractionResult:
        """Run Pass 1 → Pass 2 → Pass 3 and return the final result."""
        content = document.source_path.read_text(encoding="utf-8")
        identified, primary_period = await self._identify_sections(content, ticker=document.ticker)

        # Pass 2: parse every section whose type we recognise.
        pass1_sections = [
            StructuredSection(
                section_type=s.section_type,
                title=s.title,
                content=content[s.start_char : s.end_char],
                parsed_data=None,
                page_range=None,
                fiscal_period=s.fiscal_period or primary_period,
                confidence=s.confidence,
                extraction_method="llm_section_detection",
            )
            for s in identified
        ]
        self._enforce_cost_cap(ticker=document.ticker, stage="section_parse")
        sections = await self._parse_sections(pass1_sections, ticker=document.ticker)

        fiscal_period = primary_period or (
            next(
                (s.fiscal_period for s in sections if s.fiscal_period),
                "unknown",
            )
        )
        result = ExtractionResult(
            doc_id=document.doc_id,
            ticker=document.ticker,
            fiscal_period=fiscal_period,
            sections=sections,
        )

        # Pass 3: validation. Issues + overall_status roll up here; no
        # LLM calls, so no cost-cap check needed.
        issues = self._validator.validate(result)
        result.issues = issues
        result.overall_status = ExtractionValidator.overall_status(issues)
        return result

    # ------------------------------------------------------------------
    # Pass 1
    # ------------------------------------------------------------------
    async def _identify_sections(
        self, content: str, ticker: str
    ) -> tuple[list[IdentifiedSection], str | None]:
        """Pass 1 — one tool-use call returning section boundaries.

        Boundaries are resolved from the LLM's literal markers via
        ``str.find``; any marker that doesn't match the document is
        silently dropped.
        """
        self._enforce_cost_cap(ticker=ticker, stage="section_toc")

        tool = build_tool(
            REPORT_SECTIONS_TOOL_NAME,
            REPORT_SECTIONS_TOOL["description"],
            REPORT_SECTIONS_TOOL["input_schema"],
        )
        user_prompt = SECTION_IDENTIFICATION_USER_PROMPT_TEMPLATE.format(content=content)
        request = LLMRequest(
            prompt=user_prompt,
            system=SECTION_IDENTIFICATION_SYSTEM_PROMPT,
            model=self.model_toc,
            max_tokens=self.max_tokens_toc,
            tools=[tool],
            tool_choice=force_tool_choice(REPORT_SECTIONS_TOOL_NAME),
        )

        response = await self.llm.complete(request)
        self.cost_tracker.record(
            operation="section_toc",
            model=response.model_used,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd or Decimal("0"),
            ticker=ticker,
        )

        payload = response.structured_output or {}
        raw_sections = payload.get("sections") or []
        primary_period = payload.get("primary_fiscal_period")

        identified: list[IdentifiedSection] = []
        seen_markers: set[str] = set()
        for raw in raw_sections:
            section_type = raw.get("section_type")
            title = raw.get("title", "")
            start_marker = raw.get("start_marker")
            if not section_type or not start_marker:
                continue
            if start_marker in seen_markers:
                continue
            start_char = content.find(start_marker)
            if start_char < 0:
                continue
            seen_markers.add(start_marker)

            end_marker = raw.get("end_marker")
            if end_marker:
                end_char = content.find(end_marker, start_char + 1)
                if end_char < 0:
                    end_char = len(content)
            else:
                end_char = len(content)

            confidence = raw.get("confidence", 0.8)
            try:
                confidence_float = float(confidence)
            except (TypeError, ValueError):
                confidence_float = 0.8

            identified.append(
                IdentifiedSection(
                    section_type=section_type,
                    title=title,
                    start_char=start_char,
                    end_char=end_char,
                    fiscal_period=raw.get("fiscal_period") or primary_period,
                    confidence=confidence_float,
                )
            )

        identified.sort(key=lambda s: s.start_char)
        return identified, primary_period

    # ------------------------------------------------------------------
    # Pass 2
    # ------------------------------------------------------------------
    async def _parse_sections(
        self, sections: list[StructuredSection], ticker: str
    ) -> list[StructuredSection]:
        """Per-section extraction. Sections whose type is not in
        :data:`SECTION_TOOLS` pass through with ``parsed_data=None``.

        Bounded by ``max_concurrent`` via an asyncio semaphore so a
        document with 20+ sections doesn't stampede the provider.
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def parse_one(section: StructuredSection) -> StructuredSection:
            if section.section_type not in SECTION_TOOLS:
                return section
            async with semaphore:
                parsed = await self._extract_section_content(
                    section_type=section.section_type,
                    title=section.title,
                    fiscal_period=section.fiscal_period,
                    content=section.content,
                    ticker=ticker,
                )
            return StructuredSection(
                section_type=section.section_type,
                title=section.title,
                content=section.content,
                parsed_data=parsed,
                page_range=section.page_range,
                fiscal_period=section.fiscal_period,
                confidence=section.confidence,
                extraction_method=section.extraction_method,
            )

        # Gather preserves order — sections come back in document order.
        return list(await asyncio.gather(*(parse_one(s) for s in sections)))

    async def _extract_section_content(
        self,
        *,
        section_type: str,
        title: str,
        fiscal_period: str | None,
        content: str,
        ticker: str,
    ) -> dict[str, object] | None:
        """One LLM call for a single section. Returns the tool_use
        input (a dict) or ``None`` if the model failed to invoke the tool."""
        tool_def, operation = SECTION_TOOLS[section_type]
        system_prompt = SECTION_SYSTEM_PROMPTS[section_type]

        tool = build_tool(tool_def["name"], tool_def["description"], tool_def["input_schema"])
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            title=title or section_type,
            fiscal_period=fiscal_period or "unknown",
            content=content,
        )
        request = LLMRequest(
            prompt=user_prompt,
            system=system_prompt,
            model=self.model_parse,
            max_tokens=self.max_tokens_parse,
            tools=[tool],
            tool_choice=force_tool_choice(tool_def["name"]),
        )

        response = await self.llm.complete(request)
        self.cost_tracker.record(
            operation=operation,
            model=response.model_used,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd or Decimal("0"),
            ticker=ticker,
        )
        return response.structured_output

    # ------------------------------------------------------------------
    # Cost-cap enforcement
    # ------------------------------------------------------------------
    def _enforce_cost_cap(self, *, ticker: str, stage: str) -> None:
        """Raise :class:`CostLimitExceededError` if the per-company cap has
        already been hit. Called once per stage (TOC + parse), not per LLM
        call — the cap is coarse-grained by design."""
        cap = Decimal(str(settings.llm_max_cost_per_company_usd))
        spent = self.cost_tracker.ticker_total(ticker)
        if spent >= cap:
            raise CostLimitExceededError(
                f"Per-company cost cap reached before stage {stage!r}: "
                f"${spent} >= ${cap} for ticker {ticker!r}"
            )
