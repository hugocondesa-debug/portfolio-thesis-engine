"""Three-tier validator for :class:`RawExtraction` artefacts.

The pipeline trusts the extraction numerically, but Hugo needs tools
to catch typos before paying for a full process run. This module
gives him three independent check tiers:

- :meth:`ExtractionValidator.validate_strict` — accounting identities
  that MUST hold for any well-formed extraction. A FAIL at this tier
  blocks the pipeline. Tolerances are tight (IS ±0.5 %, BS ±0.1 %).
- :meth:`ExtractionValidator.validate_warn` — softer consistency
  checks that often hold but aren't guarantees (CF identity, capex
  vs ΔPPE + D&A, dividends vs ΔRE − NI, YoY sanity). A WARN doesn't
  stop anything; it surfaces on the pipeline log and in
  ``pte validate-extraction`` output.
- :meth:`ExtractionValidator.validate_completeness` — per-profile
  note coverage check. Phase 1 ships P1 only; other profiles pile
  on in Phase 2.

Each method returns a :class:`ValidationReport` with per-check
results. The CLI renders the report as a Rich table; the pipeline
stage pulls the strict report's :attr:`overall_status` to decide
whether to block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    IncomeStatementPeriod,
    NotesContainer,
    RawExtraction,
)

ValidationStatus = Literal["OK", "WARN", "FAIL", "SKIP"]

_IS_TOL = Decimal("0.005")  # 0.5 %
_BS_TOL = Decimal("0.001")  # 0.1 %
_CF_TOL = Decimal("0.02")  # 2 %
_CAPEX_VS_DELTA_PPE_TOL = Decimal("0.05")  # 5 %
_DIVIDENDS_VS_RE_TOL = Decimal("0.02")  # 2 %
_YOY_GROWTH_FLAG_THRESHOLD = Decimal("3.0")  # 3× = flag for review


REQUIRED_NOTES_BY_PROFILE: dict[Profile, list[str]] = {
    Profile.P1_INDUSTRIAL: [
        "taxes",
        "leases",
        "ppe",
        "inventory",
        "trade_receivables",
        "trade_payables",
        "employee_benefits",
        "financial_instruments",
        "commitments_contingencies",
        "provisions",
    ],
    # P2–P6 land in Phase 2. REQUIRED_NOTES lookup returns [] for any
    # profile without an entry — validator treats that as "no
    # completeness check configured".
}

RECOMMENDED_NOTES_BY_PROFILE: dict[Profile, list[str]] = {
    Profile.P1_INDUSTRIAL: [
        "goodwill",
        "intangibles",
        "share_based_compensation",
        "pensions",
        "acquisitions",
    ],
}


# ======================================================================
# Result dataclasses
# ======================================================================
@dataclass(frozen=True)
class ValidationResult:
    """One row of a validation report."""

    check_id: str
    status: ValidationStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Aggregate result with helpers for CLI / pipeline consumers."""

    tier: Literal["strict", "warn", "completeness"]
    results: list[ValidationResult] = field(default_factory=list)

    def add(self, result: ValidationResult) -> None:
        self.results.append(result)

    @property
    def overall_status(self) -> ValidationStatus:
        """Worst-case across results. Precedence: FAIL > WARN > OK > SKIP."""
        order: dict[ValidationStatus, int] = {
            "FAIL": 3,
            "WARN": 2,
            "OK": 1,
            "SKIP": 0,
        }
        if not self.results:
            return "OK"
        return max(self.results, key=lambda r: order[r.status]).status

    @property
    def fails(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == "FAIL"]

    @property
    def warns(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == "WARN"]


# ======================================================================
# Helpers
# ======================================================================
def _pct_delta(computed: Decimal, reported: Decimal) -> Decimal:
    """Relative |computed − reported| / |reported| (or |computed| on
    zero reported)."""
    divisor = abs(reported) if reported != 0 else abs(computed) if computed != 0 else Decimal("1")
    return abs(computed - reported) / divisor


