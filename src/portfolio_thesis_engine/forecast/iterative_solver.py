"""Phase 2 Sprint 4A-beta — pure-Python fixed-point solver.

The three statements are interdependent: ΔWC (BS) feeds CFO, M&A
financing choice (debt vs cash) depends on cash availability, and the
post-iteration BS cash must equal the prior cash plus CFO+CFI+CFF.
A classic fixed-point iteration converges these in a handful of steps
for well-posed scenarios. No scipy dependency — Decimals throughout.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

MAX_ITERATIONS = 20
CONVERGENCE_TOLERANCE = Decimal("0.0001")


def fixed_point_solve(
    *,
    initial_state: dict[str, Any],
    iteration_fn: Callable[[dict[str, Any]], dict[str, Any]],
    convergence_fn: Callable[[dict[str, Any], dict[str, Any]], Decimal],
    max_iterations: int = MAX_ITERATIONS,
    tolerance: Decimal = CONVERGENCE_TOLERANCE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Iterate until ``convergence_fn(prev, next) < tolerance`` or we
    exhaust ``max_iterations``.

    Returns ``(final_state, convergence_info)``.
    ``convergence_info`` always includes ``iterations``, ``final_residual``,
    and ``converged`` keys.
    """
    state = initial_state
    residual = Decimal("0")
    new_state = state

    for iteration in range(1, max_iterations + 1):
        new_state = iteration_fn(state)
        residual = convergence_fn(state, new_state)

        if residual < tolerance:
            return new_state, {
                "iterations": iteration,
                "final_residual": float(residual),
                "converged": True,
            }

        state = new_state

    return new_state, {
        "iterations": max_iterations,
        "final_residual": float(residual),
        "converged": False,
    }


def compute_cash_residual(
    state_a: dict[str, Any], state_b: dict[str, Any]
) -> Decimal:
    """Sum-of-cash residual between two iterations.

    Uses the absolute relative delta when state_a has a non-zero cash
    sum, else absolute delta. Robust to zero-cash initial states.
    """
    a_series = state_a.get("bs_cash", [Decimal("0")])
    b_series = state_b.get("bs_cash", [Decimal("0")])
    cash_a = sum(a_series, Decimal("0"))
    cash_b = sum(b_series, Decimal("0"))

    if cash_a == 0:
        return abs(cash_b)

    return abs(cash_a - cash_b) / abs(cash_a)


__all__ = [
    "CONVERGENCE_TOLERANCE",
    "MAX_ITERATIONS",
    "compute_cash_residual",
    "fixed_point_solve",
]
