"""Parser for structured-markdown ``wacc_inputs.md`` files.

Sibling to :mod:`wacc_parser` which handles the YAML-frontmatter form.
Hugo's real workflow produces analyst-friendly markdown with tables
and H2/H3 sections; this module reads that format and returns the
same :class:`WACCInputs` schema so downstream code is format-agnostic.

Expected structure (flexible — see synonym dicts below for accepted
aliases per field):

```markdown
# WACC Inputs — CompanyName

**Ticker:** ABC
**Profile:** P1
**Valuation date:** 2024-12-31

## Market Data
| Metric             | Value |
| Share price        | 12.30 |

## WACC Parameters
| Parameter           | Value |
| Risk-Free Rate (Rf) | 2.50  |
| Equity Risk Premium | 5.50  |
| Beta levered (β_l)  | 1.10  |
| Size Premium        | 1.50  |   ← optional
| Cost of Debt (Kd)   | 4.00  |
| Tax rate            | 16.50 |

## Capital Structure
| Component | Weight |
| Debt      | 25     |
| Equity    | 75     |

## Business Scenarios
### Bear (25%)
- Revenue CAGR: 3.0%
- Terminal operating margin: 15.0%
- Terminal growth: 2.0%
### Base (50%)   ← same shape
### Bull (25%)   ← same shape
```

Values tolerate markdown conventions: thousands separators (``2,460``
→ 2460), percent suffixes (``50%`` → 50), trailing units (``12.30 HKD``
→ 12.30). Only the leading numeric chunk is consumed.

Detection between the two parsers lives in
:func:`wacc_parser.parse_wacc_inputs`: files starting with ``---``
route to YAML, everything else routes here.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)

# ----------------------------------------------------------------------
# Synonym dictionaries — easy to extend as new company files surface.
# ----------------------------------------------------------------------
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # Market data
    "current_price": ("share price", "stock price", "price", "current price"),
    # CAPM + cost of debt
    "risk_free_rate": (
        "risk free rate",
        "risk free rate rf",
        "rf year end",
        "rfr",
        "rf",
    ),
    "equity_risk_premium": (
        "equity risk premium",
        "market risk premium",
        "erp",
    ),
    "beta": ("beta levered", "β levered", "β l", "beta", "levered beta"),
    "size_premium": ("size premium",),
    "cost_of_debt_pretax": (
        "cost of debt pre tax",
        "pre tax cost of debt",
        "cost of debt kd",
        "cost of debt",
        "kd",
    ),
    "tax_rate_for_wacc": (
        "tax rate for wacc",
        "marginal tax rate",
        "tax rate",
    ),
}

_CAPITAL_STRUCTURE_ALIASES: dict[str, tuple[str, ...]] = {
    "debt_weight": ("debt",),
    "equity_weight": ("equity",),
    "preferred_weight": ("preferred",),
}

_SCENARIO_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue_cagr_explicit_period": (
        "revenue cagr",
        "revenue growth",
        "revenue cagr explicit period",
    ),
    "terminal_operating_margin": (
        "terminal operating margin",
        "terminal margin",
    ),
    "terminal_growth": (
        "terminal growth rate",
        "terminal growth",
    ),
}

_SECTION_TITLE_ALIASES: dict[str, tuple[str, ...]] = {
    "market_data": ("market data", "market snapshot"),
    "wacc_parameters": (
        "wacc parameters",
        "wacc inputs",
        "wacc calculation",
        "cost of capital",
    ),
    "capital_structure": ("capital structure",),
    "business_scenarios": ("business scenarios", "scenarios"),
}

_SCENARIO_LABELS = ("bear", "base", "bull")


# ----------------------------------------------------------------------
# Normalisation + parsing helpers
# ----------------------------------------------------------------------
def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Keeps word characters (letters, digits, underscore, unicode) and
    ``%``; drops parentheses, slashes, hyphens, commas. Runs of
    whitespace collapse to a single space.
    """
    s = s.lower().strip()
    s = re.sub(r"[^\w\s%]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _parse_decimal(value: str) -> Decimal | None:
    """Extract the leading numeric chunk from ``value`` and return it
    as :class:`Decimal`, or ``None`` when no number is found.

    Strips thousands separators (``,``) and percent signs. Trailing
    units (``HKD``, ``M``, etc.) are ignored.
    """
    s = value.strip().replace(",", "").replace("%", "")
    m = _NUMBER_RE.search(s)
    if not m:
        return None
    try:
        return Decimal(m.group(0))
    except InvalidOperation:
        return None


def _match_alias(key: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    """Return the canonical field for ``key``, or ``None``.

    Matches when a normalised alias is a substring of the normalised
    key or vice-versa. Iteration order is alias-dict insertion order,
    so more specific canonicals should appear earlier.
    """
    norm_key = _normalize(key)
    if not norm_key:
        return None
    for canonical, variants in aliases.items():
        for raw in variants:
            norm_alias = _normalize(raw)
            if norm_alias == norm_key:
                return canonical
            # Word-bounded substring: require the alias to appear
            # surrounded by whitespace (or string boundaries) to avoid
            # accidental matches like "debt" inside "Cost of Debt".
            pattern = r"(?:^|\s)" + re.escape(norm_alias) + r"(?:\s|$)"
            if re.search(pattern, norm_key) or re.search(
                r"(?:^|\s)" + re.escape(norm_key) + r"(?:\s|$)", norm_alias
            ):
                return canonical
    return None


# ----------------------------------------------------------------------
# Markdown structure parsers
# ----------------------------------------------------------------------
_H2_SPLIT_RE = re.compile(r"^## +", re.MULTILINE)
_H3_SPLIT_RE = re.compile(r"^### +", re.MULTILINE)
_HEADER_FIELD_RE = re.compile(r"\*\*([^*:]+):\*\*\s*(.+)")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
_SCENARIO_HEADING_RE = re.compile(
    r"^\s*([A-Za-z]+)\s*\(\s*(\d+(?:\.\d+)?)\s*%?\s*\)\s*$"
)
_LIST_ITEM_RE = re.compile(r"^\s*[-*]\s*([^:]+):\s*(.+?)\s*$", re.MULTILINE)


def _split_h2_sections(content: str) -> dict[str, str]:
    """Return ``{normalised_h2_heading: body}`` for every H2 in the file.

    The pre-H2 preamble lives under the empty-string key ``""``.
    """
    parts = _H2_SPLIT_RE.split(content)
    out: dict[str, str] = {"": parts[0]}
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        heading = _normalize(lines[0])
        body = "\n".join(lines[1:])
        out[heading] = body
    return out


def _parse_tables(text: str) -> list[list[dict[str, str]]]:
    """Find every markdown table in ``text``.

    Each table is returned as a list of row-dicts keyed by the
    header-row cells. Rows with a different number of cells than
    the header are padded/truncated to the header length.
    """
    tables: list[list[dict[str, str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            header_cells = [c.strip() for c in _strip_row(line).split("|")]
            j = i + 2
            rows: list[dict[str, str]] = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in _strip_row(lines[j]).split("|")]
                # Pad/truncate to header length so zip keys are stable.
                if len(cells) < len(header_cells):
                    cells = cells + [""] * (len(header_cells) - len(cells))
                elif len(cells) > len(header_cells):
                    cells = cells[: len(header_cells)]
                rows.append(dict(zip(header_cells, cells, strict=False)))
                j += 1
            tables.append(rows)
            i = j
        else:
            i += 1
    return tables


def _strip_row(line: str) -> str:
    """Strip the leading + trailing pipes from a markdown table row."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s


def _extract_table_fields(
    tables: list[list[dict[str, str]]],
    aliases: dict[str, tuple[str, ...]],
) -> dict[str, Decimal]:
    """Walk every table's rows as key-value pairs (first column = label,
    second column = numeric value). Returns ``{canonical_name: Decimal}``."""
    out: dict[str, Decimal] = {}
    for table in tables:
        for row in table:
            items = list(row.items())
            if len(items) < 2:
                continue
            label_cell = items[0][1]
            value_cell = items[1][1]
            canonical = _match_alias(label_cell, aliases)
            if canonical is None or canonical in out:
                continue
            dec = _parse_decimal(value_cell)
            if dec is not None:
                out[canonical] = dec
    return out


def _parse_header_fields(content: str) -> dict[str, str]:
    """Pull top-level ``**Key:** value`` pairs (before the first H2)."""
    # Only consider the preamble (content before the first H2); otherwise
    # bolded text inside sections leaks in as header fields.
    pre = _H2_SPLIT_RE.split(content, maxsplit=1)[0]
    out: dict[str, str] = {}
    for m in _HEADER_FIELD_RE.finditer(pre):
        key = _normalize(m.group(1))
        if key and key not in out:
            out[key] = m.group(2).strip()
    return out


def _parse_business_scenarios(body: str) -> dict[str, ScenarioDriversManual]:
    """Parse H3 ``### Bear (25%)`` blocks with ``- Driver: value`` lists.

    Scenarios missing any required driver are silently skipped (the
    overall WACCInputs validator will raise if no scenarios at all
    make it through).
    """
    scenarios: dict[str, ScenarioDriversManual] = {}
    parts = _H3_SPLIT_RE.split(body)
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        heading_match = _SCENARIO_HEADING_RE.match(lines[0])
        if not heading_match:
            continue
        label = heading_match.group(1).strip().lower()
        if label not in _SCENARIO_LABELS:
            continue
        probability = Decimal(heading_match.group(2))

        drivers: dict[str, Decimal] = {}
        for li in _LIST_ITEM_RE.finditer(part):
            canonical = _match_alias(li.group(1), _SCENARIO_FIELD_ALIASES)
            if canonical is None or canonical in drivers:
                continue
            dec = _parse_decimal(li.group(2))
            if dec is not None:
                drivers[canonical] = dec

        required = (
            "revenue_cagr_explicit_period",
            "terminal_operating_margin",
            "terminal_growth",
        )
        if all(k in drivers for k in required):
            scenarios[label] = ScenarioDriversManual(
                probability=probability,
                revenue_cagr_explicit_period=drivers["revenue_cagr_explicit_period"],
                terminal_operating_margin=drivers["terminal_operating_margin"],
                terminal_growth=drivers["terminal_growth"],
            )
    return scenarios


# ----------------------------------------------------------------------
# Top-level entry
# ----------------------------------------------------------------------
def parse_wacc_markdown(content: str) -> WACCInputs:
    """Parse a structured-markdown WACC file into :class:`WACCInputs`.

    Raises :class:`IngestionError` with a clear message when a required
    field can't be located. The Pydantic validator on ``WACCInputs``
    catches shape violations (probabilities sum, scenario labels).
    """
    header = _parse_header_fields(content)
    sections = _split_h2_sections(content)

    # --- Header fields (validated first so errors point at the top
    #     of the file before we try to unpack tables) ----------------
    ticker = header.get("ticker")
    if not ticker:
        raise IngestionError("wacc_inputs.md: missing **Ticker:** header.")
    profile_raw = header.get("profile", "P1")
    try:
        profile = Profile(profile_raw)
    except ValueError as e:
        raise IngestionError(
            f"wacc_inputs.md: unknown profile {profile_raw!r} "
            f"(expected one of {[p.value for p in Profile]})"
        ) from e
    valuation_date = header.get("valuation date") or header.get("valuation_date")
    if not valuation_date:
        raise IngestionError("wacc_inputs.md: missing **Valuation date:** header.")

    # Route each H2 section to its canonical bucket.
    bucket_body: dict[str, str] = {}
    for heading, body in sections.items():
        if not heading:
            continue
        canon = _match_alias(heading, _SECTION_TITLE_ALIASES)
        if canon is not None and canon not in bucket_body:
            bucket_body[canon] = body

    # --- Market Data --------------------------------------------------
    market_tables = _parse_tables(bucket_body.get("market_data", ""))
    market_fields = _extract_table_fields(
        market_tables,
        {"current_price": _FIELD_ALIASES["current_price"]},
    )
    current_price = market_fields.get("current_price")
    if current_price is None:
        raise IngestionError(
            "wacc_inputs.md: could not find 'Share price' row in the "
            "Market Data section."
        )

    # --- WACC Parameters ---------------------------------------------
    wacc_tables = _parse_tables(bucket_body.get("wacc_parameters", ""))
    wacc_fields = _extract_table_fields(wacc_tables, _FIELD_ALIASES)
    required_wacc = (
        "risk_free_rate",
        "equity_risk_premium",
        "beta",
        "cost_of_debt_pretax",
        "tax_rate_for_wacc",
    )
    missing = [k for k in required_wacc if k not in wacc_fields]
    if missing:
        raise IngestionError(
            f"wacc_inputs.md: missing WACC parameters: {missing}. "
            f"Add rows with matching labels to the WACC Parameters table."
        )
    coc = CostOfCapitalInputs(
        risk_free_rate=wacc_fields["risk_free_rate"],
        equity_risk_premium=wacc_fields["equity_risk_premium"],
        beta=wacc_fields["beta"],
        cost_of_debt_pretax=wacc_fields["cost_of_debt_pretax"],
        tax_rate_for_wacc=wacc_fields["tax_rate_for_wacc"],
        size_premium=wacc_fields.get("size_premium"),
    )

    # --- Capital Structure -------------------------------------------
    cs_tables = _parse_tables(bucket_body.get("capital_structure", ""))
    cs_fields = _extract_table_fields(cs_tables, _CAPITAL_STRUCTURE_ALIASES)
    if "debt_weight" not in cs_fields or "equity_weight" not in cs_fields:
        raise IngestionError(
            "wacc_inputs.md: Capital Structure must include Debt + Equity weights."
        )
    capital_structure = CapitalStructure(
        debt_weight=cs_fields["debt_weight"],
        equity_weight=cs_fields["equity_weight"],
        preferred_weight=cs_fields.get("preferred_weight", Decimal("0")),
    )

    # --- Business Scenarios ------------------------------------------
    scenarios = _parse_business_scenarios(bucket_body.get("business_scenarios", ""))
    if not scenarios:
        raise IngestionError(
            "wacc_inputs.md: no Bear/Base/Bull scenarios parsed from the "
            "Business Scenarios section."
        )

    return WACCInputs(
        ticker=ticker,
        profile=profile,
        valuation_date=valuation_date,
        current_price=current_price,
        cost_of_capital=coc,
        capital_structure=capital_structure,
        scenarios=scenarios,
    )


__all__ = ["parse_wacc_markdown"]
