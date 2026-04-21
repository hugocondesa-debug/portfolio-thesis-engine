"""Cross-cutting type aliases.

Domain enums (Currency, Profile, ConvictionLevel, GuardrailStatus,
ConfidenceTag) live in :mod:`portfolio_thesis_engine.schemas.common` alongside
the Pydantic schemas that use them. This module holds only generic aliases
used broadly across the codebase.

Uses PEP 695 ``type`` statements (Python 3.12+).
"""

type Ticker = str
"""Ticker symbol, e.g. ``AAPL`` or ``ASML.AS``. Format is provider-dependent."""

type ISODate = str
"""Date formatted as ``YYYY-MM-DD``."""

type UnixTimestamp = int
"""Seconds since the Unix epoch (UTC)."""

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]
type JsonList = list[JsonValue]
