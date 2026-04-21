"""Concrete guardrail implementations — Group A (arithmetic) and Group
V (validation vs external sources).

Callers usually don't import these directly; they come packaged into a
list by :func:`default_guardrails` or via the
:class:`GuardrailRunner` wiring in the pipeline coordinator.
"""

from portfolio_thesis_engine.guardrails.base import Guardrail
from portfolio_thesis_engine.guardrails.checks.arithmetic import (
    BSChecksum,
    CFChecksum,
    ICConsistency,
    ISChecksum,
)
from portfolio_thesis_engine.guardrails.checks.validation import (
    CrossCheckNetIncomeGuardrail,
    CrossCheckRevenueGuardrail,
    CrossCheckTotalAssetsGuardrail,
    WACCConsistency,
)


def default_guardrails() -> list["Guardrail"]:
    """Return the Phase 1 guardrail bundle, in run order."""
    checks: list[Guardrail] = [
        # A.* arithmetic — consume canonical_state
        ISChecksum(),
        BSChecksum(),
        CFChecksum(),
        ICConsistency(),
        # V.* validation — consume cross_check_report + wacc_inputs
        CrossCheckRevenueGuardrail(),
        CrossCheckNetIncomeGuardrail(),
        CrossCheckTotalAssetsGuardrail(),
        WACCConsistency(),
    ]
    return checks


__all__ = [
    "BSChecksum",
    "CFChecksum",
    "CrossCheckNetIncomeGuardrail",
    "CrossCheckRevenueGuardrail",
    "CrossCheckTotalAssetsGuardrail",
    "ICConsistency",
    "ISChecksum",
    "WACCConsistency",
    "default_guardrails",
]