def _or_none(value: Decimal | None) -> Decimal:
    """Treat ``None`` as zero in arithmetic checks (callers already
    guard against missing inputs explicitly)."""
    return value if value is not None else Decimal("0")


# ======================================================================
# Validator
# ======================================================================
class ExtractionValidator:
    """Run the three tiers of checks against a :class:`RawExtraction`."""

    # ── Strict (blocking) ─────────────────────────────────────────
    def validate_strict(self, extraction: RawExtraction) -> ValidationReport:
        report = ValidationReport(tier="strict")
        primary = extraction.primary_period
        is_data = extraction.primary_is
        bs_data = extraction.primary_bs

        # Metadata completeness — trivially enforced by the schema but
        # we surface a reassuring OK here so the report tells the full
        # story.
        report.add(
            ValidationResult(
                check_id="S.M1",
                status="OK",
                message=(
                    f"Metadata populated: ticker={extraction.metadata.ticker}, "
                    f"document_type={extraction.metadata.document_type.value}, "
                    f"currency={extraction.metadata.reporting_currency.value}, "
                    f"unit_scale={extraction.metadata.unit_scale}."
                ),
            )
        )

        # IS identity — sum of categorised components ≈ operating_income
        report.add(self._check_is_arithmetic(is_data, primary.period))

        # BS identity — Assets == Liab + Equity
        report.add(self._check_bs_identity(bs_data, primary.period))

        return report

    # ── Warn (non-blocking) ───────────────────────────────────────
    def validate_warn(self, extraction: RawExtraction) -> ValidationReport:
        report = ValidationReport(tier="warn")
        primary = extraction.primary_period

        report.add(self._check_cf_identity(extraction.primary_cf, primary.period))
        report.add(
            self._check_capex_vs_ppe_movement(
                extraction.primary_cf,
                extraction.primary_is,
                extraction.primary_bs,
                periods=self._period_labels(extraction),
                bs_by_period=extraction.balance_sheet,
            )
        )
        report.add(
            self._check_dividends_vs_retained(
                extraction.primary_cf,
                extraction.primary_is,
                periods=self._period_labels(extraction),
                bs_by_period=extraction.balance_sheet,
            )
        )
        report.add(self._check_shares_consistency(extraction.primary_is, extraction.primary_bs))
        if extraction.notes.leases is not None:
            report.add(self._check_lease_movement(extraction.notes.leases))
        report.add(self._check_yoy_sanity(extraction))
        return report

    # ── Completeness (profile-driven) ──────────────────────────────
    def validate_completeness(
        self, extraction: RawExtraction, profile: Profile
    ) -> ValidationReport:
        report = ValidationReport(tier="completeness")
        required = REQUIRED_NOTES_BY_PROFILE.get(profile, [])
        recommended = RECOMMENDED_NOTES_BY_PROFILE.get(profile, [])
        if not required and not recommended:
            report.add(
                ValidationResult(
                    check_id="C.P0",
                    status="SKIP",
                    message=(
                        f"No completeness checklist configured for profile "
                        f"{profile.value}; skipping."
                    ),
                )
            )
            return report

        notes = extraction.notes
        for note_name in required:
            r_status: ValidationStatus = (
                "OK" if self._note_populated(notes, note_name) else "FAIL"
            )
            report.add(
                ValidationResult(
                    check_id=f"C.R.{note_name}",
                    status=r_status,
                    message=(
                        f"Required note {note_name!r} "
                        + ("present" if r_status == "OK" else "MISSING")
                        + f" for profile {profile.value}."
                    ),
                )
            )
        for note_name in recommended:
            o_status: ValidationStatus = (
                "OK" if self._note_populated(notes, note_name) else "WARN"
            )
            report.add(
                ValidationResult(
                    check_id=f"C.O.{note_name}",
                    status=o_status,
                    message=(
                        f"Recommended note {note_name!r} "
                        + ("present" if o_status == "OK" else "absent")
                        + f" for profile {profile.value}."
                    ),
                )
            )
        return report

    # ==================================================================
    # Strict checks
    # ==================================================================
    def _check_is_arithmetic(
        self, is_data: IncomeStatementPeriod | None, period: str
    ) -> ValidationResult:
        if is_data is None:
            return ValidationResult(
                "S.IS", "SKIP", f"No IS for primary period {period}."
            )
        if is_data.revenue is None or is_data.operating_income is None:
            return ValidationResult(
                "S.IS",
                "SKIP",
                "Cannot check IS arithmetic without revenue + operating_income.",
            )
        # revenue + cost_of_sales + opex + d_and_a + other ≈ operating_income
        components = (
            _or_none(is_data.revenue)
            + _or_none(is_data.cost_of_sales)
            + _or_none(is_data.selling_marketing)
            + _or_none(is_data.general_administrative)
            + _or_none(is_data.selling_general_administrative)
            + _or_none(is_data.research_development)
            + _or_none(is_data.other_operating_expenses)
            + _or_none(is_data.depreciation_amortization)
        )
        reported = is_data.operating_income
        delta = _pct_delta(components, reported)
        status: ValidationStatus = "OK" if delta <= _IS_TOL else "FAIL"
        return ValidationResult(
            "S.IS",
            status,
            (
                f"IS arithmetic {period}: Σ components = {components} vs reported "
                f"Op Income = {reported} (Δ = {delta:.4%}; tolerance "
                f"{_IS_TOL:.1%})."
            ),
            data={"computed": str(components), "reported": str(reported),
                  "delta": str(delta)},
        )

    def _check_bs_identity(
        self, bs_data: BalanceSheetPeriod | None, period: str
    ) -> ValidationResult:
        if bs_data is None:
            return ValidationResult(
                "S.BS", "SKIP", f"No BS for primary period {period}."
            )
        total_assets = bs_data.total_assets
        total_liab = bs_data.total_liabilities
        total_equity = bs_data.total_equity
        if total_assets is None or total_liab is None or total_equity is None:
            return ValidationResult(
                "S.BS",
                "SKIP",
                "Cannot check BS identity without total_assets, "
                "total_liabilities, total_equity.",
            )
        rhs = total_liab + total_equity
        delta = _pct_delta(rhs, total_assets)
        status: ValidationStatus = "OK" if delta <= _BS_TOL else "FAIL"
        return ValidationResult(
            "S.BS",
            status,
            (
                f"BS identity {period}: Assets {total_assets} vs Liab+Equity "
                f"{rhs} (Δ = {delta:.4%}; tolerance {_BS_TOL:.2%})."
            ),
            data={
                "assets": str(total_assets),
                "liab_plus_equity": str(rhs),
                "delta": str(delta),
            },
        )

    # ==================================================================
    # Warn checks
    # ==================================================================
    def _check_cf_identity(self, cf_data: Any, period: str) -> ValidationResult:
        if cf_data is None:
            return ValidationResult(
                "W.CF", "SKIP", f"No CF for primary period {period}."
            )
        net_change = cf_data.net_change_in_cash
        if net_change is None:
            return ValidationResult(
                "W.CF",
                "SKIP",
                "CF has no net_change_in_cash line — cannot verify identity.",
            )
        computed = (
            _or_none(cf_data.operating_cash_flow)
            + _or_none(cf_data.investing_cash_flow)
            + _or_none(cf_data.financing_cash_flow)
            + _or_none(cf_data.fx_effect)
        )
        delta = _pct_delta(computed, net_change)
        status: ValidationStatus = "OK" if delta <= _CF_TOL else "WARN"
        return ValidationResult(
            "W.CF",
            status,
            (
                f"CF identity: CFO + CFI + CFF + FX = {computed} vs Δcash "
                f"{net_change} (Δ = {delta:.2%}; tolerance {_CF_TOL:.1%})."
            ),
            data={"computed": str(computed), "reported": str(net_change),
                  "delta": str(delta)},
        )

    def _check_capex_vs_ppe_movement(
        self,
        cf_data: Any,
        is_data: IncomeStatementPeriod | None,
        bs_data: BalanceSheetPeriod | None,
        periods: list[str],
        bs_by_period: dict[str, BalanceSheetPeriod],
    ) -> ValidationResult:
        if cf_data is None or is_data is None or bs_data is None:
            return ValidationResult(
                "W.CAPEX",
                "SKIP",
                "Need CF + IS + BS for capex-vs-ΔPPE check.",
            )
        capex = cf_data.capex
        d_and_a = is_data.depreciation_amortization
        current_ppe = bs_data.ppe_net
        if capex is None or d_and_a is None or current_ppe is None:
            return ValidationResult(
                "W.CAPEX",
                "SKIP",
                "Need capex + D&A + current PPE_net for check.",
            )
        # Find the prior period (the first period before the primary
        # in the list that has a BS entry)
        prior_ppe: Decimal | None = None
        for label in periods:
            if label in bs_by_period and bs_by_period[label].ppe_net is not None:
                candidate = bs_by_period[label]
                if candidate is bs_data:
                    continue
                prior_ppe = candidate.ppe_net
                break
        if prior_ppe is None:
            return ValidationResult(
                "W.CAPEX",
                "SKIP",
                "No prior-period PPE_net to reconcile against.",
            )
        # |capex| ≈ ΔPPE_net + |D&A|
        expected = (current_ppe - prior_ppe) + abs(d_and_a)
        actual = abs(capex)
        delta = _pct_delta(actual, expected) if expected != 0 else Decimal("0")
        status: ValidationStatus = "OK" if delta <= _CAPEX_VS_DELTA_PPE_TOL else "WARN"
        return ValidationResult(
            "W.CAPEX",
            status,
            (
                f"|capex| {actual} vs ΔPPE_net + |D&A| {expected} "
                f"(Δ = {delta:.2%}; tolerance {_CAPEX_VS_DELTA_PPE_TOL:.0%})."
            ),
            data={"computed": str(expected), "reported": str(actual),
                  "delta": str(delta)},
        )

    def _check_dividends_vs_retained(
        self,
        cf_data: Any,
        is_data: IncomeStatementPeriod | None,
        periods: list[str],
        bs_by_period: dict[str, BalanceSheetPeriod],
    ) -> ValidationResult:
        if cf_data is None or is_data is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need CF + IS for dividends check."
            )
        dividends = cf_data.dividends_paid
        net_income = is_data.net_income
        if dividends is None or net_income is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need dividends + NI for check."
            )
        # ΔRE ≈ NI − |dividends|
        primary_re: Decimal | None = None
        prior_re: Decimal | None = None
        for label in periods:
            bs = bs_by_period.get(label)
            if bs is None or bs.retained_earnings is None:
                continue
            if primary_re is None:
                primary_re = bs.retained_earnings
            else:
                prior_re = bs.retained_earnings
                break
        if primary_re is None or prior_re is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need two periods of retained_earnings."
            )
        delta_re = primary_re - prior_re
        expected = net_income - abs(dividends)
        delta = _pct_delta(delta_re, expected) if expected != 0 else Decimal("0")
        status: ValidationStatus = "OK" if delta <= _DIVIDENDS_VS_RE_TOL else "WARN"
        return ValidationResult(
            "W.DIV",
            status,
            (
                f"ΔRetained earnings {delta_re} vs NI − |dividends| {expected} "
                f"(Δ = {delta:.2%}; tolerance {_DIVIDENDS_VS_RE_TOL:.1%})."
            ),
            data={"computed": str(expected), "reported": str(delta_re),
                  "delta": str(delta)},
        )

    def _check_shares_consistency(
        self,
        is_data: IncomeStatementPeriod | None,
        bs_data: BalanceSheetPeriod | None,
    ) -> ValidationResult:
        if is_data is None:
            return ValidationResult("W.SHARES", "SKIP", "No IS for shares check.")
        basic = is_data.shares_basic_weighted_avg
        diluted = is_data.shares_diluted_weighted_avg
        if basic is None or diluted is None:
            return ValidationResult(
                "W.SHARES",
                "SKIP",
                "Need both basic + diluted weighted-average shares.",
            )
        if basic > diluted + Decimal("0.01"):
            return ValidationResult(
                "W.SHARES",
                "WARN",
                f"Basic shares {basic} > diluted {diluted} — unexpected.",
                data={"basic": str(basic), "diluted": str(diluted)},
            )
        return ValidationResult(
            "W.SHARES",
            "OK",
            f"Basic {basic} ≤ diluted {diluted}.",
        )

    def _check_lease_movement(self, lease_note: Any) -> ValidationResult:
        """Closing = opening + additions − principal_payments (IFRS 16)."""
        opening = lease_note.lease_liabilities_opening
        closing = lease_note.lease_liabilities_closing
        additions = lease_note.rou_assets_additions
        principal = lease_note.lease_principal_payments
        if any(v is None for v in (opening, closing, additions, principal)):
            return ValidationResult(
                "W.LEASE",
                "SKIP",
                "Need lease opening + closing + additions + principal payments.",
            )
        expected = _or_none(opening) + _or_none(additions) - _or_none(principal)
        delta = _pct_delta(expected, _or_none(closing))
        status: ValidationStatus = "OK" if delta <= _CF_TOL else "WARN"
        return ValidationResult(
            "W.LEASE",
            status,
            (
                f"Lease closing {closing} vs opening + additions − principal "
                f"{expected} (Δ = {delta:.2%})."
            ),
            data={"computed": str(expected), "reported": str(closing),
                  "delta": str(delta)},
        )

    def _check_yoy_sanity(self, extraction: RawExtraction) -> ValidationResult:
        """Revenue 3× between adjacent periods warrants a look."""
        labels = self._period_labels(extraction)
        if len(labels) < 2:
            return ValidationResult(
                "W.YOY",
                "SKIP",
                "Need at least two periods for YoY sanity check.",
            )
        current = extraction.income_statement.get(labels[0])
        prior = extraction.income_statement.get(labels[1])
        if current is None or prior is None:
            return ValidationResult("W.YOY", "SKIP", "Missing IS for YoY.")
        if current.revenue is None or prior.revenue is None:
            return ValidationResult("W.YOY", "SKIP", "Missing revenue for YoY.")
        if prior.revenue == 0:
            return ValidationResult(
                "W.YOY", "SKIP", "Prior-period revenue is zero."
            )
        ratio = abs(current.revenue) / abs(prior.revenue)
        status: ValidationStatus = (
            "WARN" if ratio >= _YOY_GROWTH_FLAG_THRESHOLD else "OK"
        )
        return ValidationResult(
            "W.YOY",
            status,
            (
                f"YoY revenue ratio {ratio:.2f}× "
                f"(flag threshold ≥ {_YOY_GROWTH_FLAG_THRESHOLD}×)."
            ),
            data={"current": str(current.revenue), "prior": str(prior.revenue),
                  "ratio": str(ratio)},
        )

    # ==================================================================
    # Helpers
    # ==================================================================
    def _period_labels(self, extraction: RawExtraction) -> list[str]:
        """Fiscal period labels in declaration order. Primary first."""
        primary_label = extraction.primary_period.period
        others = [
            fp.period
            for fp in extraction.metadata.fiscal_periods
            if fp.period != primary_label
        ]
        return [primary_label, *others]

    def _note_populated(self, notes: NotesContainer, name: str) -> bool:
        value = getattr(notes, name, None)
        if value is None:
            return False
        if isinstance(value, list | dict):
            return len(value) > 0
        # Note models are populated if any Decimal field is set.
        dumped = value.model_dump(mode="python") if hasattr(value, "model_dump") else {}
        return any(v is not None for v in dumped.values() if not isinstance(v, dict))


__all__ = [
    "ExtractionValidator",
    "ValidationReport",
    "ValidationResult",
    "ValidationStatus",
    "REQUIRED_NOTES_BY_PROFILE",
    "RECOMMENDED_NOTES_BY_PROFILE",
]
