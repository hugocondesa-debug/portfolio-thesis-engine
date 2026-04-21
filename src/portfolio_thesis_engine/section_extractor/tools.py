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


# ======================================================================
# Pass 2 tools — one per section type the extractor parses deeply.
#
# Each tool has its own enum of allowed `category` values. That keeps
# the LLM honest about where a line item belongs — Sprint 4 validators
# can then reason about categories safely without string heuristics.
# ======================================================================

_CURRENCY_UNIT_ENUM = ["units", "thousands", "millions", "billions"]


def _line_item_schema(category_enum: list[str]) -> dict[str, Any]:
    """Build a line_items[] schema with a per-statement category enum."""
    return {
        "type": "object",
        "description": "One labelled numeric line from the statement.",
        "properties": {
            "label": {
                "type": "string",
                "description": "Label as written in the document.",
            },
            "value_current": {
                "type": "number",
                "description": (
                    "Numeric value for the current period. Parentheses in "
                    "the source indicate a negative number — convert to "
                    "negative."
                ),
            },
            "value_prior": {
                "type": "number",
                "description": "Prior-period comparative if present.",
            },
            "category": {"type": "string", "enum": category_enum},
            "notes_reference": {"type": "string"},
        },
        "required": ["label", "value_current", "category"],
    }


INCOME_STATEMENT_TOOL_NAME = "extract_income_statement"
INCOME_STATEMENT_TOOL: dict[str, Any] = {
    "name": INCOME_STATEMENT_TOOL_NAME,
    "description": "Extract structured income-statement data from the chunk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "currency": {"type": "string"},
            "currency_unit": {"type": "string", "enum": _CURRENCY_UNIT_ENUM},
            "line_items": {
                "type": "array",
                "items": _line_item_schema(
                    [
                        "revenue",
                        "cost_of_sales",
                        "opex",
                        "d_and_a",
                        "operating_income",
                        "finance_income",
                        "finance_expense",
                        "non_operating",
                        "tax",
                        "net_income",
                        "other",
                    ]
                ),
            },
        },
        "required": ["fiscal_period", "currency", "currency_unit", "line_items"],
    },
}


BALANCE_SHEET_TOOL_NAME = "extract_balance_sheet"
BALANCE_SHEET_TOOL: dict[str, Any] = {
    "name": BALANCE_SHEET_TOOL_NAME,
    "description": "Extract structured balance-sheet data from the chunk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "as_of_date": {
                "type": "string",
                "description": "Snapshot date in ISO format (YYYY-MM-DD).",
            },
            "currency": {"type": "string"},
            "currency_unit": {"type": "string", "enum": _CURRENCY_UNIT_ENUM},
            "line_items": {
                "type": "array",
                "items": _line_item_schema(
                    [
                        "cash",
                        "operating_assets",
                        "financial_assets",
                        "intangibles",
                        "operating_liabilities",
                        "financial_liabilities",
                        "lease_liabilities",
                        "equity",
                        "nci",
                        "total_assets",
                        "total_liabilities",
                        "total_equity",
                        "other",
                    ]
                ),
            },
        },
        "required": ["as_of_date", "currency", "currency_unit", "line_items"],
    },
}


CASH_FLOW_TOOL_NAME = "extract_cash_flow"
CASH_FLOW_TOOL: dict[str, Any] = {
    "name": CASH_FLOW_TOOL_NAME,
    "description": "Extract structured cash-flow-statement data from the chunk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "currency": {"type": "string"},
            "currency_unit": {"type": "string", "enum": _CURRENCY_UNIT_ENUM},
            "line_items": {
                "type": "array",
                "items": _line_item_schema(
                    [
                        "cfo",
                        "cfi",
                        "cff",
                        "capex",
                        "acquisitions",
                        "dividends",
                        "buybacks",
                        "debt_issuance",
                        "debt_repayment",
                        "lease_payments",
                        "fx_effect",
                        "net_change_in_cash",
                        "other",
                    ]
                ),
            },
        },
        "required": ["fiscal_period", "currency", "currency_unit", "line_items"],
    },
}


