"""Parser: ``wacc_inputs.md`` → :class:`WACCInputs`.

Supports two on-disk formats, auto-detected by the first non-blank
line of the file:

1. **YAML frontmatter** (starts with ``---``): parsed here by
   :func:`_split_frontmatter` + :func:`WACCInputs.model_validate`.
2. **Structured markdown** (anything else): delegated to
   :func:`wacc_markdown_parser.parse_wacc_markdown`. See that module's
   docstring for the expected shape — markdown tables + H2/H3
   sections. Hugo's production workflow produces this format.

YAML frontmatter layout::

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
      bear: { probability: 25, revenue_cagr_explicit_period: 3, ... }
      base: { probability: 50, ... }
      bull: { probability: 25, ... }
    ---

    # Optional free-form markdown below — ignored by the parser.

Both formats produce the same :class:`WACCInputs` object; the rest of
the pipeline is format-agnostic.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.wacc_markdown_parser import parse_wacc_markdown
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

    Detects the on-disk format from the first non-blank line:

    - ``---`` → YAML frontmatter (this module).
    - anything else → structured markdown
      (:func:`wacc_markdown_parser.parse_wacc_markdown`).

    Raises :class:`IngestionError` on I/O or format errors; re-raises
    :class:`pydantic.ValidationError` unchanged when the fields are
    well-formed but violate the schema — callers can surface a rich
    message to the user.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError) as e:
        raise IngestionError(f"Cannot read {path}: {e}") from e

    if _looks_like_frontmatter(content):
        data = _split_frontmatter(content)
        return WACCInputs.model_validate(_stringify_dates(data))
    return parse_wacc_markdown(content)


def _looks_like_frontmatter(content: str) -> bool:
    """Return True when the file's first non-blank line is ``---``."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped == _DELIM
    return False
