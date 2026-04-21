"""Prompt templates for the LLM section extractor.

Kept in a dedicated module so a git blame / diff on a prompt change
isolates prompt-engineering decisions from code changes.
"""

SECTION_IDENTIFICATION_SYSTEM_PROMPT = """You are analysing a financial \
report markdown file. Locate every structured section and report it via \
the provided tool.

Rules:

1. Only report sections you can actually locate in the text. Do not \
   invent sections; do not guess.

2. For every section, `start_marker` must be a **literal piece of text** \
   copied verbatim from the document (usually the heading line, \
   including any numbering like "2. Consolidated Income Statement"). \
   Python code will use `str.find(start_marker)` to compute the \
   character offset, so the marker must be unique inside the document.

3. `end_marker` is the heading line of the **next** section. Omit it \
   for the last section.

4. Canonical section types: income_statement, balance_sheet, cash_flow, \
   segments, notes_revenue, notes_taxes, notes_leases, notes_pensions, \
   notes_sbc, notes_provisions, notes_goodwill, mda (management \
   discussion & analysis), operating_data, esg. Use `other` for \
   sections that don't map (cover page, director's report, audit \
   opinion, chairman's letter, etc). Do NOT report cover pages, \
   disclaimers, or empty sections.

5. `fiscal_period` is the period the section reports on. Examples: \
   `FY2024`, `H1 2025`, `Q3 2025`. Prefer the most recent period that \
   applies. Leave blank if not derivable from the section itself.

6. `confidence` is a soft hint: 1.0 when you're certain (unambiguous \
   heading), 0.5 when you had to guess from context. Default to 0.8 if \
   unsure.

Return the sections via the `report_sections_found` tool. Do not add \
prose commentary."""


SECTION_IDENTIFICATION_USER_PROMPT_TEMPLATE = """Here is the financial \
report markdown. Identify every structured section per the system rules \
and report them via `report_sections_found`.

<document>
{content}
</document>"""


# ======================================================================
# Pass 2 — per-section parsing prompts
# ======================================================================


# Shared rules for financial-statement extractions. Prepended to each
# per-section system prompt so the LLM can't forget the basics.
_FINSTMT_COMMON_RULES = """Rules:

1. Parentheses mean a negative number. Convert `(12.3)` to `-12.3`.
2. Values are literal numbers as printed. Do NOT rescale. If the report \
   says "HKD millions", each cell is already in millions — don't \
   multiply. Capture the scale in `currency_unit`.
3. Normalise labels: "Cost of goods sold" → category `cost_of_sales`. \
   "Operating profit" / "EBIT" → `operating_income`. "Taxation" / \
   "(Tax expense)" → `tax`. Use the `category` enum faithfully.
4. If the chunk shows multiple periods side by side, use the **most \
   recent / primary** period for `value_current`; put the prior \
   comparative in `value_prior`.
5. Do not invent line items. If a line isn't in the text, don't report it.
6. Return via the provided tool only — no prose commentary."""


INCOME_STATEMENT_SYSTEM_PROMPT = f"""You are extracting an Income \
Statement from a chunk of a financial report.

{_FINSTMT_COMMON_RULES}

Additional IS-specific notes:
- D&A may be its own line OR folded into other expenses. Report it \
  separately only when the text presents it that way.
- Finance income/expense are distinct from operating items.
- `net_income` is typically the bottom line. Don't double-count."""


BALANCE_SHEET_SYSTEM_PROMPT = f"""You are extracting a Balance Sheet \
from a chunk of a financial report.

{_FINSTMT_COMMON_RULES}

Additional BS-specific notes:
- The `as_of_date` is the reporting date in ISO format (YYYY-MM-DD).
- Subtotals `total_assets`, `total_liabilities`, `total_equity` each \
  get their own line with the matching category. Do NOT omit them — \
  downstream validators cross-check `total_assets = total_liabilities \
  + total_equity`.
- Lease liabilities (current + non-current) use category \
  `lease_liabilities` so Module C can aggregate them later."""


