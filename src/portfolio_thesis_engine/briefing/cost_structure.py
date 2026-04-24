"""Phase 2 Sprint 4A-alpha.5 Part A — cost structure analyzer.

Parses the per-period income statement line items stored on the
:class:`CanonicalCompanyState` via the Phase-2 historicals layer and
produces:

- Cost-line evolution: each identified line's share of revenue, YoY
  deltas in bps, and a qualitative trend tag.
- Margin bridges: attribution of operating-margin change between
  consecutive periods to specific cost lines.
- Operating-leverage estimate: fixed vs variable cost proxy via
  pure-Python OLS on (revenue, operating_expenses) pairs.

Graceful degradation: when only aggregate COGS / SG&A are present we
emit just those two; the margin bridge still works because it keys
off whatever cost lines the analyzer actually found.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.historicals import HistoricalRecord


_Trend = Literal["EXPANDING_AS_PERCENT", "CONTRACTING_AS_PERCENT", "STABLE"]
_InflationSensitivity = Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
class CostLineEvolution(BaseSchema):
    """Evolution of a single cost line across the analysis window."""

    line_name: str
    weights_by_period: dict[str, Decimal] = Field(default_factory=dict)
    yoy_delta_bps: dict[str, int] = Field(default_factory=dict)
    trend: _Trend = "STABLE"
    inflation_sensitivity: _InflationSensitivity = "UNKNOWN"
    current_weight: Decimal | None = None
    historical_mean: Decimal | None = None
    historical_range: tuple[Decimal, Decimal] | None = None


class MarginBridge(BaseSchema):
    """Attribution of operating-margin change between two periods."""

    from_period: str
    to_period: str
    starting_margin: Decimal
    ending_margin: Decimal
    delta_bps: int
    attribution_bps: dict[str, int] = Field(default_factory=dict)
    residual_bps: int = 0


class CostStructureAnalysis(BaseSchema):
    """Top-level output of :class:`CostStructureAnalyzer`."""

    target_ticker: str
    periods_analyzed: list[str] = Field(default_factory=list)
    cost_lines: list[CostLineEvolution] = Field(default_factory=list)
    margin_bridges: list[MarginBridge] = Field(default_factory=list)
    operating_leverage_estimate: Decimal | None = None
    total_fixed_cost_proxy: Decimal | None = None
    total_variable_cost_proxy: Decimal | None = None
    analysis_notes: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Line classification
# ----------------------------------------------------------------------
# Standardised line keys. Analyst-facing labels map to these via
# case-insensitive substring lookup.
_LINE_KEYS = (
    "cogs",
    "personnel",
    "selling",
    "admin",
    "impairment",
    "other_gains",
    "d_and_a",
    "research",
    "rent_utilities",
    "marketing",
    "other",
)


def _classify_line_label(label: str) -> str | None:
    """Map a raw IS line label to one of our standard keys. ``None``
    when it's not a cost line we want to track (e.g. revenue,
    subtotals, finance items, tax, net income)."""
    lower = label.lower()
    # Cost-line keywords checked BEFORE the skip list so "Cost of
    # sales" isn't filtered by the bare "sales" skip token.
    if "cost of sales" in lower or "cost of goods" in lower or "cogs" in lower:
        return "cogs"
    # Skip non-cost lines.
    if any(skip in lower for skip in (
        "revenue", "turnover", "sales",
        "gross profit", "operating profit", "profit before",
        "profit for", "net income", "income tax",
        "finance income", "finance expense",
        "finance income/(expenses)", "other comprehensive",
        "comprehensive income", "exchange differences",
    )):
        return None
    if "selling" in lower:
        return "selling"
    if "administrative" in lower or "admin" in lower:
        return "admin"
    if "impairment" in lower:
        return "impairment"
    if "other gains" in lower or "other income" in lower:
        return "other_gains"
    if "depreciation" in lower or "amortisation" in lower or "amortization" in lower:
        return "d_and_a"
    if "research" in lower or "r&d" in lower:
        return "research"
    if "personnel" in lower or "employee" in lower or "staff" in lower:
        return "personnel"
    if "rent" in lower or "utilities" in lower:
        return "rent_utilities"
    if "marketing" in lower or "advertising" in lower:
        return "marketing"
    return None


# Sector-default sensitivity heuristics. Callers can override by
# passing a ``sensitivity_overrides`` dict.
_DEFAULT_SENSITIVITY: dict[str, _InflationSensitivity] = {
    "personnel": "HIGH",
    "selling": "LOW",
    "admin": "MODERATE",
    "cogs": "MODERATE",
    "d_and_a": "LOW",
    "research": "LOW",
    "rent_utilities": "HIGH",
    "marketing": "LOW",
    "other_gains": "UNKNOWN",
    "impairment": "UNKNOWN",
    "other": "UNKNOWN",
}


# ----------------------------------------------------------------------
# Analyzer
# ----------------------------------------------------------------------
class CostStructureAnalyzer:
    """Compute :class:`CostStructureAnalysis` from a sequence of
    :class:`HistoricalRecord` (the Sprint-2 time-series view). The
    analyzer reads the *reclassified* income statement stored inside
    the record's source canonical state — so it sees the same line
    items Module A/B/C/D have already normalised."""

    def __init__(
        self,
        *,
        sensitivity_overrides: dict[str, _InflationSensitivity] | None = None,
    ) -> None:
        self._sensitivity_overrides = sensitivity_overrides or {}

    # ------------------------------------------------------------------
    def analyze(
        self,
        *,
        ticker: str,
        records: list[HistoricalRecord],
        states: dict[str, Any] | None = None,
    ) -> CostStructureAnalysis:
        """Run the analysis. ``states`` is a dict keyed by
        ``HistoricalRecord.source_canonical_state_id`` returning the
        canonical state (so the analyzer can walk the IS line list).
        When ``states`` is ``None`` the analyzer falls back to
        record-level aggregates (revenue, operating_income) only —
        which limits output to aggregate margin bridges without
        per-line decomposition.
        """
        notes: list[str] = []
        annual = [
            r for r in records
            if getattr(r.period_type, "value", "") == "annual"
        ]
        annual.sort(key=lambda r: r.period_end)
        if len(annual) < 2:
            notes.append(
                "Fewer than 2 annual records available; cost-structure "
                "analysis will be limited."
            )
        periods = [r.period for r in annual]

        # ── Per-period per-line weights ──────────────────────────────
        # Only populate when ``_extract_line_weights`` actually found
        # something — keeps ``per_period_weights`` empty when no line
        # data is available so the graceful-degradation note fires.
        per_period_weights: dict[str, dict[str, Decimal]] = {}
        for record in annual:
            if record.revenue in (None, Decimal("0")):
                continue
            assert record.revenue is not None
            state = states.get(record.source_canonical_state_id) if states else None
            weights = self._extract_line_weights(state, record)
            if weights:
                per_period_weights[record.period] = weights

        if not per_period_weights:
            notes.append(
                "No line-level cost data found in canonical state; "
                "margin bridges only."
            )

        cost_lines = self._build_cost_line_evolutions(
            per_period_weights, periods
        )
        margin_bridges = self._build_margin_bridges(
            annual, per_period_weights
        )
        op_lev, fixed, variable = self._estimate_operating_leverage(annual)

        return CostStructureAnalysis(
            target_ticker=ticker,
            periods_analyzed=periods,
            cost_lines=cost_lines,
            margin_bridges=margin_bridges,
            operating_leverage_estimate=op_lev,
            total_fixed_cost_proxy=fixed,
            total_variable_cost_proxy=variable,
            analysis_notes=notes,
        )

    # ------------------------------------------------------------------
    def _extract_line_weights(
        self, state: Any | None, record: HistoricalRecord
    ) -> dict[str, Decimal]:
        """Return ``{line_key: weight_vs_revenue}`` for the record's
        period. Values are positive (expense weights) regardless of
        the sign convention used in the IS."""
        out: dict[str, Decimal] = {}
        revenue = record.revenue
        if revenue is None or revenue == 0:
            return out
        if state is None or not getattr(state, "reclassified_statements", None):
            return out
        period_label = record.period
        rs = next(
            (
                rs for rs in state.reclassified_statements
                if rs.period.label == period_label
            ),
            state.reclassified_statements[0],
        )
        for line in rs.income_statement:
            key = _classify_line_label(line.label)
            if key is None:
                continue
            value = abs(Decimal(str(line.value)))
            out.setdefault(key, Decimal("0"))
            out[key] += value / revenue
        return out

    # ------------------------------------------------------------------
    def _build_cost_line_evolutions(
        self,
        per_period_weights: dict[str, dict[str, Decimal]],
        periods: list[str],
    ) -> list[CostLineEvolution]:
        if not per_period_weights:
            return []
        # Union of keys observed across periods.
        all_keys = sorted(
            {k for weights in per_period_weights.values() for k in weights}
        )
        result: list[CostLineEvolution] = []
        for key in all_keys:
            weights_by_period: dict[str, Decimal] = {}
            for period in periods:
                if period in per_period_weights and key in per_period_weights[period]:
                    weights_by_period[period] = per_period_weights[period][key]
            if not weights_by_period:
                continue
            # YoY deltas in bps (period vs prior period).
            yoy_delta_bps: dict[str, int] = {}
            sorted_periods = [p for p in periods if p in weights_by_period]
            for i in range(1, len(sorted_periods)):
                prev, curr = sorted_periods[i - 1], sorted_periods[i]
                delta = (weights_by_period[curr] - weights_by_period[prev]) * Decimal("10000")
                yoy_delta_bps[curr] = int(delta.to_integral_value())
            values = list(weights_by_period.values())
            mean = sum(values, start=Decimal("0")) / Decimal(len(values))
            lo, hi = min(values), max(values)
            current = weights_by_period[sorted_periods[-1]]
            # Trend: compare last delta to threshold.
            trend: _Trend = "STABLE"
            if yoy_delta_bps:
                last_delta = yoy_delta_bps[sorted_periods[-1]]
                if last_delta > 50:
                    trend = "EXPANDING_AS_PERCENT"
                elif last_delta < -50:
                    trend = "CONTRACTING_AS_PERCENT"
            sensitivity = self._sensitivity_overrides.get(
                key, _DEFAULT_SENSITIVITY.get(key, "UNKNOWN")
            )
            result.append(
                CostLineEvolution(
                    line_name=key,
                    weights_by_period=weights_by_period,
                    yoy_delta_bps=yoy_delta_bps,
                    trend=trend,
                    inflation_sensitivity=sensitivity,
                    current_weight=current,
                    historical_mean=mean,
                    historical_range=(lo, hi),
                )
            )
        return result

    # ------------------------------------------------------------------
    def _build_margin_bridges(
        self,
        annual: list[HistoricalRecord],
        per_period_weights: dict[str, dict[str, Decimal]],
    ) -> list[MarginBridge]:
        bridges: list[MarginBridge] = []
        for i in range(1, len(annual)):
            prev = annual[i - 1]
            curr = annual[i]
            if (
                prev.revenue in (None, Decimal("0"))
                or curr.revenue in (None, Decimal("0"))
                or prev.operating_income is None
                or curr.operating_income is None
            ):
                continue
            assert prev.revenue is not None and curr.revenue is not None
            assert prev.operating_income is not None and curr.operating_income is not None
            start = prev.operating_income / prev.revenue
            end = curr.operating_income / curr.revenue
            delta_bps = int(((end - start) * Decimal("10000")).to_integral_value())
            attribution: dict[str, int] = {}
            prev_weights = per_period_weights.get(prev.period, {})
            curr_weights = per_period_weights.get(curr.period, {})
            keys = set(prev_weights) | set(curr_weights)
            for key in keys:
                p_w = prev_weights.get(key, Decimal("0"))
                c_w = curr_weights.get(key, Decimal("0"))
                # Higher cost weight → lower margin, so contribution
                # is the negative of the weight change.
                weight_change_bps = (c_w - p_w) * Decimal("10000")
                attribution[key] = int((-weight_change_bps).to_integral_value())
            residual = delta_bps - sum(attribution.values())
            bridges.append(
                MarginBridge(
                    from_period=prev.period,
                    to_period=curr.period,
                    starting_margin=start,
                    ending_margin=end,
                    delta_bps=delta_bps,
                    attribution_bps=attribution,
                    residual_bps=residual,
                )
            )
        return bridges

    # ------------------------------------------------------------------
    def _estimate_operating_leverage(
        self, annual: list[HistoricalRecord]
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """Pure-Python OLS on (revenue, operating_expenses). Returns
        ``(variable_cost_slope, fixed_cost_proxy, variable_cost_proxy)``."""
        points: list[tuple[Decimal, Decimal]] = []
        for r in annual:
            if (
                r.revenue in (None, Decimal("0"))
                or r.operating_income is None
            ):
                continue
            assert r.revenue is not None and r.operating_income is not None
            opex = r.revenue - r.operating_income
            points.append((r.revenue, opex))
        if len(points) < 3:
            return None, None, None
        n = Decimal(len(points))
        sum_x = sum((x for x, _ in points), start=Decimal("0"))
        sum_y = sum((y for _, y in points), start=Decimal("0"))
        mean_x = sum_x / n
        mean_y = sum_y / n
        num = sum(((x - mean_x) * (y - mean_y) for x, y in points), start=Decimal("0"))
        den = sum((((x - mean_x) ** 2) for x, _ in points), start=Decimal("0"))
        if den == 0:
            return None, None, None
        slope = num / den
        intercept = mean_y - slope * mean_x
        # variable_cost_proxy is the slope × latest revenue (what
        # would vary if revenue moved). fixed_cost_proxy is intercept.
        latest_rev = points[-1][0]
        variable_proxy = slope * latest_rev
        return slope, intercept, variable_proxy


__all__ = [
    "CostLineEvolution",
    "CostStructureAnalysis",
    "CostStructureAnalyzer",
    "MarginBridge",
]
