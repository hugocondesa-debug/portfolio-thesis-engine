"""Run a set of guardrails and aggregate the outcome."""

from __future__ import annotations

from typing import Any

from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.schemas.common import GuardrailStatus

# Precedence for overall_status: FAIL > REVIEW > WARN > NOTA > PASS > SKIP.
_STATUS_PRIORITY: dict[GuardrailStatus, int] = {
    GuardrailStatus.FAIL: 5,
    GuardrailStatus.REVIEW: 4,
    GuardrailStatus.WARN: 3,
    GuardrailStatus.NOTA: 2,
    GuardrailStatus.PASS: 1,
    GuardrailStatus.SKIP: 0,
}


class GuardrailRunner:
    """Execute a list of guardrails against a single context."""

    def __init__(self, guardrails: list[Guardrail]) -> None:
        self.guardrails = guardrails

    def run(
        self,
        context: dict[str, Any],
        stop_on_blocking_fail: bool = True,
    ) -> list[GuardrailResult]:
        """Execute guardrails in order.

        A guardrail raising inside :meth:`Guardrail.check` does **not** crash
        the runner — the exception is caught and turned into a synthetic
        FAIL result so downstream consumers see the failure uniformly.

        When ``stop_on_blocking_fail`` is True (default), a blocking FAIL
        short-circuits the remaining guardrails.
        """
        results: list[GuardrailResult] = []
        for guardrail in self.guardrails:
            try:
                result = guardrail.check(context)
            except Exception as e:
                result = GuardrailResult(
                    check_id=guardrail.check_id,
                    name=guardrail.name,
                    status=GuardrailStatus.FAIL,
                    message=f"Guardrail raised {type(e).__name__}: {e}",
                    blocking=guardrail.blocking,
                )
            results.append(result)
            if stop_on_blocking_fail and result.status == GuardrailStatus.FAIL and result.blocking:
                break
        return results

    @staticmethod
    def overall_status(results: list[GuardrailResult]) -> GuardrailStatus:
        """Worst-case status across ``results``.

        Precedence: FAIL > REVIEW > WARN > NOTA > PASS > SKIP. Empty list
        returns PASS (nothing to complain about).
        """
        if not results:
            return GuardrailStatus.PASS
        worst = max(results, key=lambda r: _STATUS_PRIORITY[r.status])
        return worst.status
