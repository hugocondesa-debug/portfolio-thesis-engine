"""Dividend Discount Model valuation engine.

Consumes a :class:`ThreeStatementProjection` (output of Sprint 4A-beta's
forecast orchestrator) and the cost of equity from Sprint-3's
WACCGenerator, and returns a :class:`DDMProjection` with per-year
dividends, terminal value via Gordon Growth, and fair value per share.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import ThreeStatementProjection
from portfolio_thesis_engine.valuation_methodologies.ddm.dividend_stream_extractor import (
    compute_dividend_per_share,
    extract_dividend_stream,
)
from portfolio_thesis_engine.valuation_methodologies.ddm.schemas import (
    DDMProjection,
    DDMYear,
)


class DDMEngine:
    """DDM fair value from forecast projection + cost of equity."""

    def compute(
        self,
        projection: ThreeStatementProjection,
        cost_of_equity: Decimal,
        terminal_growth_rate: Decimal = Decimal("0.025"),
        terminal_discount_rate: Decimal | None = None,
    ) -> DDMProjection:
        """Return a :class:`DDMProjection`.

        Raises ``ValueError`` when the terminal growth is not strictly
        below the terminal discount rate (Gordon-growth singularity) or
        when every projected year pays zero dividend (DDM inapplicable).
        """
        if terminal_discount_rate is None:
            terminal_discount_rate = cost_of_equity

        if terminal_growth_rate >= terminal_discount_rate:
            raise ValueError(
                f"Terminal growth {terminal_growth_rate} must be < terminal "
                f"discount rate {terminal_discount_rate} for Gordon Growth."
            )

        stream = extract_dividend_stream(projection)
        if not stream:
            raise ValueError(
                "ThreeStatementProjection has no cash-flow years — cannot "
                "run DDM without a dividend stream."
            )
        if all(d == 0 for _, d, _ in stream):
            raise ValueError(
                "All projected dividends are zero — DDM not applicable. "
                "Company does not pay dividends or capital_allocation.yaml "
                "dividend_policy.type is ZERO."
            )

        ddm_years: list[DDMYear] = []
        total_explicit_pv = Decimal("0")

        for year, dividend_total, shares in stream:
            dps = compute_dividend_per_share(dividend_total, shares)
            year_coe = cost_of_equity  # Sprint 4B: flat CoE across explicit horizon.
            discount_factor = Decimal("1") / (
                (Decimal("1") + year_coe) ** year
            )
            pv_dividend = dividend_total * discount_factor

            ddm_years.append(
                DDMYear(
                    year=year,
                    dividend_total=dividend_total,
                    dividend_per_share=dps,
                    shares_outstanding=shares,
                    cost_of_equity=year_coe,
                    discount_factor=discount_factor,
                    pv_dividend=pv_dividend,
                )
            )
            total_explicit_pv += pv_dividend

        # Terminal via Gordon on last explicit year's dividend.
        last_year = ddm_years[-1]
        terminal_dividend = last_year.dividend_total * (
            Decimal("1") + terminal_growth_rate
        )
        terminal_value = terminal_dividend / (
            terminal_discount_rate - terminal_growth_rate
        )
        terminal_pv = terminal_value * last_year.discount_factor

        enterprise_value = total_explicit_pv + terminal_pv
        equity_value = enterprise_value  # DDM has no debt bridge.

        shares_terminal = last_year.shares_outstanding
        fair_value_per_share = (
            equity_value / shares_terminal
            if shares_terminal > 0
            else Decimal("0")
        )

        warnings: list[str] = []
        if last_year.dividend_total < ddm_years[0].dividend_total * Decimal("0.5"):
            warnings.append(
                f"Terminal dividend {last_year.dividend_total} is less than "
                f"half of Y1 {ddm_years[0].dividend_total} — dividend cut "
                "scenario; review capital_allocation.yaml."
            )

        return DDMProjection(
            scenario_name=projection.scenario_name,
            methodology="DDM",
            base_year_label=projection.base_year_label,
            projection_years=projection.projection_years,
            years=ddm_years,
            terminal_dividend=terminal_dividend,
            terminal_growth_rate=terminal_growth_rate,
            terminal_discount_rate=terminal_discount_rate,
            terminal_value=terminal_value,
            terminal_pv=terminal_pv,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            shares_outstanding_terminal=shares_terminal,
            fair_value_per_share=fair_value_per_share,
            warnings=warnings,
        )


__all__ = ["DDMEngine"]
