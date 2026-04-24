"""Residual Income valuation engine.

Consumes a :class:`ThreeStatementProjection` + CoE + base book value
(from canonical state) and returns an :class:`RIProjection`. The
fundamental identity is::

    EV = BookValue_0 + Σ PV(RI_y) + PV(terminal_RI)

    RI_y = NI_y − (CoE × BookValue_{y-1})

Positive-RI scenarios imply the firm earns above its cost of capital
and trades above book; negative-RI scenarios destroy value.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import ThreeStatementProjection
from portfolio_thesis_engine.valuation_methodologies.residual_income.book_value_extractor import (
    compute_beginning_book_values,
    extract_book_value_stream,
)
from portfolio_thesis_engine.valuation_methodologies.residual_income.schemas import (
    RIProjection,
    RIYear,
)


class RIEngine:
    """Residual Income fair value from projection + CoE + base equity."""

    def compute(
        self,
        projection: ThreeStatementProjection,
        cost_of_equity: Decimal,
        base_equity: Decimal,
        terminal_growth_rate: Decimal = Decimal("0.025"),
        terminal_discount_rate: Decimal | None = None,
    ) -> RIProjection:
        """Return an :class:`RIProjection`.

        Raises ``ValueError`` when the terminal growth is not strictly
        below the terminal discount rate or when ``base_equity`` is
        non-positive (RI model undefined without a positive book anchor).
        """
        if terminal_discount_rate is None:
            terminal_discount_rate = cost_of_equity

        if terminal_growth_rate >= terminal_discount_rate:
            raise ValueError(
                f"Terminal growth {terminal_growth_rate} must be < terminal "
                f"discount rate {terminal_discount_rate}."
            )

        if base_equity <= 0:
            raise ValueError(
                f"Base equity {base_equity} must be positive for the RI "
                "model. Companies with zero or negative book value cannot "
                "use RI."
            )

        stream = extract_book_value_stream(projection)
        if not stream:
            raise ValueError(
                "ThreeStatementProjection has no projection years — cannot "
                "run RI without an income / balance-sheet stream."
            )

        ending_equities = [equity for _, equity, _, _ in stream]
        beginning_equities = compute_beginning_book_values(
            base_equity, ending_equities
        )

        ri_years: list[RIYear] = []
        sum_pv_ri = Decimal("0")

        for (year, _ending, net_income, _shares), beg_equity in zip(
            stream, beginning_equities
        ):
            required_return = cost_of_equity * beg_equity
            residual_income = net_income - required_return
            discount_factor = Decimal("1") / (
                (Decimal("1") + cost_of_equity) ** year
            )
            pv_ri = residual_income * discount_factor

            ri_years.append(
                RIYear(
                    year=year,
                    net_income=net_income,
                    beginning_book_value=beg_equity,
                    required_return=required_return,
                    residual_income=residual_income,
                    discount_factor=discount_factor,
                    pv_residual_income=pv_ri,
                )
            )
            sum_pv_ri += pv_ri

        # Terminal RI via Gordon Growth on last explicit RI.
        last_ri = ri_years[-1]
        terminal_ri = last_ri.residual_income * (
            Decimal("1") + terminal_growth_rate
        )
        terminal_value = terminal_ri / (
            terminal_discount_rate - terminal_growth_rate
        )
        terminal_pv = terminal_value * last_ri.discount_factor

        enterprise_value = base_equity + sum_pv_ri + terminal_pv
        equity_value = enterprise_value

        shares_terminal = stream[-1][3]
        fair_value_per_share = (
            equity_value / shares_terminal
            if shares_terminal > 0
            else Decimal("0")
        )

        warnings: list[str] = []
        if last_ri.residual_income < 0:
            warnings.append(
                f"Terminal RI {last_ri.residual_income} is negative — "
                "company earning below CoE on book equity. RI model "
                "penalises but still produces a valuation."
            )
        if sum_pv_ri < 0:
            warnings.append(
                f"Sum of explicit RI PVs is negative ({sum_pv_ri}) — "
                "forecast implies sustained value destruction; RI "
                "valuation sits below base book value."
            )

        return RIProjection(
            scenario_name=projection.scenario_name,
            methodology="RESIDUAL_INCOME",
            base_year_label=projection.base_year_label,
            projection_years=projection.projection_years,
            base_book_value=base_equity,
            years=ri_years,
            terminal_residual_income=terminal_ri,
            terminal_growth_rate=terminal_growth_rate,
            terminal_discount_rate=terminal_discount_rate,
            terminal_value=terminal_value,
            terminal_pv=terminal_pv,
            sum_pv_residual_income=sum_pv_ri,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            shares_outstanding_terminal=shares_terminal,
            fair_value_per_share=fair_value_per_share,
            warnings=warnings,
        )


__all__ = ["RIEngine"]
