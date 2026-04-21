"""Base classes for guardrails.

A :class:`Guardrail` encapsulates a single quality/validation check.
:meth:`check` receives an opaque ``context`` dict (the caller decides what
keys to put in — extraction output, valuation snapshot, price data, …) and
returns a :class:`GuardrailResult`.

FAIL/WARN/etc. statuses are carried by :class:`GuardrailResult`; exceptions
raised from ``check()`` are infrastructure errors (the runner converts them
to FAIL, preserving the invariant that a FAIL is always represented by a
result object).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from portfolio_thesis_engine.schemas.common import GuardrailStatus


@dataclass
class GuardrailResult:
    """Outcome of a single guardrail check."""

    check_id: str
    name: str
    status: GuardrailStatus
    message: str
    blocking: bool = False
    data: dict[str, Any] = field(default_factory=dict)


class Guardrail(ABC):
    """Abstract single-check guardrail."""

    @property
    @abstractmethod
    def check_id(self) -> str:
        """Stable identifier, e.g. ``A.1``, ``V.2``, ``D.3``."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name (shown in reports)."""

    @property
    def blocking(self) -> bool:
        """If ``True``, a FAIL from this guardrail stops the pipeline when the
        runner is invoked with ``stop_on_blocking_fail=True``."""
        return False

    @abstractmethod
    def check(self, context: dict[str, Any]) -> GuardrailResult:
        """Run the check over ``context`` and return the outcome."""
