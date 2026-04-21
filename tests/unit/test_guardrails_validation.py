"""Unit tests for guardrails.checks.validation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_thesis_engine.cross_check.base import (
    CrossCheckMetric,
    CrossCheckReport,
    CrossCheckStatus,
)
from portfolio_thesis_engine.guardrails.checks.validation import (
    CrossCheckNetIncomeGuardrail,
    CrossCheckRevenueGuardrail,
    CrossCheckTotalAssetsGuardrail,
    WACCConsistency,
)
from portfolio_thesis_engine.schemas.common import GuardrailStatus, Profile
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)


def _metric(name: str, status: CrossCheckStatus, delta: Decimal | None) -> CrossCheckMetric:
    return CrossCheckMetric(
        metric=name,
        extracted_value=Decimal("100"),
        fmp_value=Decimal("101"),
        yfinance_value=Decimal("99"),
        max_delta_pct=delta,
        status=status,
    )


def _report(metrics: list[CrossCheckMetric]) -> CrossCheckReport:
    return CrossCheckReport(
        ticker="TST",
        period="FY2024",
        metrics=metrics,
        overall_status=CrossCheckStatus.PASS,
        blocking=False,
        generated_at=datetime.now(UTC),
    )


# ======================================================================
# V.1 pass-throughs
# ======================================================================


class TestCrossCheckPassThrough:
    @pytest.mark.parametrize(
        "cc_status, expected",
        [
            (CrossCheckStatus.PASS, GuardrailStatus.PASS),
            (CrossCheckStatus.WARN, GuardrailStatus.WARN),
            (CrossCheckStatus.FAIL, GuardrailStatus.FAIL),
            (CrossCheckStatus.SOURCES_DISAGREE, GuardrailStatus.WARN),
            (CrossCheckStatus.UNAVAILABLE, GuardrailStatus.SKIP),
        ],
    )
    def test_revenue_maps_each_status(
        self, cc_status: CrossCheckStatus, expected: GuardrailStatus
    ) -> None:
        report = _report([_metric("revenue", cc_status, Decimal("0.01"))])
        result = CrossCheckRevenueGuardrail().check({"cross_check_report": report})
        assert result.status == expected

    def test_net_income(self) -> None:
        report = _report([_metric("net_income", CrossCheckStatus.PASS, Decimal("0.00"))])
        result = CrossCheckNetIncomeGuardrail().check({"cross_check_report": report})
        assert result.status == GuardrailStatus.PASS
        assert "net_income" in result.data["metric"]

    def test_total_assets(self) -> None:
        report = _report(
            [_metric("total_assets", CrossCheckStatus.FAIL, Decimal("0.50"))]
        )
        result = CrossCheckTotalAssetsGuardrail().check({"cross_check_report": report})
        assert result.status == GuardrailStatus.FAIL

    def test_no_report_skips(self) -> None:
        result = CrossCheckRevenueGuardrail().check({})
        assert result.status == GuardrailStatus.SKIP

    def test_metric_absent_skips(self) -> None:
        report = _report([])  # no metrics at all
        result = CrossCheckRevenueGuardrail().check({"cross_check_report": report})
        assert result.status == GuardrailStatus.SKIP
        assert "absent" in result.message

    def test_check_id_formatting(self) -> None:
        assert CrossCheckRevenueGuardrail().check_id == "V.1.CROSSCHECK_REVENUE"
        assert CrossCheckNetIncomeGuardrail().check_id == "V.1.CROSSCHECK_NET_INCOME"
        assert CrossCheckTotalAssetsGuardrail().check_id == "V.1.CROSSCHECK_TOTAL_ASSETS"


# ======================================================================
# V.2 WACC consistency
# ======================================================================


def _wacc() -> WACCInputs:
    return WACCInputs(
        ticker="TST",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("100"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("3.0"),
            equity_risk_premium=Decimal("5.0"),
            beta=Decimal("1.0"),
            cost_of_debt_pretax=Decimal("5.0"),
            tax_rate_for_wacc=Decimal("25.0"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("30"),
            equity_weight=Decimal("70"),
        ),
        scenarios={
            "base": ScenarioDriversManual(
                probability=Decimal("100"),
                revenue_cagr_explicit_period=Decimal("5"),
                terminal_growth=Decimal("2"),
                terminal_operating_margin=Decimal("18"),
            )
        },
    )


class TestWACCConsistency:
    def test_consistent_passes(self) -> None:
        result = WACCConsistency().check({"wacc_inputs": _wacc()})
        # @property mirrors our recompute → PASS.
        assert result.status == GuardrailStatus.PASS

    def test_no_inputs_skips(self) -> None:
        result = WACCConsistency().check({})
        assert result.status == GuardrailStatus.SKIP

    def test_data_includes_reported_and_computed(self) -> None:
        result = WACCConsistency().check({"wacc_inputs": _wacc()})
        assert "reported" in result.data
        assert "computed" in result.data
