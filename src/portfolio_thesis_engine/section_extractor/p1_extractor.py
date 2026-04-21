"""P1 Industrial archetype extractor — Pass 1 (TOC identification).

Pass 2 and Pass 3 land in Sprints 3 and 4 respectively. Today the
extractor runs Pass 1 only and returns sections whose ``parsed_data`` is
``None``.
"""

from __future__ import annotations

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
)
from portfolio_thesis_engine.section_extractor.tools import (
    REPORT_SECTIONS_TOOL,
    REPORT_SECTIONS_TOOL_NAME,
)

_DEFAULT_TOC_MODEL = "claude-sonnet-4-6"


class P1IndustrialExtractor(SectionExtractor):
    """Section extractor for the P1 Industrial archetype."""

    profile_name = "P1_INDUSTRIAL"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
        model_toc: str = _DEFAULT_TOC_MODEL,
        max_tokens_toc: int = 4096,
    ) -> None:
        self.llm = llm
        self.cost_tracker = cost_tracker
        self.model_toc = model_toc
        self.max_tokens_toc = max_tokens_toc

    # ------------------------------------------------------------------
    async def extract(self, document: IngestedDocument) -> ExtractionResult:
        """Run Pass 1 today; Pass 2 + 3 will fill in over Sprints 3-4."""
        content = document.source_path.read_text(encoding="utf-8")
        identified, primary_period = await self._identify_sections(content, ticker=document.ticker)
        sections = [
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
        fiscal_period = primary_period or (
            next(
                (s.fiscal_period for s in sections if s.fiscal_period),
                "unknown",
            )
        )
        return ExtractionResult(
            doc_id=document.doc_id,
            ticker=document.ticker,
            fiscal_period=fiscal_period,
            sections=sections,
        )

    # ------------------------------------------------------------------
    async def _identify_sections(
        self, content: str, ticker: str
    ) -> tuple[list[IdentifiedSection], str | None]:
        """Pass 1 — one tool-use call returning section boundaries.

        Returns ``(identified, primary_fiscal_period)``. Boundaries are
        resolved from the LLM's literal markers via ``str.find``; any
        marker that doesn't match the document is dropped with a warning
        in the caller's log (``warnings`` on the ExtractionResult).
        """
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
            # De-duplicate if the LLM emits the same marker twice.
            if start_marker in seen_markers:
                continue
            start_char = content.find(start_marker)
            if start_char < 0:
                # Marker not found — can't resolve boundaries, skip it.
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
