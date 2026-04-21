"""Valuation Snapshot — output of forecast & valuation system.

:class:`ValuationSnapshot` is the top-level immutable, versioned output.
Portfolio reads current snapshots but never writes into them.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, ImmutableSchema, VersionedMixin
from portfolio_thesis_engine.schemas.common import (
    ConvictionLevel,
    Currency,
    FiscalPeriod,
    GuardrailStatus,
    Money,
    Percentage,
    Profile,
)


class ScenarioDrivers(BaseSchema):
    """Key drivers defining a scenario. Shape varies by profile."""

    revenue_cagr: Percentage | None = None
    terminal_growth: Percentage | None = None
    terminal_margin: Percentage | None = None
    terminal_roic: Percentage | None = None
    terminal_wacc: Percentage | None = None

    # P2-specific
    terminal_roe: Percentage | None = None
    terminal_payout: Percentage | None = None
    terminal_nim: Percentage | None = None
    terminal_cor_bps: int | None = None
    terminal_cost_income: Percentage | None = None
    terminal_cet1: Percentage | None = None

    custom_drivers: dict[str, Decimal] = Field(default_factory=dict)


class SurvivalCondition(BaseSchema):
    """Condition that keeps a scenario alive."""

    metric: str
    on_track: str
    warning: str
    source: str | None = None
    last_observed: str | None = None


class Scenario(BaseSchema):
    """A scenario definition (``bear``, ``base``, ``bull``, or custom)."""

    label: str
    description: str
    probability: Annotated[Decimal, Field(ge=0, le=100)]
    horizon_years: int = Field(default=3, ge=1, le=10)

    drivers: ScenarioDrivers
    targets: dict[str, Money] = Field(default_factory=dict)

    irr_3y: Percentage | None = None
    irr_5y: Percentage | None = None
    irr_decomposition: dict[str, Percentage] | None = None

    upside_pct: Percentage | None = None

    survival_conditions: list[SurvivalCondition] = Field(default_factory=list)
    kill_signals: list[str] = Field(default_factory=list)


class MarketImpliedView(BaseSchema):
    """What the market is pricing."""

    roe_terminal: Percentage | None = None
    prob_bear: Percentage | None = None
    prob_base: Percentage | None = None
    prob_bull: Percentage | None = None
    growth_implied_in_price: Percentage | None = None
    custom_fields: dict[str, Decimal] = Field(default_factory=dict)


class GapDecomposition(BaseSchema):
    """Decomposition of the gap between model and market."""

    driver: str
    delta: str
    contribution_value: Decimal
    pct_of_gap: Percentage
    prove_right: str | None = None
    prove_wrong: str | None = None


class ReverseAnalysis(BaseSchema):
    """Reverse DDM / DCF analysis."""

    market_implied: MarketImpliedView
    gap_total_value: Decimal
    gap_unit: str
    gap_decomposition: list[GapDecomposition]


class MonteCarloResult(BaseSchema):
    """Monte Carlo simulation output."""

    iterations: int
    p10: Money
    p25: Money
    p50: Money
    p75: Money
    p90: Money
    prob_above_current: Percentage


class CorrelatedStress(BaseSchema):
    """Correlated stress test result."""

    value_per_share: Money
    assumptions: dict[str, str] = Field(default_factory=dict)


class ConsensusComparison(BaseSchema):
    """Comparison with sell-side consensus."""

    tp_avg: Money | None = None
    tp_range_low: Money | None = None
    tp_range_high: Money | None = None
    analyst_count: int | None = None
    quality_note: str | None = None


class CrossChecks(BaseSchema):
    """All cross-check analyses."""

    monte_carlo: MonteCarloResult | None = None
    correlated_stress: CorrelatedStress | None = None
    consensus: ConsensusComparison | None = None


class EPSBridgeComponent(BaseSchema):
    """Single component in the EPS bridge."""

    item: str
    impact: Decimal


class EPSBridgeYear(BaseSchema):
    """EPS bridge for a specific year."""

    period: FiscalPeriod
    model: Decimal
    consensus: Decimal | None = None
    gap: Decimal | None = None
    components: list[EPSBridgeComponent] = Field(default_factory=list)


class EPSBridge(BaseSchema):
    """Multi-year EPS bridge."""

    years: list[EPSBridgeYear]


class Catalyst(BaseSchema):
    """Single catalyst event."""

    date: str
    event: str
    scenarios_affected: list[str]
    impact: str
    probability: Percentage | None = None
    notes: str | None = None


class WeightedOutputs(BaseSchema):
    """Probability-weighted outputs across scenarios."""

    expected_value: Money
    expected_value_method_used: str
    fair_value_range_low: Money
    fair_value_range_high: Money
    upside_pct: Percentage
    asymmetry_ratio: Decimal
    weighted_irr_3y: Percentage | None = None
    weighted_irr_5y: Percentage | None = None


class GuardrailCategory(BaseSchema):
    """Guardrail results for one category (A–F)."""

    category: str
    total: int
    passed: int
    warned: int
    failed: int
    skipped: int
    notes: list[str] = Field(default_factory=list)


class GuardrailsStatus(BaseSchema):
    """All guardrails status."""

    categories: list[GuardrailCategory]
    overall: GuardrailStatus


class MarketSnapshot(BaseSchema):
    """Market data at the time of valuation."""

    price: Money
    price_date: str
    shares_outstanding: Decimal | None = None
    market_cap: Money | None = None
    cost_of_equity: Percentage | None = None
    wacc: Percentage | None = None
    currency: Currency


class FactorExposure(BaseSchema):
    """Single factor exposure."""

    factor: str
    beta: Decimal
    r_squared: Decimal
    window_months: int
    computed_at: str


class Conviction(BaseSchema):
    """Conviction levels across dimensions."""

    forecast: ConvictionLevel
    valuation: ConvictionLevel
    asymmetry: ConvictionLevel
    timing_risk: ConvictionLevel
    liquidity_risk: ConvictionLevel
    governance_risk: ConvictionLevel


class ValuationSnapshot(ImmutableSchema, VersionedMixin):
    """Immutable, versioned output of the valuation system."""

    snapshot_id: str
    ticker: str
    company_name: str
    profile: Profile
    valuation_date: datetime

    based_on_extraction_id: str
    based_on_extraction_date: datetime

    market: MarketSnapshot

    scenarios: list[Scenario]

    weighted: WeightedOutputs

    reverse: ReverseAnalysis | None = None
    cross_checks: CrossChecks | None = None
    eps_bridge: EPSBridge | None = None

    catalysts: list[Catalyst] = Field(default_factory=list)
    factor_exposures: list[FactorExposure] = Field(default_factory=list)
    scenario_response: dict[str, Any] | None = None

    conviction: Conviction
    guardrails: GuardrailsStatus

    forecast_system_version: str
    source_documents: list[str] = Field(default_factory=list)

    total_api_cost_usd: Decimal | None = None