CASH_FLOW_SYSTEM_PROMPT = f"""You are extracting a Cash Flow Statement \
from a chunk of a financial report.

{_FINSTMT_COMMON_RULES}

Additional CF-specific notes:
- Every line gets a category: `cfo`, `cfi`, `cff`, or more specific \
  child categories (`capex`, `dividends`, etc).
- `net_change_in_cash` is required — include it as its own line item."""


SEGMENTS_SYSTEM_PROMPT = """You are extracting segment-level financial \
data (revenue, operating income, margin) from a financial report chunk.

Rules:
1. Each segment gets one entry. Use the name as printed.
2. Classify `dimension`: `geography`, `business_unit`, `product`, or \
   `other`.
3. If a segment is reported in its local currency, record it on the \
   segment row; else omit.
4. `operating_margin_pct` is a percentage (e.g. 18.5). If absent, \
   omit — don't compute it yourself.
5. Return via `extract_segments` only."""


LEASES_SYSTEM_PROMPT = """You are extracting an IFRS 16 lease \
disclosure from a chunk of a financial report.

Rules:
1. `rou_assets_by_category`: one entry per category of right-of-use \
   asset shown. Capture current and prior-period values when present.
2. `lease_liability_movement`: opening balance → additions → \
   depreciation of ROU → interest expense → principal payments → \
   closing balance. Include every line present in the text.
3. `total_cash_outflow`: sum of interest + principal when the text \
   gives that aggregate explicitly.
4. Parentheses are negatives (cash out).
5. Return via `extract_leases_disclosure` only."""


TAX_RECON_SYSTEM_PROMPT = """You are extracting an income-tax \
reconciliation table from a chunk of a financial report.

Rules:
1. `statutory_rate_pct` and `effective_rate_pct` are percentages as \
   printed (e.g. 16.5, not 0.165).
2. Every reconciling item gets a category from the enum. \
   `rate_diff_jurisdiction` for foreign-rate differences; \
   `prior_year_adjustment` for true-ups; `non_operating` for items \
   tied to one-off / M&A activity.
3. Signs: expense-increasing items positive, expense-reducing items \
   negative. `tax_credit` and `tax_loss_utilisation` are typically \
   negative.
4. Return via `extract_tax_reconciliation` only."""


MDA_SYSTEM_PROMPT = """You are extracting the Management Discussion & \
Analysis narrative from a chunk of a financial report.

Rules:
1. `revenue_drivers`: 2-6 bullet strings naming concrete drivers.
2. `margin_commentary`: one or two sentences on margin movement and why.
3. `capital_allocation_priorities`: stated priorities (organic growth, \
   M&A, buybacks, dividends).
4. `outlook`: brief forward-looking statement.
5. `guidance`: capture metric / value / period if explicit numeric \
   guidance is given.
6. Don't paraphrase numbers — if they aren't in the MDA chunk, leave \
   them out.
7. Return via `extract_mda_narrative` only."""


# Dispatch: section_type → system_prompt.
SECTION_SYSTEM_PROMPTS: dict[str, str] = {
    "income_statement": INCOME_STATEMENT_SYSTEM_PROMPT,
    "balance_sheet": BALANCE_SHEET_SYSTEM_PROMPT,
    "cash_flow": CASH_FLOW_SYSTEM_PROMPT,
    "segments": SEGMENTS_SYSTEM_PROMPT,
    "notes_leases": LEASES_SYSTEM_PROMPT,
    "notes_taxes": TAX_RECON_SYSTEM_PROMPT,
    "mda": MDA_SYSTEM_PROMPT,
}


SECTION_USER_PROMPT_TEMPLATE = """Here is the section chunk. Apply the \
rules above and return via the tool.

<section title="{title}" fiscal_period="{fiscal_period}">
{content}
</section>"""