SEGMENTS_TOOL_NAME = "extract_segments"
SEGMENTS_TOOL: dict[str, Any] = {
    "name": SEGMENTS_TOOL_NAME,
    "description": "Extract segment-level revenue / margin data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "dimension": {
                            "type": "string",
                            "enum": ["geography", "business_unit", "product", "other"],
                            "description": "How the segment is defined.",
                        },
                        "currency": {"type": "string"},
                        "revenue": {"type": "number"},
                        "operating_income": {"type": "number"},
                        "operating_margin_pct": {"type": "number"},
                        "assets": {"type": "number"},
                    },
                    "required": ["name", "revenue"],
                },
            },
        },
        "required": ["fiscal_period", "segments"],
    },
}


LEASES_TOOL_NAME = "extract_leases_disclosure"
LEASES_TOOL: dict[str, Any] = {
    "name": LEASES_TOOL_NAME,
    "description": (
        "Extract IFRS 16 lease disclosure: ROU assets by category, "
        "lease liability movement, P&L impact."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "currency": {"type": "string"},
            "currency_unit": {"type": "string", "enum": _CURRENCY_UNIT_ENUM},
            "rou_assets_by_category": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "value_current": {"type": "number"},
                        "value_prior": {"type": "number"},
                    },
                    "required": ["category", "value_current"],
                },
            },
            "lease_liability_movement": {
                "type": "object",
                "properties": {
                    "opening_balance": {"type": "number"},
                    "additions": {"type": "number"},
                    "depreciation_of_rou": {"type": "number"},
                    "interest_expense": {"type": "number"},
                    "principal_payments": {"type": "number"},
                    "closing_balance": {"type": "number"},
                },
            },
            "total_cash_outflow": {"type": "number"},
        },
        "required": ["fiscal_period", "currency", "currency_unit"],
    },
}


TAX_RECON_TOOL_NAME = "extract_tax_reconciliation"
TAX_RECON_TOOL: dict[str, Any] = {
    "name": TAX_RECON_TOOL_NAME,
    "description": "Extract the income-tax reconciliation table.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "currency": {"type": "string"},
            "currency_unit": {"type": "string", "enum": _CURRENCY_UNIT_ENUM},
            "statutory_rate_pct": {"type": "number"},
            "effective_rate_pct": {"type": "number"},
            "profit_before_tax": {"type": "number"},
            "statutory_tax": {"type": "number"},
            "reconciling_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "amount": {"type": "number"},
                        "category": {
                            "type": "string",
                            "enum": [
                                "non_deductible",
                                "tax_credit",
                                "rate_diff_jurisdiction",
                                "prior_year_adjustment",
                                "tax_loss_utilisation",
                                "non_operating",
                                "other",
                            ],
                        },
                    },
                    "required": ["label", "amount"],
                },
            },
            "reported_tax_expense": {"type": "number"},
        },
        "required": ["fiscal_period", "reconciling_items", "reported_tax_expense"],
    },
}


MDA_TOOL_NAME = "extract_mda_narrative"
MDA_TOOL: dict[str, Any] = {
    "name": MDA_TOOL_NAME,
    "description": ("Extract key narrative points from management discussion & analysis."),
    "input_schema": {
        "type": "object",
        "properties": {
            "fiscal_period": {"type": "string"},
            "revenue_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Bullet points explaining revenue movement.",
            },
            "margin_commentary": {"type": "string"},
            "capital_allocation_priorities": {
                "type": "array",
                "items": {"type": "string"},
            },
            "outlook": {"type": "string"},
            "guidance": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "string"},
                    "period": {"type": "string"},
                },
            },
        },
        "required": ["fiscal_period"],
    },
}


# Dispatch table: section_type → (tool, operation_name for cost tracker).
# Only the section types we parse deeply appear here; others pass through
# Pass 2 with parsed_data=None.
SECTION_TOOLS: dict[str, tuple[dict[str, Any], str]] = {
    "income_statement": (INCOME_STATEMENT_TOOL, "section_parse_is"),
    "balance_sheet": (BALANCE_SHEET_TOOL, "section_parse_bs"),
    "cash_flow": (CASH_FLOW_TOOL, "section_parse_cf"),
    "segments": (SEGMENTS_TOOL, "section_parse_segments"),
    "notes_leases": (LEASES_TOOL, "section_parse_leases"),
    "notes_taxes": (TAX_RECON_TOOL, "section_parse_tax"),
    "mda": (MDA_TOOL, "section_parse_mda"),
}
