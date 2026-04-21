"""Tool definitions for Anthropic structured output (tool use).

Phase 1 ships Pass 1's ``report_sections_found`` only. Pass 2 tools
(``extract_income_statement`` et al) land in Sprint 3 alongside their
prompts.
"""

from __future__ import annotations

from typing import Any

# Section types the P1 extractor knows about. The LLM is constrained to
# this enum via the tool's input_schema so we never see surprise
# section_type values downstream.
KNOWN_SECTION_TYPES: tuple[str, ...] = (
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "segments",
    "notes_revenue",
    "notes_taxes",
    "notes_leases",
    "notes_pensions",
    "notes_sbc",
    "notes_provisions",
    "notes_goodwill",
    "mda",
    "operating_data",
    "esg",
    "other",
)


REPORT_SECTIONS_TOOL_NAME = "report_sections_found"


REPORT_SECTIONS_TOOL: dict[str, Any] = {
    "name": REPORT_SECTIONS_TOOL_NAME,
    "description": (
        "Report every structured section located in the provided financial "
        "report text. Use markers (exact literal text) so Python can find "
        "the section boundaries without guessing character positions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "description": (
                    "One entry per section found. Only include sections "
                    "you can actually locate in the text."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "section_type": {
                            "type": "string",
                            "enum": list(KNOWN_SECTION_TYPES),
                            "description": (
                                "Canonical section type. Use 'other' for "
                                "anything that doesn't fit the known types."
                            ),
                        },
                        "title": {
                            "type": "string",
                            "description": (
                                "Title as written in the document (may include numbering)."
                            ),
                        },
                        "start_marker": {
                            "type": "string",
                            "description": (
                                "Exact literal text (usually the heading "
                                "line) that begins this section. Must be "
                                "unique in the document."
                            ),
                        },
                        "end_marker": {
                            "type": "string",
                            "description": (
                                "Exact literal text that begins the next "
                                "section. Omit for the last section in the "
                                "document."
                            ),
                        },
                        "fiscal_period": {
                            "type": "string",
                            "description": (
                                "Period the section reports on, e.g. "
                                "'FY2024' or 'H1 2025'. Omit if not "
                                "derivable."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": (
                                "Confidence in this section's identification, "
                                "0.0 (guess) to 1.0 (certain)."
                            ),
                        },
                    },
                    "required": ["section_type", "title", "start_marker"],
                },
            },
            "primary_fiscal_period": {
                "type": "string",
                "description": (
                    "The document's primary fiscal period (e.g. 'FY2024'). "
                    "Used when per-section fiscal_period is absent."
                ),
            },
        },
        "required": ["sections"],
    },
}
