"""Common types shared across schemas.

Enums, monetary/percentage aliases, and a handful of small value objects
(:class:`MoneyWithCurrency`, :class:`DateRange`, :class:`FiscalPeriod`,
:class:`Source`). Imported widely — keep it free of heavier schema deps.

Value objects inherit from :class:`BaseSchema` / :class:`ImmutableSchema`
so they pick up ``extra="forbid"``, whitespace stripping, and the
:meth:`to_yaml` / :meth:`from_yaml` helpers.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, ImmutableSchema


class Currency(StrEnum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    CHF = "CHF"
    JPY = "JPY"
    HKD = "HKD"


class Profile(StrEnum):
    """Archetype for the company's sector."""

    P1_INDUSTRIAL = "P1"
    P2_BANKS = "P2"
    P3A_INSURANCE = "P3a"
    P3B_REITS = "P3b"
    P4_RESOURCES = "P4"
    P5_PRE_REVENUE = "P5"
    P6_HOLDINGS = "P6"


class ConvictionLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GuardrailStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    REVIEW = "REVIEW"
    NOTA = "NOTA"


class ConfidenceTag(StrEnum):
    """Data-confidence (vintage) tags."""

    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    ESTIMATED = "ESTIMATED"
    ADJUSTED = "ADJUSTED"
    ALIGNED = "ALIGNED"


Money = Annotated[Decimal, Field(description="Monetary amount, precision preserved")]
Percentage = Annotated[
    Decimal, Field(ge=-100, le=1000, description="Percentage, e.g. 12.5 = 12.5%")
]
BasisPoints = Annotated[int, Field(description="Basis points, e.g. 250 = 2.5%")]

# ISO date string (YYYY-MM-DD). Kept as ``str`` with a regex pattern
# rather than :class:`datetime.date` so YAML round-trip behaves
# predictably (PyYAML would otherwise auto-parse bare dates).
ISODate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Ticker = Annotated[str, Field(min_length=1, max_length=20)]


class MoneyWithCurrency(ImmutableSchema):
    """Monetary value with explicit currency. Immutable."""

    amount: Money
    currency: Currency


class DateRange(BaseSchema):
    """Inclusive date range, ISO-formatted strings."""

    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class FiscalPeriod(BaseSchema):
    """Fiscal period identifier, e.g. ``FY2025`` or ``Q3 2025``."""

    year: int = Field(ge=1990, le=2100)
    quarter: int | None = Field(default=None, ge=1, le=4)
    label: str

    def __str__(self) -> str:
        return self.label


class Source(BaseSchema):
    """Documentation of a data source."""

    document: str
    page: int | None = None
    confidence: ConfidenceTag = ConfidenceTag.REPORTED
    url: str | None = None
    accessed: str | None = None
