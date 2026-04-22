"""Group A guardrails — arithmetic integrity checks on the canonical state.

These run **after** the extraction engine has produced a
:class:`CanonicalCompanyState` and before it's persisted downstream.
They read the reclassified statements (post-Modules A/B/C) and verify
the accounting identities. Two status tiers per check:

- **PASS** when |delta| ≤ ``pass_tolerance`` of the reference value
- **WARN** when ``pass_tolerance`` < |delta| ≤ ``fail_tolerance``
- **FAIL** when |delta| > ``fail_tolerance`` (blocking)

Missing inputs (e.g., no income statement in the state) produce a
**SKIP** result with a clear rationale — they're never silently treated
as PASS. All A.* checks are blocking: a FAIL stops the pipeline by
default.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.schemas.company import (
    BalanceSheetLine,
    CanonicalCompanyState,
    IncomeStatementLine,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _state_or_none(context: dict[str, Any]) -> CanonicalCompanyState | None:
    state = context.get("canonical_state")
    return state if isinstance(state, CanonicalCompanyState) else None


def _pct_delta(computed: Decimal, reported: Decimal) -> Decimal:
    """|(computed − reported) / reported|. Treat reported==0 as
    "use absolute delta" (divide by 1) so a 0-reference doesn't
    blow up on division."""
    divisor = abs(reported) if reported != 0 else Decimal("1")
    return abs(computed - reported) / divisor


def _tier(
    delta_pct: Decimal, *, pass_tol: Decimal, fail_tol: Decimal
) -> GuardrailStatus:
    if delta_pct <= pass_tol:
        return GuardrailStatus.PASS
    if delta_pct <= fail_tol:
        return GuardrailStatus.WARN
    return GuardrailStatus.FAIL


def _sum_lines(lines: list[IncomeStatementLine] | list[BalanceSheetLine]) -> Decimal:
    return sum((ln.value for ln in lines), start=Decimal("0"))


# ----------------------------------------------------------------------
# A.1.IS_CHECKSUM
# ----------------------------------------------------------------------
class ISChecksum(Guardrail):
    """Income statement arithmetic: the reclassified IS lines sum to
    the net income line (within tolerance).

    Reference: reported Net Income. Tolerances: PASS ≤ 0.1 %, FAIL > 0.5 %.
    The check works on **reclassified** IS: the sum of every atomic
    line item (revenue, COGS, OpEx, D&A, finance, tax) equals the net
    income line. Subtotals (Gross Profit, Operating Income, PBT) are
    excluded from the sum — they'd double-count — via label matching.
    """

    _PASS_TOL = Decimal("0.001")
    _FAIL_TOL = Decimal("0.005")

    _SUBTOTAL_LABEL_KEYWORDS = (
        "operating income",
        "operating profit",
        "profit from operations",
        "gross profit",
        "profit before tax",
        "profit before taxation",
        "pretax income",
        "pre-tax income",
        "income before tax",
        "ebit",
        "ebitda",
    )

    _NI_LABEL_PATTERNS = (
        "net income",
        "profit for the year",
        "profit for the period",
        "net profit",
        "profit attributable to",
    )

    @classmethod
    def _is_subtotal(cls, label: str) -> bool:
        lowered = label.strip().lower()
        return any(kw in lowered for kw in cls._SUBTOTAL_LABEL_KEYWORDS)

    @property
    def check_id(self) -> str:
        return "A.1.IS_CHECKSUM"

    @property
    def name(self) -> str:
        return "Income statement arithmetic"

    @property
    def blocking(self) -> bool:
        return True

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        state = _state_or_none(context)
        if state is None or not state.reclassified_statements:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No canonical_state with reclassified statements available.",
                blocking=self.blocking,
            )
        is_lines = state.reclassified_statements[0].income_statement
        if not is_lines:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "Income statement has no line items.",
                blocking=self.blocking,
            )

        ni_lines = [
            ln for ln in is_lines
            if any(pat in ln.label.lower() for pat in self._NI_LABEL_PATTERNS)
        ]
        if not ni_lines:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No net-income line found in reclassified IS.",
                blocking=self.blocking,
            )
        ni_reported = ni_lines[-1].value
        ni_label_lower = ni_lines[-1].label.lower()
        ni_computed = _sum_lines(
            [
                ln
                for ln in is_lines
                if ln.label.lower() != ni_label_lower
                and not self._is_subtotal(ln.label)
            ]
        )
        delta_pct = _pct_delta(ni_computed, ni_reported)
        status = _tier(delta_pct, pass_tol=self._PASS_TOL, fail_tol=self._FAIL_TOL)

        return GuardrailResult(
            self.check_id,
            self.name,
            status,
            f"Σ components {ni_computed} vs reported NI {ni_reported} "
            f"(|Δ|={delta_pct:.2%}; PASS≤{self._PASS_TOL:.1%}, "
            f"FAIL>{self._FAIL_TOL:.1%}).",
            blocking=self.blocking,
            data={
                "computed": str(ni_computed),
                "reported": str(ni_reported),
                "delta_pct": str(delta_pct),
            },
        )


# ----------------------------------------------------------------------
# A.1.BS_CHECKSUM
# ----------------------------------------------------------------------
class BSChecksum(Guardrail):
    """Balance sheet identity: Assets == Liabilities + Equity.

    Tolerances: PASS ≤ 0.01 %, FAIL > 0.1 %. The identity must hold
    tightly — any deviation is a reclassification bug.
    """

    _PASS_TOL = Decimal("0.0001")
    _FAIL_TOL = Decimal("0.001")

    # BS categories. Phase 1.5.3 uses BS ``section`` names as
    # categories; legacy phase-1 categories retained for compatibility
    # with any canonical states produced pre-1.5.3.
    _ASSET_CATEGORIES = frozenset(
        {
            # Phase 1.5.3 sections
            "current_assets", "non_current_assets",
            # Legacy categories
            "cash", "operating_assets", "financial_assets", "intangibles",
        }
    )
    _LIAB_CATEGORIES = frozenset(
        {
            # Phase 1.5.3 sections
            "current_liabilities", "non_current_liabilities",
            # Legacy categories
            "operating_liabilities", "financial_liabilities",
            "lease_liabilities",
        }
    )
    _EQUITY_CATEGORIES = frozenset({"equity", "nci"})

    @property
    def check_id(self) -> str:
        return "A.1.BS_CHECKSUM"

    @property
    def name(self) -> str:
        return "Balance sheet identity"

    @property
    def blocking(self) -> bool:
        return True

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        state = _state_or_none(context)
        if state is None or not state.reclassified_statements:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No canonical_state with reclassified statements available.",
                blocking=self.blocking,
            )
        bs_lines = state.reclassified_statements[0].balance_sheet
        if not bs_lines:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "Balance sheet has no line items.",
                blocking=self.blocking,
            )

        assets = sum(
            (ln.value for ln in bs_lines if ln.category in self._ASSET_CATEGORIES),
            start=Decimal("0"),
        )
        liabilities = sum(
            (ln.value for ln in bs_lines if ln.category in self._LIAB_CATEGORIES),
            start=Decimal("0"),
        )
        equity = sum(
            (ln.value for ln in bs_lines if ln.category in self._EQUITY_CATEGORIES),
            start=Decimal("0"),
        )
        rhs = liabilities + equity
        if assets == 0 and rhs == 0:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "Balance sheet buckets all zero — no categorised lines to check.",
                blocking=self.blocking,
            )
        delta_pct = _pct_delta(rhs, assets)
        status = _tier(delta_pct, pass_tol=self._PASS_TOL, fail_tol=self._FAIL_TOL)

        return GuardrailResult(
            self.check_id,
            self.name,
            status,
            f"Assets {assets} vs Liab+Equity {rhs} "
            f"(|Δ|={delta_pct:.4%}; PASS≤{self._PASS_TOL:.2%}, "
            f"FAIL>{self._FAIL_TOL:.2%}).",
            blocking=self.blocking,
            data={
                "assets": str(assets),
                "liabilities": str(liabilities),
                "equity": str(equity),
                "delta_pct": str(delta_pct),
            },
        )


# ----------------------------------------------------------------------
# A.1.CF_CHECKSUM
# ----------------------------------------------------------------------
class CFChecksum(Guardrail):
    """Cash flow identity: CFO + CFI + CFF + FX ≈ Δcash.

    Phase 1 tolerances: PASS ≤ 0.5 %, FAIL > 2 %. We derive Δcash from
    the CF line whose category is ``net_change_in_cash`` when available;
    otherwise, we use the sum of the CFO/CFI/CFF/FX buckets as the
    reference and check the identity against ``net_change_in_cash=None``
    with a SKIP.
    """

    _PASS_TOL = Decimal("0.005")
    _FAIL_TOL = Decimal("0.02")

    @property
    def check_id(self) -> str:
        return "A.1.CF_CHECKSUM"

    @property
    def name(self) -> str:
        return "Cash flow identity"

    @property
    def blocking(self) -> bool:
        return True

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        state = _state_or_none(context)
        if state is None or not state.reclassified_statements:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No canonical_state with reclassified statements available.",
                blocking=self.blocking,
            )
        cf_lines = state.reclassified_statements[0].cash_flow
        if not cf_lines:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "Cash flow has no line items.",
                blocking=self.blocking,
            )

        # Phase 1.5.3 uses section names as categories; legacy
        # categories (cfo / cfi / cff / net_change_in_cash) retained
        # for old canonical states. Sum all non-subtotal lines per
        # section; then compare section subtotals to Δcash.
        cfo = sum(
            (ln.value for ln in cf_lines
             if ln.category in ("cfo", "operating")),
            start=Decimal("0"),
        )
        cfi = sum(
            (ln.value for ln in cf_lines
             if ln.category in ("cfi", "investing")),
            start=Decimal("0"),
        )
        cff = sum(
            (ln.value for ln in cf_lines
             if ln.category in ("cff", "financing")),
            start=Decimal("0"),
        )
        fx = sum(
            (ln.value for ln in cf_lines if ln.category == "fx_effect"),
            start=Decimal("0"),
        )
        computed = cfo + cfi + cff + fx
        # Net-change line: either the legacy "net_change_in_cash"
        # category OR a line in the "subtotal" section with a
        # net-change-like label.
        nc_lines = [
            ln for ln in cf_lines
            if ln.category == "net_change_in_cash"
            or (
                ln.category == "subtotal"
                and (
                    "net change in cash" in ln.label.lower()
                    or "net increase in cash" in ln.label.lower()
                    or "net decrease in cash" in ln.label.lower()
                )
            )
        ]
        if not nc_lines:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                (
                    "No net_change_in_cash line — identity can't be verified. "
                    f"Computed CFO+CFI+CFF+FX = {computed}."
                ),
                blocking=self.blocking,
            )
        reported = nc_lines[-1].value
        delta_pct = _pct_delta(computed, reported)
        status = _tier(delta_pct, pass_tol=self._PASS_TOL, fail_tol=self._FAIL_TOL)

        return GuardrailResult(
            self.check_id,
            self.name,
            status,
            f"CFO+CFI+CFF+FX {computed} vs Δcash {reported} "
            f"(|Δ|={delta_pct:.2%}; PASS≤{self._PASS_TOL:.1%}, "
            f"FAIL>{self._FAIL_TOL:.1%}).",
            blocking=self.blocking,
            data={
                "computed": str(computed),
                "reported": str(reported),
                "delta_pct": str(delta_pct),
            },
        )


# ----------------------------------------------------------------------
# A.2.IC_CONSISTENCY
# ----------------------------------------------------------------------
class ICConsistency(Guardrail):
    """Invested Capital consistency: the InvestedCapital computed by
    :class:`AnalysisDeriver` matches the IC implied by NOPAT / ROIC
    (when ROIC is published on the ratios block), within 2 %.

    When ROIC isn't published or NOPAT is zero, the check SKIPs — it
    needs both to form the comparison. Non-blocking: an inconsistency
    here indicates a ratio-computation issue, not bad reclassification,
    so we warn loudly but don't stop the pipeline.
    """

    _PASS_TOL = Decimal("0.005")
    _FAIL_TOL = Decimal("0.02")

    @property
    def check_id(self) -> str:
        return "A.2.IC_CONSISTENCY"

    @property
    def name(self) -> str:
        return "Invested Capital vs NOPAT/ROIC consistency"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        state = _state_or_none(context)
        if state is None:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "No canonical_state in context.",
            )
        analysis = state.analysis
        if not analysis.invested_capital_by_period or not analysis.nopat_bridge_by_period:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "Missing invested_capital or nopat_bridge in analysis.",
            )
        ratios_list = analysis.ratios_by_period
        roic = ratios_list[0].roic if ratios_list else None
        if roic is None or roic == 0:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "ROIC not published — can't cross-check IC.",
            )
        ic = analysis.invested_capital_by_period[0].invested_capital
        nopat = analysis.nopat_bridge_by_period[0].nopat
        if nopat == 0:
            return GuardrailResult(
                self.check_id,
                self.name,
                GuardrailStatus.SKIP,
                "NOPAT is zero — implied IC undefined.",
            )
        implied_ic = nopat / (roic / Decimal("100"))
        delta_pct = _pct_delta(ic, implied_ic)
        status = _tier(delta_pct, pass_tol=self._PASS_TOL, fail_tol=self._FAIL_TOL)

        return GuardrailResult(
            self.check_id,
            self.name,
            status,
            f"IC {ic} vs NOPAT/ROIC implied {implied_ic} "
            f"(|Δ|={delta_pct:.2%}; PASS≤{self._PASS_TOL:.1%}, "
            f"FAIL>{self._FAIL_TOL:.1%}).",
            data={
                "ic_extracted": str(ic),
                "ic_implied": str(implied_ic),
                "delta_pct": str(delta_pct),
            },
        )
