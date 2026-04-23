"""Phase 2 Sprint 2A — analytical computers.

- DuPont 3-way ROE decomposition + ROE driver attribution.
- ROIC decomposition (NOPAT margin × IC turnover) + spread classification.
- Trend analysis across records (CAGRs, margin/ROIC/capex deltas).
- Quality of Earnings composite score with per-component exposure.
- Investment signal synthesis from the above.

All helpers are pure functions — given the inputs, they emit the
schema object and never mutate anything else.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.historicals import (
    DuPont3Way,
    HistoricalPeriodType,
    HistoricalRecord,
    InvestmentSignal,
    QualityOfEarnings,
    ROEDriverAttribution,
    ROICDecomposition,
    ROICDriverAttribution,
    TrendAnalysis,
)
from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

_BPS = Decimal("10000")  # 100 pp = 10 000 bps
_HUNDRED = Decimal("100")

# ----------------------------------------------------------------------
# DuPont 3-way ROE
# ----------------------------------------------------------------------
def compute_dupont_3way(record: HistoricalRecord) -> DuPont3Way | None:
    """Return a :class:`DuPont3Way` when all four inputs are present
    (revenue, net_income, total_assets, total_equity). Otherwise
    ``None`` — historical records with partial financial data shouldn't
    fabricate a decomposition."""
    revenue = record.revenue
    ni = record.net_income
    assets = record.total_assets
    equity = record.total_equity
    if not all(v is not None and v != 0 for v in (revenue, ni, assets, equity)):
        return None
    # mypy / pyright can't narrow through ``all`` — assert for clarity.
    assert revenue is not None and ni is not None
    assert assets is not None and equity is not None
    net_margin = ni / revenue
    asset_turnover = revenue / assets
    financial_leverage = assets / equity
    roe_computed = net_margin * asset_turnover * financial_leverage
    roe_reported = ni / equity
    return DuPont3Way(
        period=record.period,
        net_margin=net_margin * _HUNDRED,
        asset_turnover=asset_turnover,
        financial_leverage=financial_leverage,
        roe_computed=roe_computed * _HUNDRED,
        roe_reported=roe_reported * _HUNDRED,
        reconciliation_delta=(roe_computed - roe_reported) * _HUNDRED,
    )


def attribute_roe_change(
    period_a: DuPont3Way, period_b: DuPont3Way
) -> ROEDriverAttribution | None:
    """Decompose ΔROE from ``period_a`` → ``period_b`` into
    margin / turnover / leverage contributions in basis points.
    Returns ``None`` when either input lacks a required driver."""
    margins = (period_a.net_margin, period_b.net_margin)
    turnovers = (period_a.asset_turnover, period_b.asset_turnover)
    leverages = (period_a.financial_leverage, period_b.financial_leverage)
    for a, b in (margins, turnovers, leverages):
        if a is None or b is None:
            return None
    assert period_a.net_margin is not None and period_b.net_margin is not None
    assert period_a.asset_turnover is not None and period_b.asset_turnover is not None
    assert period_a.financial_leverage is not None and period_b.financial_leverage is not None
    delta_margin = period_b.net_margin - period_a.net_margin
    delta_turn = period_b.asset_turnover - period_a.asset_turnover
    delta_lev = period_b.financial_leverage - period_a.financial_leverage
    # ROE = margin(%) / 100 × turnover × leverage
    # Contributions in bps: all scaled by 100 so margin delta (already %)
    # × turnover × leverage → bps.
    margin_contrib = delta_margin * period_a.asset_turnover * period_a.financial_leverage
    turn_contrib = (
        period_a.net_margin * delta_turn * period_a.financial_leverage
    )
    lev_contrib = (
        period_a.net_margin * period_a.asset_turnover * delta_lev
    )
    roe_delta = (
        period_b.roe_computed - period_a.roe_computed
        if (period_a.roe_computed is not None and period_b.roe_computed is not None)
        else Decimal("0")
    )
    # All already in % space → convert to bps via × 100.
    roe_delta_bps = roe_delta * _HUNDRED
    margin_bps = margin_contrib * _HUNDRED
    turn_bps = turn_contrib * _HUNDRED
    lev_bps = lev_contrib * _HUNDRED
    cross = roe_delta_bps - margin_bps - turn_bps - lev_bps
    return ROEDriverAttribution(
        period_from=period_a.period,
        period_to=period_b.period,
        roe_delta_bps=roe_delta_bps,
        margin_contribution_bps=margin_bps,
        turnover_contribution_bps=turn_bps,
        leverage_contribution_bps=lev_bps,
        cross_residual_bps=cross,
    )


# ----------------------------------------------------------------------
# ROIC decomposition
# ----------------------------------------------------------------------
def _classify_roic_spread(spread_bps: Decimal) -> str:
    if spread_bps < Decimal("-100"):
        return "DESTROYING"
    if spread_bps <= Decimal("100"):
        return "NEUTRAL"
    if spread_bps <= Decimal("500"):
        return "MODEST"
    return "STRONG"


def compute_roic_decomposition(
    record: HistoricalRecord, wacc_pct: Decimal | None = None
) -> ROICDecomposition | None:
    """Two-way ROIC decomposition. Returns ``None`` when revenue or
    invested_capital is missing (can't form the turnover)."""
    revenue = record.revenue
    ic = record.invested_capital
    nopat = record.nopat
    if revenue is None or revenue == 0 or ic is None or ic == 0:
        return None
    assert revenue is not None and ic is not None
    nopat_margin = (nopat / revenue) if nopat is not None else None
    ic_turnover = revenue / ic
    roic_computed = (
        nopat_margin * ic_turnover if nopat_margin is not None else None
    )
    spread_bps: Decimal | None = None
    value_signal: str | None = None
    if roic_computed is not None and wacc_pct is not None:
        spread_pct = roic_computed * _HUNDRED - wacc_pct
        spread_bps = spread_pct * _HUNDRED
        value_signal = _classify_roic_spread(spread_bps)
    return ROICDecomposition(
        period=record.period,
        nopat_margin=nopat_margin * _HUNDRED if nopat_margin is not None else None,
        ic_turnover=ic_turnover,
        roic_computed=roic_computed * _HUNDRED if roic_computed is not None else None,
        roic_reported=record.roic_primary,
        wacc=wacc_pct,
        spread_bps=spread_bps,
        value_signal=value_signal,  # type: ignore[arg-type]
    )


def attribute_roic_change(
    period_a: ROICDecomposition, period_b: ROICDecomposition
) -> ROICDriverAttribution | None:
    for attr in ("nopat_margin", "ic_turnover"):
        if getattr(period_a, attr) is None or getattr(period_b, attr) is None:
            return None
    assert period_a.nopat_margin is not None and period_b.nopat_margin is not None
    assert period_a.ic_turnover is not None and period_b.ic_turnover is not None
    delta_margin = period_b.nopat_margin - period_a.nopat_margin
    delta_turn = period_b.ic_turnover - period_a.ic_turnover
    margin_contrib = delta_margin * period_a.ic_turnover
    turn_contrib = period_a.nopat_margin * delta_turn
    roic_delta = (
        (period_b.roic_computed or Decimal("0"))
        - (period_a.roic_computed or Decimal("0"))
    )
    roic_delta_bps = roic_delta * _HUNDRED
    margin_bps = margin_contrib * _HUNDRED
    turn_bps = turn_contrib * _HUNDRED
    cross = roic_delta_bps - margin_bps - turn_bps
    return ROICDriverAttribution(
        period_from=period_a.period,
        period_to=period_b.period,
        roic_delta_bps=roic_delta_bps,
        nopat_margin_contribution_bps=margin_bps,
        ic_turnover_contribution_bps=turn_bps,
        cross_residual_bps=cross,
    )


# ----------------------------------------------------------------------
# Quality of Earnings
# ----------------------------------------------------------------------
_AUDIT_NUMERIC = {
    AuditStatus.AUDITED: Decimal("1.0"),
    AuditStatus.REVIEWED: Decimal("0.7"),
    AuditStatus.UNAUDITED: Decimal("0.4"),
}


def _score_accruals(ratio: Decimal | None) -> int | None:
    if ratio is None:
        return None
    abs_ratio = abs(ratio)
    if abs_ratio <= Decimal("0.05"):
        return 100
    if abs_ratio <= Decimal("0.10"):
        return 85
    if abs_ratio <= Decimal("0.15"):
        return 65
    return 30


def _score_cfo_ni(ratio: Decimal | None) -> int | None:
    if ratio is None:
        return None
    if ratio >= Decimal("1"):
        return 100
    if ratio >= Decimal("0.85"):
        return 85
    if ratio >= Decimal("0.70"):
        return 70
    return 40


def _score_ar_revenue(delta_pp: Decimal | None) -> int | None:
    if delta_pp is None:
        return None
    if delta_pp <= 0:
        return 100
    if delta_pp <= Decimal("2"):
        return 80
    if delta_pp <= Decimal("5"):
        return 60
    return 30


def _score_non_recurring(share: Decimal | None) -> int | None:
    if share is None:
        return None
    if share <= Decimal("0.20"):
        return 100
    if share <= Decimal("0.40"):
        return 75
    if share <= Decimal("0.60"):
        return 50
    return 25


def _score_audit(numeric: Decimal | None) -> int | None:
    if numeric is None:
        return None
    if numeric >= Decimal("1.0"):
        return 100
    if numeric >= Decimal("0.7"):
        return 70
    return 40


def compute_qoe(
    record: HistoricalRecord,
    *,
    cfo: Decimal | None = None,
    prior_revenue: Decimal | None = None,
    prior_ar: Decimal | None = None,
    non_recurring_items_share: Decimal | None = None,
) -> QualityOfEarnings:
    """Compute QoE for a single record. Inputs not available on
    :class:`HistoricalRecord` (CFO, prior-period AR / revenue,
    non-recurring share) are passed explicitly by the caller.

    Composite is weighted 30 / 20 / 15 / 20 / 15. When a component is
    missing, the composite is scaled by the sum of the available
    weights so partial-information records still produce a number
    instead of leaving composite ``None``.
    """
    audit_numeric = _AUDIT_NUMERIC.get(record.audit_status, Decimal("1"))

    accruals_ratio: Decimal | None = None
    if record.total_assets and record.net_income is not None and cfo is not None:
        accruals_ratio = (record.net_income - cfo) / record.total_assets
    cfo_ni_ratio: Decimal | None = None
    if cfo is not None and record.net_income not in (None, Decimal("0")):
        assert record.net_income is not None
        cfo_ni_ratio = cfo / record.net_income

    ar_delta_pp: Decimal | None = None
    if (
        record.revenue is not None
        and prior_revenue not in (None, Decimal("0"))
        and prior_ar not in (None, Decimal("0"))
    ):
        assert prior_revenue is not None and prior_ar is not None
        # Record doesn't carry AR directly; callers should pass current
        # AR via side channel (Phase 2 Sprint 2B adds AR to the record).
        # For Sprint 2A we skip if AR current is absent — keeps the
        # ratio honest.
        ar_delta_pp = None

    accruals_score = _score_accruals(accruals_ratio)
    cfo_ni_score = _score_cfo_ni(cfo_ni_ratio)
    ar_score = _score_ar_revenue(ar_delta_pp)
    non_rec_score = _score_non_recurring(non_recurring_items_share)
    audit_score = _score_audit(audit_numeric)

    weights = {
        "accruals": (Decimal("0.30"), accruals_score),
        "cfo": (Decimal("0.20"), cfo_ni_score),
        "ar": (Decimal("0.15"), ar_score),
        "non_rec": (Decimal("0.20"), non_rec_score),
        "audit": (Decimal("0.15"), audit_score),
    }
    available = [
        (w, s) for w, s in weights.values() if s is not None
    ]
    composite: int | None = None
    if available:
        weight_sum = sum(w for w, _ in available)
        weighted = sum(w * Decimal(s) for w, s in available)
        composite = int(round(float(weighted / weight_sum))) if weight_sum else None

    flags: list[str] = []
    if accruals_score is not None and accruals_score < 60:
        flags.append("WEAK_ACCRUALS_QUALITY")
    if cfo_ni_score is not None and cfo_ni_score < 60:
        flags.append("CFO_LAGS_NI")
    if ar_score is not None and ar_score < 60:
        flags.append("AR_GROWING_FASTER_THAN_REVENUE")
    if non_rec_score is not None and non_rec_score < 60:
        flags.append("HIGH_NON_RECURRING_SHARE")
    if audit_score is not None and audit_score < 60:
        flags.append("NON_AUDITED_SOURCE")

    return QualityOfEarnings(
        period=record.period,
        accruals_to_assets=accruals_ratio,
        cfo_to_ni_ratio=cfo_ni_ratio,
        ar_growth_vs_revenue_growth_delta=ar_delta_pp,
        non_recurring_items_share=non_recurring_items_share,
        audit_status_numeric=audit_numeric,
        accruals_quality_score=accruals_score,
        cfo_ni_score=cfo_ni_score,
        ar_revenue_score=ar_score,
        non_recurring_score=non_rec_score,
        audit_score=audit_score,
        composite_score=composite,
        flags=flags,
    )


# ----------------------------------------------------------------------
# Trend analysis
# ----------------------------------------------------------------------
def _cagr(start: Decimal, end: Decimal, years: int) -> Decimal | None:
    if start is None or end is None or start <= 0 or years <= 0:
        return None
    ratio = end / start
    if ratio <= 0:
        return None
    # CAGR = ratio ** (1/years) - 1; compute via float to avoid
    # Decimal ** non-integer restrictions.
    cagr = Decimal(str(float(ratio) ** (1.0 / years) - 1.0))
    return cagr * _HUNDRED  # %


def _trajectory_from_deltas(
    recent_delta: Decimal | None, long_run_delta: Decimal | None
) -> str:
    if recent_delta is None:
        return "STABLE"
    if long_run_delta is None:
        if recent_delta > Decimal("1"):
            return "ACCELERATING"
        if recent_delta < Decimal("-1"):
            return "DECELERATING"
        return "STABLE"
    if recent_delta > long_run_delta + Decimal("1"):
        return "ACCELERATING"
    if recent_delta < long_run_delta - Decimal("1"):
        return "DECELERATING"
    return "STABLE"


def compute_trends(records: list[HistoricalRecord]) -> TrendAnalysis | None:
    """Build a :class:`TrendAnalysis` from a list of records sorted
    ascending by ``period_end``.

    Phase 2 Sprint 2A.1 — CAGR math must use **only annual audited/
    reviewed** records. Interims, TTM, and preliminary observations
    previously leaked into the list (H1_2025 pretended to be an annual
    point at index ``[-3]`` and produced a 45 % 2Y CAGR against
    FY2025). Comparatives (from a neighbouring AR's prior-year column)
    are still accepted because they're annual observations with full
    audit posture.

    Returns ``None`` only when fewer than two annual records are
    available. With exactly two annuals the CAGR columns stay blank and
    ``revenue_yoy_growth`` surfaces a single-period growth rate.
    """
    annuals = [
        r for r in records
        if r.period_type == HistoricalPeriodType.ANNUAL
        and r.audit_status != AuditStatus.UNAUDITED
        and r.revenue is not None
    ]
    if len(annuals) < 2:
        return None
    annuals.sort(key=lambda r: r.period_end)
    start = annuals[0]
    end = annuals[-1]
    years = end.period_end.year - start.period_end.year

    cagr_2y: Decimal | None = None
    cagr_3y: Decimal | None = None
    cagr_5y: Decimal | None = None
    if len(annuals) >= 3 and annuals[-3].revenue is not None:
        cagr_2y = _cagr(annuals[-3].revenue, end.revenue, 2)
    if len(annuals) >= 4 and annuals[-4].revenue is not None:
        cagr_3y = _cagr(annuals[-4].revenue, end.revenue, 3)
    if len(annuals) >= 6 and annuals[-6].revenue is not None:
        cagr_5y = _cagr(annuals[-6].revenue, end.revenue, 5)

    # Phase 2 Sprint 2A.1 — YoY fallback when we can't yet build a
    # multi-year CAGR (e.g. EuroEyes: only FY2023 + FY2024 audited so
    # far). Expressed as a percentage, same as the CAGR columns.
    yoy_growth: Decimal | None = None
    if len(annuals) >= 2 and annuals[-2].revenue:
        yoy_growth = (end.revenue / annuals[-2].revenue - Decimal("1")) * _HUNDRED

    total_cagr = (
        _cagr(start.revenue, end.revenue, years)
        if years > 0 else None
    )

    revenue_trajectory = _trajectory_from_deltas(cagr_2y, total_cagr)

    margin_delta_bps: Decimal | None = None
    margin_trajectory = "STABLE"
    if (
        start.operating_margin_reported is not None
        and end.operating_margin_reported is not None
    ):
        margin_delta = (
            end.operating_margin_reported - start.operating_margin_reported
        )
        margin_delta_bps = margin_delta * _HUNDRED
        if margin_delta_bps > Decimal("50"):
            margin_trajectory = "EXPANDING"
        elif margin_delta_bps < Decimal("-50"):
            margin_trajectory = "CONTRACTING"

    roic_delta_bps: Decimal | None = None
    roic_trajectory = "STABLE"
    if (
        start.roic_primary is not None
        and end.roic_primary is not None
    ):
        roic_delta_bps = (end.roic_primary - start.roic_primary) * _HUNDRED
        if roic_delta_bps > Decimal("100"):
            roic_trajectory = "IMPROVING"
        elif roic_delta_bps < Decimal("-100"):
            roic_trajectory = "DECLINING"

    return TrendAnalysis(
        period_start=start.period,
        period_end=end.period,
        revenue_cagr_2y=cagr_2y,
        revenue_cagr_3y=cagr_3y,
        revenue_cagr_5y=cagr_5y,
        revenue_yoy_growth=yoy_growth,
        annuals_used_for_cagr=len(annuals),
        revenue_trajectory=revenue_trajectory,  # type: ignore[arg-type]
        operating_margin_delta_bps=margin_delta_bps,
        operating_margin_trajectory=margin_trajectory,  # type: ignore[arg-type]
        roic_delta_bps=roic_delta_bps,
        roic_trajectory=roic_trajectory,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------
# Investment signal synthesis
# ----------------------------------------------------------------------
def synthesise_investment_signal(
    records: list[HistoricalRecord],
    trends: TrendAnalysis | None,
    latest_roic_decomposition: ROICDecomposition | None,
    latest_qoe: QualityOfEarnings | None,
) -> InvestmentSignal:
    """Rule-based synthesis combining the analytical layers."""
    signal = InvestmentSignal()

    if latest_roic_decomposition is not None and latest_roic_decomposition.spread_bps is not None:
        spread = int(latest_roic_decomposition.spread_bps)
        signal.current_value_spread_bps = spread
        if spread < -100:
            signal.current_value_creation = "DESTROYING"
        elif spread <= 100:
            signal.current_value_creation = "NEUTRAL"
        else:
            signal.current_value_creation = "CREATING"

    if trends is not None:
        signal.growth_trajectory = trends.revenue_trajectory
        signal.margin_trend = trends.operating_margin_trajectory
        if trends.roic_trajectory == "IMPROVING":
            signal.capital_efficiency_trend = "IMPROVING"
        elif trends.roic_trajectory == "DECLINING":
            signal.capital_efficiency_trend = "DETERIORATING"
        else:
            signal.capital_efficiency_trend = "STABLE"

    if latest_qoe is not None and latest_qoe.composite_score is not None:
        signal.earnings_quality_score = latest_qoe.composite_score

    # Balance sheet strength — trivial heuristic: records that have a
    # financial_debt value >= 2 × cash → weak, <= 0.5 × → strong.
    latest = next(
        (r for r in reversed(records) if r.period_relation == "primary"),
        None,
    )
    if latest is not None and latest.cash_and_equivalents is not None and latest.financial_debt is not None:
        cash = latest.cash_and_equivalents
        debt = latest.financial_debt
        if cash > 0 and debt / cash <= Decimal("0.5"):
            signal.balance_sheet_strength = "STRONG"
        elif cash > 0 and debt / cash >= Decimal("2"):
            signal.balance_sheet_strength = "WEAK"
        else:
            signal.balance_sheet_strength = "ADEQUATE"

    bullets: list[str] = []
    if signal.current_value_creation != "NEUTRAL":
        bullets.append(
            f"Current value creation: {signal.current_value_creation} "
            f"({signal.current_value_spread_bps} bps spread vs WACC)"
        )
    if signal.growth_trajectory != "STABLE":
        bullets.append(f"Revenue trajectory: {signal.growth_trajectory}")
    if signal.capital_efficiency_trend != "STABLE":
        bullets.append(
            f"Capital efficiency: {signal.capital_efficiency_trend}"
        )
    if signal.margin_trend != "STABLE":
        bullets.append(f"Margin trend: {signal.margin_trend}")
    if signal.earnings_quality_score is not None:
        bullets.append(
            f"Earnings quality composite: {signal.earnings_quality_score}/100"
        )
    if signal.balance_sheet_strength != "UNKNOWN":
        bullets.append(
            f"Balance sheet strength: {signal.balance_sheet_strength}"
        )
    signal.summary_bullets = bullets
    return signal


__all__ = [
    "attribute_roe_change",
    "attribute_roic_change",
    "compute_dupont_3way",
    "compute_qoe",
    "compute_roic_decomposition",
    "compute_trends",
    "synthesise_investment_signal",
]
