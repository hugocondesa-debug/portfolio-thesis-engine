"""Parser: ``wacc_inputs.md`` (YAML frontmatter) → :class:`WACCInputs`.

Expected file layout::

    ---
    ticker: 1846.HK
    profile: P1
    valuation_date: 2025-03-31
    current_price: "12.50"
    cost_of_capital:
      risk_free_rate: 3.5
      equity_risk_premium: 6.0
      beta: 1.2
      cost_of_debt_pretax: 4.5
      tax_rate_for_wacc: 16.5
    capital_structure:
      debt_weight: 30
      equity_weight: 70
    scenarios:
      bear:
        probability: 25
        revenue_cagr_explicit_period: 3
        terminal_growth: 2
        terminal_operating_margin: 15
      base:
        probability: 50
        revenue_cagr_explicit_period: 8
        terminal_growth: 2.5
        terminal_operating_margin: 18
      bull:
        probability: 25
        revenue_cagr_explicit_period: 12
        terminal_growth: 3
        terminal_operating_margin: 22
    explicit_period_years: 10
    notes: |
      Free-form analyst notes here.
    ---

    # Optional free-form markdown below — ignored by the parser.

The frontmatter block is a YAML mapping delimited by lines of exactly
``---``. The parser rejects files whose frontmatter is missing or
malformed.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.schemas.wacc import WACCInputs

_DELIM = "---"


def _stringify_dates(obj: Any) -> Any:
    """Recursively convert date/datetime instances to ISO strings.

    PyYAML's SafeLoader auto-parses ``2025-03-31`` into a :class:`date`
    object; our schema fields use ISO strings, so coerce before
    validation to save callers the hassle of quoting every date.
    """
    if isinstance(obj, datetime):
        return obj.date().isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    return obj


def _split_frontmatter(content: str) -> dict[str, object]:
    """Return the parsed YAML frontmatter dict.

    Raises :class:`IngestionError` when the frontmatter is missing,
    malformed, or doesn't deserialize to a mapping.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != _DELIM:
        raise IngestionError("wacc_inputs.md must start with a YAML frontmatter delimiter '---'")
    # Find the closing delimiter.
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == _DELIM:
            yaml_text = "".join(lines[1:idx])
            break
    else:
        raise IngestionError(
            "wacc_inputs.md frontmatter is not closed — expected a second '---' line"
        )

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise IngestionError(f"wacc_inputs.md frontmatter is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise IngestionError("wacc_inputs.md frontmatter must be a YAML mapping at the top level")
    return data


def parse_wacc_inputs(path: Path) -> WACCInputs:
    """Read ``path`` and return a validated :class:`WACCInputs`.

    Raises :class:`IngestionError` on I/O or frontmatter errors;
    re-raises :class:`pydantic.ValidationError` unchanged when the
    frontmatter is well-formed YAML but violates the schema — callers
    can surface a rich message to the user.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError) as e:
        raise IngestionError(f"Cannot read {path}: {e}") from e

    data = _split_frontmatter(content)
    return WACCInputs.model_validate(_stringify_dates(data))
