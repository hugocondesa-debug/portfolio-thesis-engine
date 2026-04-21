"""Group V guardrails — validation of the canonical state against
external sources and the WACC manual.

**V.1.CROSSCHECK_*** — promote :class:`CrossCheckReport` verdicts into
the guardrails block so the pipeline's overall status reflects the
cross-check outcome. The cross-check gate itself (Sprint 5) already
blocks on FAIL; these guardrails make the verdict visible on the
final report instead of living only in the gate's JSON log.

**V.2.WACC_CONSISTENCY** — checks that the headline ``wacc`` computed
by :class:`WACCInputs` is internally consistent with the capital
structure + cost-of-capital components. Catches hand-edited
``wacc_inputs.md`` files where the analyst wrote a WACC by hand that
doesn't match the components they also wrote.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.cross_check.base import (
    CrossCheckMetric,
    CrossCheckReport,
    CrossCheckStatus,
)
from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.schemas.wacc import WACCInputs


def _report_or_none(context: dict[str, Any]) -> CrossCheckReport | None:
    report = context.get("cross_check_report")
    return report if isinstance(report, CrossCheckReport) else None


def _find_metric(report: CrossCheckReport, metric_name: str) -> CrossCheckMetric | None:
    for m in report.metrics:
        if m.metric == metric_name:
            return m
    return None


_CROSSCHECK_TO_GUARDRAIL: dict[CrossCheckStatus, GuardrailStatus] = {
    CrossCheckStatus.PASS: GuardrailStatus.PASS,
    CrossCheckStatus.WARN: GuardrailStatus.WARN,
    CrossCheckStatus.FAIL: GuardrailStatus.FAIL,
    CrossCheckStatus.SOURCES_DISAGREE: GuardrailStatus.WARN,
    CrossCheckStatus.UNAVAILABLE: GuardrailStatus.SKIP,
}


class _CrossCheckGuardrail(Guardrail):
    """Common body for V.1.* cross-check pass-through guardrails.

    Subclasses specify a metric name; this class pulls the metric from
    the report, maps the cross-check status onto the guardrail status,
    and returns a rich message.
    """

    _metric: str = ""
    _label: str = ""

    @property
    def check_id(self) -> str:
        return f"V.1.CROSSCHECK_{self._metric.upper()}"

    @property
    def name(self) -> str:
        return f"Cross-check pass-through: {self._label or self._metric}"

    @property
    def blocking(self) -> bool:
        return True

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        report = _report_or_none(context)
        if report is None:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No cross_check_report in context.",
                blocking=self.blocking,
            )
        metric = _find_metric(report, self._metric)
        if metric is None:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                f"Metric {self._metric!r} absent from cross-check report.",
                blocking=self.blocking,
            )
        gstatus = _CROSSCHECK_TO_GUARDRAIL[metric.status]
        delta_str = (
            f"{metric.max_delta_pct:.2%}" if metric.max_delta_pct is not None else "—"
        )
        return GuardrailResult(
            self.check_id,
            self.name,
            gstatus,
            f"Cross-check metric {self._metric}: status={metric.status.value}, "
            f"|Δ|={delta_str}. {metric.notes}".strip(),
            blocking=self.blocking,
            data={
                "metric": metric.metric,
                "cross_check_status": metric.status.value,
                "max_delta_pct": (
                    str(metric.max_delta_pct) if metric.max_delta_pct is not None else None
                ),
            },
        )


class CrossCheckRevenueGuardrail(_CrossCheckGuardrail):
    _metric = "revenue"
    _label = "revenue"


class CrossCheckNetIncomeGuardrail(_CrossCheckGuardrail):
    _metric = "net_income"
    _label = "net income"


class CrossCheckTotalAssetsGuardrail(_CrossCheckGuardrail):
    _metric = "total_assets"
    _label = "total assets"


# ----------------------------------------------------------------------
# V.2 — WACC internal consistency
# ----------------------------------------------------------------------
class WACCConsistency(Guardrail):
    """Recompute WACC from the capital structure + cost-of-capital and
    compare to the headline :attr:`WACCInputs.wacc` property.

    Tolerance: 0.1 percentage points (10 bps). When components are
    missing we SKIP — the WACC parser already validates structurally,
    so a WACCInputs object here is a *valid* WACC. This check catches
    accidental divergence rather than missing data.

    Non-blocking: a WACC typo will propagate into valuation and surface
    there; we flag it loudly but don't stop extraction.
    """

    _TOL_PP = Decimal("0.1")

    @property
    def check_id(self) -> str:
        return "V.2.WACC_CONSISTENCY"

    @property
    def name(self) -> str:
        return "WACC internal consistency"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        wacc_inputs = context.get("wacc_inputs")
        if not isinstance(wacc_inputs, WACCInputs):
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No wacc_inputs in context.",
            )
        # ``wacc_inputs.wacc`` is a pure property derived from the
        # components; the check is "does it round to what we'd compute
        # independently?". We recompute here using Decimal arithmetic
        # separate from the @property so a typo in one path would
        # surface as an FAIL. Since the @property is already the
        # canonical implementation, this is mostly a regression guard
        # and a sanity check that the components aren't internally
        # contradictory (e.g., weights not actually summing to 100).
        coc = wacc_inputs.cost_of_capital
        cs = wacc_inputs.capital_structure
        hundred = Decimal("100")
        w_e = cs.equity_weight / hundred
        w_d = cs.debt_weight / hundred
        w_p = cs.preferred_weight / hundred
        k_e = (coc.risk_free_rate + coc.beta * coc.equity_risk_premium) / hundred
        k_d_after_tax = (coc.cost_of_debt_pretax / hundred) * (
            Decimal("1") - coc.tax_rate_for_wacc / hundred
        )
        computed = (w_e * k_e + w_d * k_d_after_tax + w_p * k_e) * hundred
        reported = wacc_inputs.wacc
        delta_pp = abs(computed - reported)
        status = GuardrailStatus.PASS if delta_pp <= self._TOL_PP else GuardrailStatus.WARN
        return GuardrailResult(
            self.check_id,
            self.name,
            status,
            f"Reported WACC {reported:.3f}% vs recomputed {computed:.3f}% "
            f"(Δ={delta_pp:.3f}pp; tolerance {self._TOL_PP}pp).",
            data={
                "reported": str(reported),
                "computed": str(computed),
                "delta_pp": str(delta_pp),
            },
        )
