"""Phase 2 Sprint 4A-alpha — DCF schemas.

Separate module from the Phase-1 ``schemas/valuation.py`` because the
Phase-1 Scenario class is already defined there with a different
shape. Sprint 4's scenarios are richer (probability-weighted with
unlimited count + driver overrides over a common base set).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema


class DCFProfile(StrEnum):
    """Six DCF profiles covering the valuation universe.

    Sprint 4A-alpha implements P1 only; the other five raise
    :class:`NotImplementedError` in the orchestrator and land in
    Sprint 4A-beta, 4B, 4C respectively.
    """

    P1_INDUSTRIAL_SERVICES = "P1"
    P2_FINANCIAL = "P2"
    P3_REIT = "P3"
    P4_CYCLICAL_COMMODITY = "P4"
    P5_HIGH_GROWTH = "P5"
    P6_MATURE_STABLE = "P6"


class TerminalMethod(StrEnum):
    """Sprint 4A-alpha.3 — terminal value methodology for DCF engines.

    ``GORDON_GROWTH`` is the classic Damodaran formulation
    (``FCF × (1 + g) / (WACC − g)``). ``TERMINAL_MULTIPLE`` anchors
    the terminal value on an observable market multiple applied to the
    terminal-year metric (EV/EBITDA, EV/Sales, PE) — useful when
    Gordon growth is degenerate (WACC ≤ g) or when the analyst wants
    to cross-validate an intrinsic DCF against a peer-derived exit
    price."""

    GORDON_GROWTH = "GORDON_GROWTH"
    TERMINAL_MULTIPLE = "TERMINAL_MULTIPLE"


class ValuationMethodology(StrEnum):
    """Sprint 4A-alpha.2 — per-scenario valuation methodology.

    Each scenario in a :class:`ScenarioSet` declares its methodology;
    the :class:`ValuationEngine` dispatcher routes to the appropriate
    engine. M1-M3 + M10 implemented in Sprint 4A-alpha; M4-M9 stubbed
    for Sprint 4B (financials) / 4C (cyclicals) / 4D (asset-based).
    """

    DCF_3_STAGE = "DCF_3_STAGE"          # M1
    DCF_2_STAGE = "DCF_2_STAGE"          # M2
    MULTIPLE_EXIT = "MULTIPLE_EXIT"      # M3
    DDM = "DDM"                          # M4 — Sprint 4B
    RESIDUAL_INCOME = "RESIDUAL_INCOME"  # M5 — Sprint 4B
    FFO_BASED = "FFO_BASED"              # M6 — Sprint 4B
    NORMALIZED_DCF = "NORMALIZED_DCF"    # M7 — Sprint 4C
    THROUGH_CYCLE_DCF = "THROUGH_CYCLE_DCF"          # M8 — Sprint 4C
    ASSET_BASED = "ASSET_BASED"          # M9 — Sprint 4D
    TRANSACTION_PRECEDENT = "TRANSACTION_PRECEDENT"  # M10


_Confidence = Literal["HIGH", "MEDIUM", "LOW"]
_ProfileSource = Literal["HEURISTIC_SUGGESTION", "USER_OVERRIDE"]
_WarningSeverity = Literal["INFO", "WARNING", "CRITICAL"]
_FadeShape = Literal["LINEAR", "FRONT_LOADED", "BACK_LOADED"]
_DCFStructureType = Literal[
    "THREE_STAGE",
    "TWO_STAGE",
    "SINGLE_STAGE",
    "DDM",
    "FFO",
    "THROUGH_CYCLE",
    "EXPLICIT_TO_MATURITY",
]
_TerminalMethod = Literal["GORDON_GROWTH", "TERMINAL_MULTIPLE"]


class ProfileHeuristic(BaseSchema):
    """Suggestion emitted by :func:`infer_profile_from_industry`."""

    sic_code: str | None = None
    gics_sector: str | None = None
    gics_industry: str | None = None
    suggested_profile: DCFProfile
    confidence: _Confidence
    rationale: str


# ----------------------------------------------------------------------
# Valuation profile YAML schema
# ----------------------------------------------------------------------
class ProfileSelection(BaseSchema):
    code: DCFProfile
    source: _ProfileSource = "HEURISTIC_SUGGESTION"
    heuristic_suggestion: DCFProfile | None = None
    confidence: _Confidence = "MEDIUM"
    rationale: str = ""


class DCFStructure(BaseSchema):
    type: _DCFStructureType = "THREE_STAGE"
    explicit_years: int = 5
    fade_years: int = 5
    terminal_method: _TerminalMethod = "GORDON_GROWTH"


class WACCEvolution(BaseSchema):
    stage_1_source: str = "SPRINT_3_AUTO"
    stage_3_method: str = "COMPUTED_MATURE"
    stage_3_mature_beta: Decimal = Decimal("0.70")
    stage_3_target_leverage: Decimal = Decimal("0.20")
    fade_shape: _FadeShape = "LINEAR"


class TerminalValueConfig(BaseSchema):
    growth_rate: Decimal = Decimal("0.025")
    cross_check_multiple_type: str = "EV_EBITDA"
    cross_check_industry_median: Decimal | None = None
    warning_threshold: Decimal = Decimal("1.5")


class TargetCapitalStructure(BaseSchema):
    target_debt_to_total_capital: Decimal = Decimal("0")
    debt_evolution_policy: Literal[
        "MAINTAIN", "PAYDOWN", "LEVER_UP", "MATCH_PEER_MEDIAN"
    ] = "MAINTAIN"


class NormalizationConfig(BaseSchema):
    """Sprint 4C — only relevant for P4 profiles. Accepted in YAML for
    forward-compat but ignored by P1 orchestrator."""

    method: str | None = None
    historical_window_years: int | None = None
    cycle_characteristics: dict[str, Any] = Field(default_factory=dict)


class ValuationProfile(BaseSchema):
    """Contents of ``data/yamls/companies/<ticker>/valuation_profile.yaml``."""

    target_ticker: str
    profile: ProfileSelection
    dcf_structure: DCFStructure = Field(default_factory=DCFStructure)
    wacc_evolution: WACCEvolution = Field(default_factory=WACCEvolution)
    terminal_value: TerminalValueConfig = Field(default_factory=TerminalValueConfig)
    target_capital_structure: TargetCapitalStructure = Field(
        default_factory=TargetCapitalStructure
    )
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)
    # Scenario-4C stub — ``{"cycle_length_years": int | None}`` etc.
    cycle_characteristics: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# Scenarios YAML schema
# ----------------------------------------------------------------------
class ScenarioDriverOverride(BaseSchema):
    """Per-driver override. Fields are sparse — analysts only set the
    ones that differ from the ``base_drivers`` block."""

    current: Decimal | None = None
    target_terminal: Decimal | None = None
    growth_pattern: list[Decimal] | None = None
    fade_pattern: _FadeShape | None = None


# ----------------------------------------------------------------------
# Sprint 4A-alpha.2 — per-scenario methodology config schemas
# ----------------------------------------------------------------------
# Discriminated by the ``type`` literal. Pydantic v2 picks the correct
# class via the ``MethodologyConfig`` Annotated union below.
class DCFMethodologyConfig(BaseSchema):
    """M1 / M2 — classic 3-stage (or 2-stage when fade_years=0) DCF.

    Sprint 4A-alpha.3 — ``terminal_method`` now accepts either
    ``GORDON_GROWTH`` (needs ``terminal_growth``) or
    ``TERMINAL_MULTIPLE`` (needs the ``terminal_multiple_*`` fields).
    ``validate_terminal_method_fields`` enforces the required-fields
    contract.
    """

    type: Literal["DCF_3_STAGE", "DCF_2_STAGE"]
    explicit_years: int = 5
    fade_years: int = 5
    terminal_method: TerminalMethod = TerminalMethod.GORDON_GROWTH

    # Gordon-growth branch
    terminal_growth: Decimal | None = Decimal("0.025")

    # Terminal-multiple branch (Sprint 4A-alpha.3)
    terminal_multiple_metric: (
        Literal["EV_EBITDA", "EV_SALES", "PE"] | None
    ) = None
    terminal_multiple_source: (
        Literal["INDUSTRY_MEDIAN", "PEER_MEDIAN", "USER_SPECIFIED"] | None
    ) = None
    terminal_multiple_value: Decimal | None = None

    @model_validator(mode="after")
    def _validate_terminal_method_fields(self) -> "DCFMethodologyConfig":
        if self.terminal_method == TerminalMethod.GORDON_GROWTH:
            if self.terminal_growth is None:
                raise ValueError(
                    "GORDON_GROWTH terminal method requires "
                    "terminal_growth."
                )
        elif self.terminal_method == TerminalMethod.TERMINAL_MULTIPLE:
            if self.terminal_multiple_metric is None:
                raise ValueError(
                    "TERMINAL_MULTIPLE terminal method requires "
                    "terminal_multiple_metric."
                )
            if self.terminal_multiple_source is None:
                raise ValueError(
                    "TERMINAL_MULTIPLE terminal method requires "
                    "terminal_multiple_source."
                )
            if (
                self.terminal_multiple_source == "USER_SPECIFIED"
                and self.terminal_multiple_value is None
            ):
                raise ValueError(
                    "USER_SPECIFIED terminal multiple requires "
                    "terminal_multiple_value."
                )
        return self


class MultipleExitMethodologyConfig(BaseSchema):
    """M3 — project forward to ``metric_year``, apply a target
    multiple, discount the exit enterprise value back to present.
    """

    type: Literal["MULTIPLE_EXIT"] = "MULTIPLE_EXIT"
    metric: Literal[
        "CURRENT_EBITDA",
        "FORWARD_EBITDA",
        "TTM_EBITDA",
        "NORMALIZED_EBITDA",
    ] = "FORWARD_EBITDA"
    metric_year: int = 0
    multiple_source: Literal[
        "PEER_MEDIAN",
        "INDUSTRY_MEDIAN",
        "HISTORICAL_OWN",
        "USER_SPECIFIED",
    ] = "PEER_MEDIAN"
    multiple_value: Decimal | None = None
    multiple_multiplier: Decimal = Decimal("1.0")
    discount_rate_source: Literal["STAGE_1_WACC", "USER_SPECIFIED"] = "STAGE_1_WACC"
    discount_rate_override: Decimal | None = None


class TransactionPrecedentMethodologyConfig(BaseSchema):
    """M10 — M&A precedent multiple + control premium, treated as
    immediately realisable (no PV discount)."""

    type: Literal["TRANSACTION_PRECEDENT"] = "TRANSACTION_PRECEDENT"
    metric: Literal["TTM_EBITDA", "CURRENT_EBITDA", "NORMALIZED_EBITDA"] = "TTM_EBITDA"
    multiple_source: Literal["TRANSACTION_DATABASE", "USER_SPECIFIED"] = "USER_SPECIFIED"
    multiple_value: Decimal | None = None
    control_premium: Decimal = Decimal("0.0")


class AssetBasedMethodologyConfig(BaseSchema):
    """M9 — sum-of-parts / NAV-style. Sprint 4D fleshes out;
    Sprint 4A-alpha.2 only accepts the config so tests load the
    schema."""

    type: Literal["ASSET_BASED"] = "ASSET_BASED"
    components: list[dict[str, Any]] = Field(default_factory=list)


# Sprint 4B — DDM / RESIDUAL_INCOME implemented. FFO / normalized /
# through-cycle still raise in the dispatcher.
class DDMMethodologyConfig(BaseSchema):
    type: Literal["DDM"] = "DDM"
    payout_ratio: Decimal | None = None
    terminal_growth: Decimal = Decimal("0.025")
    # Sprint 4B additions — horizon + scenario-level CoE override.
    # Backward-compat: scenarios.yaml entries that only set payout_ratio
    # / terminal_growth continue to load because these fields default.
    explicit_years: int = 5
    cost_of_equity_override: Decimal | None = None


class ResidualIncomeMethodologyConfig(BaseSchema):
    type: Literal["RESIDUAL_INCOME"] = "RESIDUAL_INCOME"
    terminal_growth: Decimal = Decimal("0.025")
    explicit_years: int = 5
    cost_of_equity_override: Decimal | None = None


class FFOBasedMethodologyConfig(BaseSchema):
    type: Literal["FFO_BASED"] = "FFO_BASED"
    terminal_growth: Decimal = Decimal("0.025")


class NormalizedDCFMethodologyConfig(BaseSchema):
    type: Literal["NORMALIZED_DCF"] = "NORMALIZED_DCF"
    historical_window_years: int = 7
    terminal_growth: Decimal = Decimal("0.025")


class ThroughCycleDCFMethodologyConfig(BaseSchema):
    type: Literal["THROUGH_CYCLE_DCF"] = "THROUGH_CYCLE_DCF"
    cycle_length_years: int = 5
    terminal_growth: Decimal = Decimal("0.025")


MethodologyConfig = Annotated[
    Union[
        DCFMethodologyConfig,
        MultipleExitMethodologyConfig,
        TransactionPrecedentMethodologyConfig,
        AssetBasedMethodologyConfig,
        DDMMethodologyConfig,
        ResidualIncomeMethodologyConfig,
        FFOBasedMethodologyConfig,
        NormalizedDCFMethodologyConfig,
        ThroughCycleDCFMethodologyConfig,
    ],
    Field(discriminator="type"),
]


def _default_methodology() -> DCFMethodologyConfig:
    """Default methodology when a scenario omits the field — preserves
    Sprint 4A-alpha backward compatibility."""
    return DCFMethodologyConfig(type="DCF_3_STAGE")


class Scenario(BaseSchema):
    name: str
    probability: Decimal
    rationale: str = ""
    # Sprint 4A-alpha.2 — per-scenario methodology config. Optional at
    # the schema level (defaults to DCF_3_STAGE) so scenarios.yaml
    # files from before the migration still load.
    methodology: MethodologyConfig = Field(default_factory=_default_methodology)
    driver_overrides: dict[str, ScenarioDriverOverride] = Field(
        default_factory=dict
    )
    valuation_overrides: dict[str, Any] = Field(default_factory=dict)


class TerminalMultipleScenario(BaseSchema):
    name: str
    probability: Decimal
    ev_ebitda: Decimal


class ScenarioSet(BaseSchema):
    target_ticker: str
    valuation_profile: DCFProfile
    base_year: str
    base_drivers: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[Scenario] = Field(default_factory=list)
    terminal_multiple_scenarios: list[TerminalMultipleScenario] | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _scenario_probabilities_sum_to_one(self) -> "ScenarioSet":
        if not self.scenarios:
            return self
        total = sum((s.probability for s in self.scenarios), start=Decimal("0"))
        if abs(total - Decimal("1")) > Decimal("0.01"):
            raise ValueError(
                f"Scenario probabilities sum to {total}, expected 1.00 ± 0.01"
            )
        return self

    @model_validator(mode="after")
    def _terminal_multiple_probabilities_sum_to_one(self) -> "ScenarioSet":
        if not self.terminal_multiple_scenarios:
            return self
        total = sum(
            (s.probability for s in self.terminal_multiple_scenarios),
            start=Decimal("0"),
        )
        if abs(total - Decimal("1")) > Decimal("0.01"):
            raise ValueError(
                f"Terminal-multiple probabilities sum to {total}, expected 1.00 ± 0.01"
            )
        return self


# ----------------------------------------------------------------------
# DCF outputs
# ----------------------------------------------------------------------
class DCFStageProjection(BaseSchema):
    """One year of the forecast (explicit or fade stage)."""

    year: int
    revenue: Decimal
    operating_margin: Decimal
    operating_income: Decimal
    tax_rate: Decimal
    nopat: Decimal
    capex: Decimal
    depreciation: Decimal
    wc_change: Decimal
    fcf: Decimal
    wacc_applied: Decimal
    discount_factor: Decimal
    pv: Decimal


class ForecastWarning(BaseSchema):
    severity: _WarningSeverity
    scenario: str
    year: int | None = None
    metric: str
    observation: str
    recommendation: str = ""


class TerminalMultipleValidation(BaseSchema):
    implied_ev_ebitda: Decimal | None = None
    industry_median_ev_ebitda: Decimal | None = None
    ratio_vs_median: Decimal | None = None
    warning_threshold: Decimal = Decimal("1.5")
    warning_emitted: bool = False


class DCFValuation(BaseSchema):
    """Per-scenario valuation output (name kept for backward compat;
    Sprint 4A-alpha.2 widens it to cover MULTIPLE_EXIT and
    TRANSACTION_PRECEDENT methodologies in addition to DCF variants)."""

    ticker: str
    scenario_name: str
    scenario_probability: Decimal

    # Sprint 4A-alpha.2 — which methodology produced this valuation.
    methodology_used: ValuationMethodology = ValuationMethodology.DCF_3_STAGE
    methodology_summary: dict[str, Any] = Field(default_factory=dict)

    explicit_projections: list[DCFStageProjection] = Field(default_factory=list)
    fade_projections: list[DCFStageProjection] = Field(default_factory=list)

    terminal_fcf: Decimal = Decimal("0")
    terminal_growth: Decimal = Decimal("0")
    terminal_wacc: Decimal = Decimal("0")
    terminal_value: Decimal = Decimal("0")
    terminal_pv: Decimal = Decimal("0")

    enterprise_value: Decimal
    net_debt: Decimal
    non_operating_assets: Decimal
    equity_value: Decimal
    shares_outstanding: Decimal
    fair_value_per_share: Decimal

    terminal_multiple_validation: TerminalMultipleValidation = Field(
        default_factory=TerminalMultipleValidation
    )

    # Sprint 4A-beta placeholders — populated when three-statement
    # projection + capital allocation events are wired.
    balance_sheet_projections: list[Any] | None = None
    capital_allocation_events: list[Any] | None = None


class DCFValuationResult(BaseSchema):
    """Aggregate across all scenarios for a ticker."""

    ticker: str
    valuation_profile: DCFProfile
    scenarios_run: list[DCFValuation] = Field(default_factory=list)
    warnings: list[ForecastWarning] = Field(default_factory=list)

    expected_value_per_share: Decimal | None = None
    market_price: Decimal | None = None
    implied_upside_downside_pct: Decimal | None = None
    p25_value_per_share: Decimal | None = None
    p75_value_per_share: Decimal | None = None

    stage_1_wacc: Decimal | None = None
    stage_3_wacc: Decimal | None = None


__all__ = [
    "AssetBasedMethodologyConfig",
    "DCFMethodologyConfig",
    "DCFProfile",
    "DCFStageProjection",
    "DCFStructure",
    "DCFValuation",
    "DCFValuationResult",
    "DDMMethodologyConfig",
    "FFOBasedMethodologyConfig",
    "ForecastWarning",
    "MethodologyConfig",
    "MultipleExitMethodologyConfig",
    "NormalizationConfig",
    "NormalizedDCFMethodologyConfig",
    "ProfileHeuristic",
    "ProfileSelection",
    "ResidualIncomeMethodologyConfig",
    "Scenario",
    "ScenarioDriverOverride",
    "ScenarioSet",
    "TargetCapitalStructure",
    "TerminalMethod",
    "TerminalMultipleScenario",
    "TerminalMultipleValidation",
    "TerminalValueConfig",
    "ThroughCycleDCFMethodologyConfig",
    "TransactionPrecedentMethodologyConfig",
    "ValuationMethodology",
    "ValuationProfile",
    "WACCEvolution",
]
