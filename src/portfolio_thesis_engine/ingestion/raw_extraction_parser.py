"""Parser helper for ``raw_extraction.yaml`` → normalised :class:`RawExtraction`.

Two responsibilities beyond Pydantic validation:

1. **Unit-scale normalisation.** If the source document reports in
   thousands or millions, every monetary Decimal on the as-reported
   structured schema is multiplied by the scale factor so downstream
   code always works in base units. The returned
   :class:`RawExtraction` has its ``unit_scale`` reset to ``"units"``
   — calling the parser again on the returned object is a no-op
   (idempotent).

2. **Exception wrapping.** File-not-found, YAML syntax errors, and
   Pydantic validation errors surface as :class:`IngestionError` so
   CLI / pipeline code catches one type regardless of root cause.

Normalisation walks:

- Every :class:`LineItem.value` on IS / BS / CF.
- Every numeric cell in :class:`NoteTable.rows` (rows are mixed
  label-then-numbers; we scale values whose type is
  ``Decimal``).
- Every :class:`SegmentMetrics.metrics` value.
- :class:`SegmentReporting.inter_segment_eliminations`.
- :class:`HistoricalDataSeries.metrics` values.
- :class:`OperationalKPI.values` when the entry is numeric (Decimal).

Fields that are **not** monetary (and therefore not scaled):

- :class:`EarningsPerShare` per-share values and share counts.
- :class:`ProfitAttribution` fields (already monetary — scaled).
  *Correction:* profit attribution IS monetary; scale it too.
- Narrative / label / unit fields.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    HistoricalDataSeries,
    IncomeStatementPeriod,
    LineItem,
    Note,
    NoteTable,
    OperationalKPI,
    ProfitAttribution,
    RawExtraction,
    SegmentMetrics,
    SegmentReporting,
)

_FACTOR_BY_SCALE: dict[str, Decimal] = {
    "thousands": Decimal("1000"),
    "millions": Decimal("1000000"),
}


# ----------------------------------------------------------------------
# Public entry
# ----------------------------------------------------------------------
def parse_raw_extraction(path: Path) -> RawExtraction:
    """Return a validated + unit-normalised :class:`RawExtraction`.

    Raises :class:`IngestionError` on I/O failure, YAML syntax error,
    or schema violation. The returned object always has
    ``metadata.unit_scale == "units"``.
    """
    if not path.exists():
        raise IngestionError(f"raw_extraction: file not found at {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise IngestionError(f"raw_extraction: cannot read {path}: {e}") from e

    try:
        raw = RawExtraction.from_yaml(content)
    except ValidationError as e:
        raise IngestionError(
            f"raw_extraction: schema validation failed for {path}:\n{e}"
        ) from e
    except yaml.YAMLError as e:
        raise IngestionError(
            f"raw_extraction: YAML syntax error in {path}: {e}"
        ) from e

    return normalise_unit_scale(raw)


# ----------------------------------------------------------------------
# Unit-scale normalisation
# ----------------------------------------------------------------------
def normalise_unit_scale(raw: RawExtraction) -> RawExtraction:
    """Rebuild ``raw`` with all monetary Decimals converted to base
    units. Idempotent: a call on an already-``"units"`` extraction
    returns the same object."""
    scale = raw.metadata.unit_scale
    if scale == "units":
        return raw
    factor = _FACTOR_BY_SCALE[scale]

    new_is = {
        period: _scale_is(sp, factor) for period, sp in raw.income_statement.items()
    }
    new_bs = {
        period: _scale_bs(sp, factor) for period, sp in raw.balance_sheet.items()
    }
    new_cf = {
        period: _scale_cf(sp, factor) for period, sp in raw.cash_flow.items()
    }
    new_notes = [_scale_note(n, factor) for n in raw.notes]
    new_segments = [_scale_segment_reporting(s, factor) for s in raw.segments]
    new_historical = (
        _scale_historical(raw.historical, factor)
        if raw.historical is not None
        else None
    )
    new_kpis = [_scale_operational_kpi(k, factor) for k in raw.operational_kpis]

    return raw.model_copy(
        update={
            "metadata": raw.metadata.model_copy(update={"unit_scale": "units"}),
            "income_statement": new_is,
            "balance_sheet": new_bs,
            "cash_flow": new_cf,
            "notes": new_notes,
            "segments": new_segments,
            "historical": new_historical,
            "operational_kpis": new_kpis,
        }
    )


# ----------------------------------------------------------------------
# Statement scaling
# ----------------------------------------------------------------------
def _scale_line_items(items: list[LineItem], factor: Decimal) -> list[LineItem]:
    return [
        item.model_copy(update={"value": item.value * factor})
        if item.value is not None
        else item
        for item in items
    ]


def _scale_is(is_data: IncomeStatementPeriod, factor: Decimal) -> IncomeStatementPeriod:
    updates: dict[str, Any] = {
        "line_items": _scale_line_items(is_data.line_items, factor),
    }
    if is_data.profit_attribution is not None:
        updates["profit_attribution"] = _scale_profit_attribution(
            is_data.profit_attribution, factor
        )
    # EPS per-share values and share counts are dimensionally distinct
    # from monetary Decimals: do not scale.
    return is_data.model_copy(update=updates)


def _scale_bs(bs_data: BalanceSheetPeriod, factor: Decimal) -> BalanceSheetPeriod:
    return bs_data.model_copy(
        update={"line_items": _scale_line_items(bs_data.line_items, factor)}
    )


def _scale_cf(cf_data: CashFlowPeriod, factor: Decimal) -> CashFlowPeriod:
    return cf_data.model_copy(
        update={"line_items": _scale_line_items(cf_data.line_items, factor)}
    )


def _scale_profit_attribution(
    pa: ProfitAttribution, factor: Decimal
) -> ProfitAttribution:
    updates: dict[str, Any] = {}
    for name, value in pa.model_dump(mode="python").items():
        if isinstance(value, Decimal):
            updates[name] = value * factor
    return pa.model_copy(update=updates)


# ----------------------------------------------------------------------
# Notes scaling
# ----------------------------------------------------------------------
def _scale_note(note: Note, factor: Decimal) -> Note:
    if not note.tables:
        return note
    return note.model_copy(
        update={"tables": [_scale_note_table(t, factor) for t in note.tables]}
    )


def _scale_note_table(table: NoteTable, factor: Decimal) -> NoteTable:
    """Scale every numeric cell in the rows. Row cells are ``Any``,
    so numeric-looking strings (from YAML-quoted decimals) are coerced
    to Decimal then scaled; plain strings (row labels) pass through.
    None cells pass through."""
    new_rows: list[list[Any]] = []
    for row in table.rows:
        new_row: list[Any] = []
        for cell in row:
            numeric = _coerce_decimal(cell)
            if numeric is not None:
                new_row.append(numeric * factor)
            else:
                new_row.append(cell)
        new_rows.append(new_row)
    return table.model_copy(update={"rows": new_rows})


def _coerce_decimal(cell: Any) -> Decimal | None:
    """Return ``cell`` as a :class:`Decimal` if it represents a number;
    else ``None``.

    - ``Decimal`` / ``int`` / ``float`` → converted.
    - ``str`` that parses as a number → converted.
    - Non-numeric strings / ``None`` / other → ``None``.
    """
    if isinstance(cell, Decimal):
        return cell
    if isinstance(cell, bool):  # bool is int — exclude explicitly
        return None
    if isinstance(cell, int | float):
        return Decimal(str(cell))
    if isinstance(cell, str):
        try:
            return Decimal(cell)
        except Exception:  # noqa: BLE001
            return None
    return None


# ----------------------------------------------------------------------
# Segments scaling
# ----------------------------------------------------------------------
def _scale_segment_reporting(
    s: SegmentReporting, factor: Decimal
) -> SegmentReporting:
    updates: dict[str, Any] = {
        "segments": [_scale_segment_metrics(sm, factor) for sm in s.segments],
    }
    if s.inter_segment_eliminations is not None:
        updates["inter_segment_eliminations"] = {
            k: (v * factor if v is not None else None)
            for k, v in s.inter_segment_eliminations.items()
        }
    return s.model_copy(update=updates)


def _scale_segment_metrics(sm: SegmentMetrics, factor: Decimal) -> SegmentMetrics:
    scaled: dict[str, Decimal | None] = {}
    for key, value in sm.metrics.items():
        scaled[key] = value * factor if value is not None else None
    return sm.model_copy(update={"metrics": scaled})


# ----------------------------------------------------------------------
# Historical scaling
# ----------------------------------------------------------------------
def _scale_historical(h: HistoricalDataSeries, factor: Decimal) -> HistoricalDataSeries:
    scaled: dict[str, list[Decimal | None]] = {}
    for metric, values in h.metrics.items():
        scaled[metric] = [v * factor if v is not None else None for v in values]
    return h.model_copy(update={"metrics": scaled})


# ----------------------------------------------------------------------
# Operational KPIs scaling
# ----------------------------------------------------------------------
def _scale_operational_kpi(k: OperationalKPI, factor: Decimal) -> OperationalKPI:
    """KPIs with a numeric value get scaled when the unit is monetary
    (contains an ISO currency code). Non-monetary KPIs pass through
    unchanged. Numeric-looking strings are coerced to Decimal.

    The parser is intentionally conservative: when in doubt (no unit
    or ambiguous unit), it skips scaling.
    """
    if not _kpi_is_monetary(k):
        return k
    scaled: dict[str, Decimal | str | None] = {}
    for key, value in k.values.items():
        numeric = _coerce_decimal(value)
        if numeric is not None:
            scaled[key] = numeric * factor
        else:
            scaled[key] = value
    return k.model_copy(update={"values": scaled})


def _kpi_is_monetary(k: OperationalKPI) -> bool:
    """Heuristic: treat a KPI as monetary when its ``unit`` field
    contains a currency ISO code or a ``currency per X`` pattern. Safer
    to under-scale (leave to user) than over-scale (corrupt counts)."""
    if k.unit is None:
        return False
    unit_upper = k.unit.upper()
    currency_markers = ("USD", "EUR", "GBP", "CHF", "JPY", "HKD", "CNY", "RMB")
    return any(marker in unit_upper for marker in currency_markers)


__all__ = [
    "parse_raw_extraction",
    "normalise_unit_scale",
]
