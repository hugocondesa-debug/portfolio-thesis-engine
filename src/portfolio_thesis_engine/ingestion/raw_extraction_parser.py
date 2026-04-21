"""Parser helper for ``raw_extraction.yaml`` → normalised :class:`RawExtraction`.

Two responsibilities beyond Pydantic validation:

1. **Unit-scale normalisation.** If the source document reports in
   thousands or millions, every Decimal in the statements + numeric
   notes is multiplied by the scale factor so downstream code always
   works in base units. The returned :class:`RawExtraction` has its
   ``unit_scale`` reset to ``"units"`` — calling the parser again on
   the returned object would be a no-op (idempotent).

2. **Exception wrapping.** File-not-found, YAML syntax errors, and
   Pydantic validation errors all surface as :class:`IngestionError`
   so CLI / pipeline code catches one type regardless of the root
   cause.

Normalisation covers:

- Every Decimal field + ``extensions`` values on :class:`IncomeStatementPeriod`,
  :class:`BalanceSheetPeriod`, :class:`CashFlowPeriod`.
- Amount fields on items inside the notes container (tax
  reconciling items, provisions, acquisitions, goodwill / intangibles
  / PP&E / inventory / commitments / related-party, operational
  metrics with Decimal values).

Rates (``effective_tax_rate_percent``, ``statutory_rate_percent``),
headcount / shares counts that aren't monetary are **not scaled** —
they're dimensionally different and the schema documents them
explicitly.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.schemas.raw_extraction import (
    AcquisitionItem,
    AcquisitionsNote,
    BalanceSheetPeriod,
    CashFlowPeriod,
    CommitmentsNote,
    DiscontinuedOpsNote,
    GoodwillNote,
    IncomeStatementPeriod,
    IntangiblesNote,
    InventoryNote,
    LeaseNote,
    NotesContainer,
    PensionNote,
    PPENote,
    ProvisionItem,
    RawExtraction,
    RelatedPartyItem,
    SBCNote,
    TaxNote,
    TaxReconciliationItem,
)

# Fields on EmployeeBenefitsNote are dimensionally mixed (headcount is
# a count; compensation is money). We scale only the money fields.
_EMPLOYEE_MONEY_FIELDS = frozenset(
    {"avg_compensation", "total_compensation", "pension_expense", "sbc_expense"}
)

# Fields on the IS that AREN'T money and must not be scaled:
_IS_NON_MONETARY = frozenset(
    {
        "eps_basic",
        "eps_diluted",
        "shares_basic_weighted_avg",
        "shares_diluted_weighted_avg",
    }
)

_TAX_RATE_FIELDS = frozenset(
    {"effective_tax_rate_percent", "statutory_rate_percent"}
)


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
    """Rebuild ``raw`` with all Decimal monetary values converted to
    base units. Idempotent — calling with ``unit_scale == "units"``
    returns the same object."""
    scale = raw.metadata.unit_scale
    if scale == "units":
        return raw
    factor = {"thousands": Decimal("1000"), "millions": Decimal("1000000")}[scale]

    new_is = {
        period: _scale_statement(sp, factor, _IS_NON_MONETARY)
        for period, sp in raw.income_statement.items()
    }
    new_bs = {
        period: _scale_statement(sp, factor, frozenset())
        for period, sp in raw.balance_sheet.items()
    }
    new_cf = {
        period: _scale_statement(sp, factor, frozenset())
        for period, sp in raw.cash_flow.items()
    }
    new_notes = _scale_notes(raw.notes, factor)

    return raw.model_copy(
        update={
            "metadata": raw.metadata.model_copy(update={"unit_scale": "units"}),
            "income_statement": new_is,
            "balance_sheet": new_bs,
            "cash_flow": new_cf,
            "notes": new_notes,
        }
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _scale_statement(
    period_model: BaseModel,
    factor: Decimal,
    non_monetary: frozenset[str],
) -> BaseModel:
    """Return a new period model with Decimal fields scaled by
    ``factor``. Fields in ``non_monetary`` keep their raw values."""
    updates: dict[str, Any] = {}
    for name, value in period_model.model_dump(mode="python").items():
        if name in non_monetary:
            continue
        if name == "extensions":
            updates[name] = _scale_dict_of_decimal(value, factor)
            continue
        if isinstance(value, Decimal):
            updates[name] = value * factor
    return period_model.model_copy(update=updates)


def _scale_notes(notes: NotesContainer, factor: Decimal) -> NotesContainer:
    updates: dict[str, Any] = {}

    if notes.taxes is not None:
        updates["taxes"] = _scale_tax_note(notes.taxes, factor)
    if notes.leases is not None:
        updates["leases"] = _scale_all_decimals(notes.leases, factor)
    if notes.provisions:
        updates["provisions"] = [_scale_provision(p, factor) for p in notes.provisions]
    if notes.goodwill is not None:
        updates["goodwill"] = _scale_goodwill(notes.goodwill, factor)
    if notes.intangibles is not None:
        updates["intangibles"] = _scale_intangibles(notes.intangibles, factor)
    if notes.ppe is not None:
        updates["ppe"] = _scale_all_decimals(notes.ppe, factor)
    if notes.inventory is not None:
        updates["inventory"] = _scale_all_decimals(notes.inventory, factor)
    if notes.trade_receivables:
        updates["trade_receivables"] = _scale_dict_of_decimal(
            notes.trade_receivables, factor
        )
    if notes.trade_payables:
        updates["trade_payables"] = _scale_dict_of_decimal(
            notes.trade_payables, factor
        )
    if notes.employee_benefits is not None:
        updates["employee_benefits"] = _scale_selected_decimals(
            notes.employee_benefits, factor, _EMPLOYEE_MONEY_FIELDS
        )
    if notes.share_based_compensation is not None:
        updates["share_based_compensation"] = _scale_sbc(
            notes.share_based_compensation, factor
        )
    if notes.pensions is not None:
        updates["pensions"] = _scale_all_decimals(notes.pensions, factor)
    if notes.commitments_contingencies is not None:
        updates["commitments_contingencies"] = _scale_all_decimals(
            notes.commitments_contingencies, factor
        )
    if notes.acquisitions is not None:
        updates["acquisitions"] = _scale_acquisitions(notes.acquisitions, factor)
    if notes.discontinued_ops is not None:
        updates["discontinued_ops"] = _scale_all_decimals(
            notes.discontinued_ops, factor
        )
    if notes.related_parties:
        updates["related_parties"] = [
            _scale_related_party(rp, factor) for rp in notes.related_parties
        ]
    return notes.model_copy(update=updates) if updates else notes


def _scale_all_decimals(model: BaseModel, factor: Decimal) -> BaseModel:
    """Scale every Decimal field on ``model``."""
    updates: dict[str, Any] = {}
    for name, value in model.model_dump(mode="python").items():
        if isinstance(value, Decimal):
            updates[name] = value * factor
    return model.model_copy(update=updates)


def _scale_selected_decimals(
    model: BaseModel, factor: Decimal, field_names: frozenset[str]
) -> BaseModel:
    """Scale only the Decimal fields whose name is in ``field_names``."""
    updates: dict[str, Any] = {}
    for name, value in model.model_dump(mode="python").items():
        if name in field_names and isinstance(value, Decimal):
            updates[name] = value * factor
    return model.model_copy(update=updates)


def _scale_tax_note(note: TaxNote, factor: Decimal) -> TaxNote:
    """Tax note: scale reconciling-item amounts; leave rates alone."""
    updates: dict[str, Any] = {}
    # Rates stay as-is.
    for name, value in note.model_dump(mode="python").items():
        if name in _TAX_RATE_FIELDS or name == "reconciling_items":
            continue
        if isinstance(value, Decimal):
            updates[name] = value * factor
    if note.reconciling_items:
        updates["reconciling_items"] = [
            TaxReconciliationItem(
                description=item.description,
                amount=item.amount * factor,
                classification=item.classification,
            )
            for item in note.reconciling_items
        ]
    return note.model_copy(update=updates)


def _scale_goodwill(note: GoodwillNote, factor: Decimal) -> GoodwillNote:
    """Scale top-level Decimals and the by-CGU dict."""
    updates: dict[str, Any] = {
        "by_cgu": _scale_dict_of_decimal(note.by_cgu, factor),
    }
    for name, value in note.model_dump(mode="python").items():
        if isinstance(value, Decimal):
            updates[name] = value * factor
    return note.model_copy(update=updates)


def _scale_intangibles(note: IntangiblesNote, factor: Decimal) -> IntangiblesNote:
    """Scale top-level Decimals and the by-type dict."""
    updates: dict[str, Any] = {
        "by_type": _scale_dict_of_decimal(note.by_type, factor),
    }
    for name, value in note.model_dump(mode="python").items():
        if isinstance(value, Decimal):
            updates[name] = value * factor
    return note.model_copy(update=updates)


def _scale_sbc(note: SBCNote, factor: Decimal) -> SBCNote:
    """SBC note: all fields are Decimals, but only ``expense`` is
    monetary — the rest are share / unit counts. Only expense scales."""
    if note.expense is None:
        return note
    return note.model_copy(update={"expense": note.expense * factor})


def _scale_provision(item: ProvisionItem, factor: Decimal) -> ProvisionItem:
    return ProvisionItem(
        description=item.description,
        amount=item.amount * factor,
        classification=item.classification,
    )


def _scale_related_party(item: RelatedPartyItem, factor: Decimal) -> RelatedPartyItem:
    if item.amount is None:
        return item
    return item.model_copy(update={"amount": item.amount * factor})


def _scale_acquisitions(
    note: AcquisitionsNote, factor: Decimal
) -> AcquisitionsNote:
    scaled_items = [
        AcquisitionItem(
            name=item.name,
            date=item.date,
            consideration=item.consideration * factor,
            fair_value=(item.fair_value * factor) if item.fair_value is not None else None,
            goodwill_recognized=(
                item.goodwill_recognized * factor
                if item.goodwill_recognized is not None
                else None
            ),
        )
        for item in note.items
    ]
    return note.model_copy(update={"items": scaled_items})


def _scale_dict_of_decimal(
    data: dict[str, Decimal], factor: Decimal
) -> dict[str, Decimal]:
    return {k: (v * factor) for k, v in data.items()}


# Silence unused-import on types we only reference in type annotations
# via the scale helpers (needed for test isolation).
_TYPED_MODELS = (
    IncomeStatementPeriod,
    BalanceSheetPeriod,
    CashFlowPeriod,
    LeaseNote,
    PPENote,
    InventoryNote,
    PensionNote,
    CommitmentsNote,
    DiscontinuedOpsNote,
)


__all__ = [
    "parse_raw_extraction",
    "normalise_unit_scale",
]
