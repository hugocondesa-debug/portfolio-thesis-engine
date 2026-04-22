"""Three-tier validator for :class:`RawExtraction` artefacts.

Phase 1.5.3 rewrite: validation works on the as-reported structured
schema (``line_items`` lists with subtotal flags + section grouping).

Tiers:

- :meth:`ExtractionValidator.validate_strict` — accounting identities
  that MUST hold. A FAIL blocks the pipeline. Tight tolerances.

  - **S.IS** — walking subtotals on the IS: each ``is_subtotal=True``
    line equals the running sum of preceding non-subtotal lines
    (within ±0.5%). Running sum resets after each subtotal.
  - **S.BS.SECTIONS** — within each BS section, the running sum of
    non-subtotal items equals any section-ending subtotal (e.g. the
    running sum of current-asset lines equals "Total current
    assets").
  - **S.BS.IDENTITY** — total assets = total liabilities + total
    equity (within ±0.1%). Pulled from the lines flagged
    ``is_subtotal=True`` with ``section in {total_assets,
    total_liabilities, equity (final)}``.
  - **S.CF** — same walking-subtotals logic per CF section plus the
    overall Δcash walk (sum of section subtotals + fx_effect =
    reported Δcash).

- :meth:`ExtractionValidator.validate_warn` — softer checks. Don't
  block; surface on the audit report.

  - **W.CAPEX** — |capex-like line| ≈ ΔPPE + |D&A|. Capex line
    found by label pattern in CF investing section; PPE and D&A
    found by label pattern in BS / IS (relaxed since acquisitions
    column may exist).
  - **W.DIV** — dividends paid (CF financing) vs. ΔRE − NI.
  - **W.SHARES** — basic ≤ diluted EPS weighted-avg shares.
  - **W.YOY** — adjacent-period revenue ratio sanity (≥3× = flag).

- :meth:`ExtractionValidator.validate_completeness` — profile-driven
  note coverage. Notes are matched by title pattern against
  regex — the schema no longer carries typed note fields.

Each method returns a :class:`ValidationReport` with per-check
results. The CLI renders the report as a Rich table; the pipeline
stage pulls the strict report's :attr:`overall_status` to decide
whether to block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    LineItem,
    Note,
    RawExtraction,
)

ValidationStatus = Literal["OK", "WARN", "FAIL", "SKIP"]

_IS_TOL = Decimal("0.005")  # 0.5 %
_BS_SECTION_TOL = Decimal("0.005")  # 0.5 %
_BS_IDENTITY_TOL = Decimal("0.001")  # 0.1 %
_CF_TOL = Decimal("0.02")  # 2 %
_CAPEX_VS_DELTA_PPE_TOL = Decimal("0.05")  # 5 %
_DIVIDENDS_VS_RE_TOL = Decimal("0.02")  # 2 %
_YOY_GROWTH_FLAG_THRESHOLD = Decimal("3.0")


# ======================================================================
# Note-title patterns for completeness (Phase 1.5.3)
# ======================================================================
# Each required / recommended note is matched by a regex against the
# note's ``title`` (case-insensitive). A note is considered "present"
# if any Note in the extraction matches the pattern AND has at least
# one populated table or a narrative_summary.
REQUIRED_NOTE_PATTERNS: dict[Profile, dict[str, re.Pattern[str]]] = {
    Profile.P1_INDUSTRIAL: {
        "taxes": re.compile(r"income tax|taxation", re.IGNORECASE),
        "leases": re.compile(r"leases?\b", re.IGNORECASE),
        "ppe": re.compile(
            r"property,? plant|property and equipment|plant and equipment",
            re.IGNORECASE,
        ),
        "inventory": re.compile(r"inventor(y|ies)", re.IGNORECASE),
        "trade_receivables": re.compile(
            r"trade (and other )?receivable|accounts receivable", re.IGNORECASE
        ),
        "trade_payables": re.compile(
            r"trade (and other )?payable|accounts payable", re.IGNORECASE
        ),
        "employee_benefits": re.compile(
            r"employee|staff cost|salaries|compensation", re.IGNORECASE
        ),
        "financial_instruments": re.compile(
            r"financial instrument|financial risk|credit risk|liquidity risk",
            re.IGNORECASE,
        ),
        "commitments_contingencies": re.compile(
            r"commitment|contingen", re.IGNORECASE
        ),
        "provisions": re.compile(r"provisions?\b", re.IGNORECASE),
    },
}

RECOMMENDED_NOTE_PATTERNS: dict[Profile, dict[str, re.Pattern[str]]] = {
    Profile.P1_INDUSTRIAL: {
        "goodwill": re.compile(r"goodwill", re.IGNORECASE),
        "intangibles": re.compile(r"intangible", re.IGNORECASE),
        "share_based_compensation": re.compile(
            r"share[- ]based|stock option|sbc\b", re.IGNORECASE
        ),
        "pensions": re.compile(r"pension|retirement benefit|defined benefit",
                               re.IGNORECASE),
        "acquisitions": re.compile(
            r"acquisition|business combination", re.IGNORECASE
        ),
    },
}


# Legacy name list for tests that assert coverage expectations.
REQUIRED_NOTES_BY_PROFILE: dict[Profile, list[str]] = {
    profile: list(patterns.keys())
    for profile, patterns in REQUIRED_NOTE_PATTERNS.items()
}
RECOMMENDED_NOTES_BY_PROFILE: dict[Profile, list[str]] = {
    profile: list(patterns.keys())
    for profile, patterns in RECOMMENDED_NOTE_PATTERNS.items()
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
    divisor = (
        abs(reported)
        if reported != 0
        else abs(computed) if computed != 0 else Decimal("1")
    )
    return abs(computed - reported) / divisor


def _ordered(items: list[LineItem]) -> list[LineItem]:
    return sorted(items, key=lambda li: li.order)


def _find_line(
    items: list[LineItem], pattern: re.Pattern[str]
) -> LineItem | None:
    """First non-subtotal line whose label matches ``pattern``."""
    for item in items:
        if item.is_subtotal:
            continue
        if pattern.search(item.label):
            return item
    return None


def _find_subtotal(
    items: list[LineItem], pattern: re.Pattern[str]
) -> LineItem | None:
    """First subtotal line whose label matches ``pattern``."""
    for item in items:
        if not item.is_subtotal:
            continue
        if pattern.search(item.label):
            return item
    return None


def _find_last_equity_subtotal(items: list[LineItem]) -> LineItem | None:
    """Phase 1.5.5: return the LAST ``is_subtotal=True`` line in
    ``section="equity"``. Typical pattern in IFRS balance sheets:
    "Total equity attributable to owners" (TEP) appears first, then
    "Non-controlling interests", then "Total equity" (TEP + NCI) last.
    The grand total — the last subtotal — is what belongs in the
    A = L + E identity."""
    equity_subtotals = [
        item for item in items
        if item.is_subtotal and item.section == "equity"
    ]
    if not equity_subtotals:
        return None
    return equity_subtotals[-1]


def _find_cf_net_change(items: list[LineItem]) -> LineItem | None:
    """Phase 1.5.5: find the CF Δcash anchor line.

    Priority:
    1. ``is_subtotal=True`` + label matches /net (increase|decrease|
       change) in cash/ + no memo marker in ``notes``.
    2. Fallback: the legacy "net_change_in_cash" category token (now
       maps to section="subtotal" on Phase 1.5.3 schema).

    Memo lines (opening / closing cash balances tagged in ``notes``
    as "memo" or "reconciliation") are explicitly excluded — they
    often carry ``is_subtotal=True`` and the raw section
    ``"subtotal"``, which otherwise confuses the heuristic.
    """
    for item in items:
        if not item.is_subtotal or item.value is None:
            continue
        if item.notes and _MEMO_NOTE_PATTERN.search(item.notes):
            continue
        if _NET_CHANGE_IN_CASH_LABEL.search(item.label):
            return item
    # Fallback: any non-memo subtotal in the "subtotal" section.
    for item in items:
        if not item.is_subtotal or item.value is None:
            continue
        if item.section != "subtotal":
            continue
        if item.notes and _MEMO_NOTE_PATTERN.search(item.notes):
            continue
        return item
    return None


# Common subtotal / line patterns
_PPE_LABEL = re.compile(
    r"property,? plant|property and equipment|plant and equipment", re.IGNORECASE
)
_DEPRECIATION_LABEL = re.compile(r"depreciation|amorti[sz]ation", re.IGNORECASE)
_CAPEX_LABEL = re.compile(
    r"purchas[ae].*property|purchas[ae].*plant|capital expenditure|addition.*property",
    re.IGNORECASE,
)
_DIVIDENDS_LABEL = re.compile(r"dividend.*paid|payment.*dividend", re.IGNORECASE)
_NET_INCOME_LABEL = re.compile(
    r"profit for the (year|period)|net (income|profit|earnings)", re.IGNORECASE
)
_RETAINED_EARNINGS_LABEL = re.compile(
    r"retained earning|reserves? \(retained\)", re.IGNORECASE
)
_REVENUE_LABEL = re.compile(r"^revenue$|^total revenue$|^sales$", re.IGNORECASE)
_TOTAL_ASSETS_LABEL = re.compile(r"total assets", re.IGNORECASE)
_TOTAL_LIAB_LABEL = re.compile(r"total liabilities", re.IGNORECASE)
_TOTAL_EQUITY_LABEL = re.compile(r"total equity|total shareholders'?\s?equity",
                                 re.IGNORECASE)

# Phase 1.5.5: IFRS IS patterns
_OCI_HEADER_LABEL = re.compile(
    r"other comprehensive (income|loss|\(loss\)/income|\(income\)/loss)",
    re.IGNORECASE,
)
_OCI_SUBHEADER_LABEL = re.compile(
    r"items that (may|will) (not )?be reclassified", re.IGNORECASE
)
_TCI_LABEL = re.compile(
    r"total comprehensive (income|loss)", re.IGNORECASE
)
_PFY_LABEL = re.compile(
    r"profit for the (year|period)|net (income|profit|earnings)",
    re.IGNORECASE,
)

# CF Δcash identification
_NET_CHANGE_IN_CASH_LABEL = re.compile(
    r"net (increase|decrease|change) in cash", re.IGNORECASE
)
_MEMO_NOTE_PATTERN = re.compile(r"memo|reconciliation", re.IGNORECASE)


# ======================================================================
# Validator
# ======================================================================
class ExtractionValidator:
    """Three tiers of checks against a :class:`RawExtraction`."""

    # ── Strict (blocking) ─────────────────────────────────────────
    def validate_strict(self, extraction: RawExtraction) -> ValidationReport:
        report = ValidationReport(tier="strict")
        primary = extraction.primary_period

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

        # IS walking subtotals
        for r in self._check_is_arithmetic(extraction.primary_is, primary.period):
            report.add(r)
        # BS walking subtotals per section
        for r in self._check_bs_sections(extraction.primary_bs, primary.period):
            report.add(r)
        # BS identity: Assets = Liab + Equity
        report.add(self._check_bs_identity(extraction.primary_bs, primary.period))
        # CF walking subtotals per section
        for r in self._check_cf_sections(extraction.primary_cf, primary.period):
            report.add(r)

        return report

    # ── Warn (non-blocking) ───────────────────────────────────────
    def validate_warn(self, extraction: RawExtraction) -> ValidationReport:
        report = ValidationReport(tier="warn")
        primary = extraction.primary_period
        bs_by_period = extraction.balance_sheet
        period_labels = self._period_labels(extraction)

        report.add(self._check_cf_identity(extraction.primary_cf, primary.period))
        report.add(
            self._check_capex_vs_ppe_movement(
                extraction.primary_cf,
                extraction.primary_is,
                extraction.primary_bs,
                period_labels,
                bs_by_period,
            )
        )
        report.add(
            self._check_dividends_vs_retained(
                extraction.primary_cf,
                extraction.primary_is,
                period_labels,
                bs_by_period,
            )
        )
        report.add(self._check_shares_consistency(extraction.primary_is))
        report.add(self._check_yoy_sanity(extraction))
        return report

    # ── Completeness ──────────────────────────────────────────────
    def validate_completeness(
        self, extraction: RawExtraction, profile: Profile
    ) -> ValidationReport:
        """Walk required + recommended note patterns for the profile.

        Phase 1.5.11: when the source is unaudited (investor
        presentation, preliminary announcement, pre-audit disclosure),
        required notes demote from ``FAIL`` to ``WARN`` — pre-audit
        sources disclose fewer notes by design and should not be
        blocked by their absence. Strict arithmetic checks (IS / BS /
        CF identities) remain unchanged.
        """
        from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

        report = ValidationReport(tier="completeness")
        required = REQUIRED_NOTE_PATTERNS.get(profile, {})
        recommended = RECOMMENDED_NOTE_PATTERNS.get(profile, {})
        unaudited = extraction.metadata.audit_status == AuditStatus.UNAUDITED
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

        for name, pattern in required.items():
            present = self._note_present(extraction.notes, pattern)
            # Phase 1.5.11 — unaudited sources demote required→WARN.
            if present:
                status: ValidationStatus = "OK"
                msg_suffix = "present"
            elif unaudited:
                status = "WARN"
                msg_suffix = (
                    "MISSING (expected absence — unaudited source)"
                )
            else:
                status = "FAIL"
                msg_suffix = "MISSING"
            report.add(
                ValidationResult(
                    check_id=f"C.R.{name}",
                    status=status,
                    message=(
                        f"Required note {name!r} {msg_suffix} "
                        f"for profile {profile.value}."
                    ),
                )
            )
        for name, pattern in recommended.items():
            present = self._note_present(extraction.notes, pattern)
            status_o: ValidationStatus = "OK" if present else "WARN"
            report.add(
                ValidationResult(
                    check_id=f"C.O.{name}",
                    status=status_o,
                    message=(
                        f"Recommended note {name!r} "
                        + ("present" if present else "absent")
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
    ) -> list[ValidationResult]:
        """Walking subtotals on the IS with IFRS-aware handling.

        Three behaviours:

        - **Waterfall subtotals** (default) — Σ preceding non-subtotal
          items. Resets the running sum to the subtotal's reported
          value (Gross profit → Operating profit → PBT → PFY).
        - **Nested subtotals** (``skip_in_waterfall=True``) — sub-sum
          of adjacent lines (e.g. "Finance income/(expenses), net").
          Verified against ``running_sum − last_waterfall_anchor``.
          Does NOT reset the anchor.
        - **OCI section** — detected by header label pattern. OCI
          items accumulate to an independent ``oci_sum`` starting
          from zero. OCI subtotal (``S.IS.OCI``) verifies oci_sum.
          TCI subtotal (``S.IS.TCI``) verifies PFY + OCI subtotal
          (not cumulative).
        """
        if is_data is None or not is_data.line_items:
            return [
                ValidationResult(
                    "S.IS", "SKIP",
                    f"No IS line_items for primary period {period}.",
                )
            ]

        items = _ordered(is_data.line_items)
        results: list[ValidationResult] = []
        waterfall_running = Decimal("0")
        waterfall_anchor = Decimal("0")
        saw_waterfall_non_subtotal = False
        pfy_value: Decimal | None = None  # value of the last PFY-style subtotal before OCI
        oci_running = Decimal("0")
        oci_subtotal_value: Decimal | None = None
        in_oci = False
        subtotal_idx = 0
        oci_sub_emitted = False

        for item in items:
            # OCI section entry — detect by header (null value is
            # expected but we don't strictly require it).
            if _OCI_HEADER_LABEL.search(item.label) and item.value is None:
                in_oci = True
                # Snapshot PFY = last waterfall anchor (= last
                # subtotal value = PFY)
                pfy_value = waterfall_anchor
                oci_running = Decimal("0")
                continue
            if in_oci and _OCI_SUBHEADER_LABEL.search(item.label) and item.value is None:
                # Sub-header inside OCI — no value, skip
                continue

            if item.is_subtotal:
                if item.value is None:
                    continue

                # TCI check — dedicated
                if in_oci and _TCI_LABEL.search(item.label):
                    if pfy_value is None or oci_subtotal_value is None:
                        results.append(
                            ValidationResult(
                                "S.IS.TCI", "SKIP",
                                (
                                    f"IS {period}: TCI line found but "
                                    f"PFY snapshot or OCI subtotal missing."
                                ),
                            )
                        )
                    else:
                        expected = pfy_value + oci_subtotal_value
                        delta = _pct_delta(expected, item.value)
                        status: ValidationStatus = (
                            "OK" if delta <= _IS_TOL else "FAIL"
                        )
                        results.append(
                            ValidationResult(
                                "S.IS.TCI",
                                status,
                                (
                                    f"IS {period}: TCI check — "
                                    f"PFY {pfy_value} + OCI subtotal "
                                    f"{oci_subtotal_value} = {expected} vs "
                                    f"reported {item.value} "
                                    f"(Δ = {delta:.4%}; tolerance "
                                    f"{_IS_TOL:.1%})."
                                ),
                                data={
                                    "pfy": str(pfy_value),
                                    "oci_subtotal": str(oci_subtotal_value),
                                    "computed": str(expected),
                                    "reported": str(item.value),
                                    "delta": str(delta),
                                },
                            )
                        )
                    # TCI ends the IS; continue but nothing more
                    # to accumulate.
                    continue

                # OCI subtotal — first non-TCI subtotal inside OCI
                # that has a value.
                if in_oci and not oci_sub_emitted:
                    delta = _pct_delta(oci_running, item.value)
                    status = "OK" if delta <= _IS_TOL else "FAIL"
                    results.append(
                        ValidationResult(
                            "S.IS.OCI",
                            status,
                            (
                                f"IS {period}: OCI subtotal — "
                                f"Σ OCI items = {oci_running} vs reported "
                                f"{item.label!r} = {item.value} "
                                f"(Δ = {delta:.4%}; tolerance "
                                f"{_IS_TOL:.1%})."
                            ),
                            data={
                                "subtotal_label": item.label,
                                "computed_sum": str(oci_running),
                                "reported_subtotal": str(item.value),
                                "delta": str(delta),
                            },
                        )
                    )
                    oci_subtotal_value = item.value
                    oci_sub_emitted = True
                    continue

                # PnL subtotal
                if not saw_waterfall_non_subtotal:
                    # Cross-section grand total before any leaves —
                    # skip (handled by dedicated identity checks).
                    continue

                if item.skip_in_waterfall:
                    # Extractor flagged nested — verify via nested sum.
                    nested_sum = waterfall_running - waterfall_anchor
                    delta = _pct_delta(nested_sum, item.value)
                    status = "OK" if delta <= _IS_TOL else "FAIL"
                    subtotal_idx += 1
                    results.append(
                        ValidationResult(
                            f"S.IS.NESTED{subtotal_idx}",
                            status,
                            (
                                f"IS {period}: nested subtotal "
                                f"{item.label!r} — Σ items since last "
                                f"waterfall anchor = {nested_sum} vs "
                                f"reported {item.value} "
                                f"(Δ = {delta:.4%}; tolerance "
                                f"{_IS_TOL:.1%})."
                            ),
                            data={
                                "subtotal_label": item.label,
                                "computed_sum": str(nested_sum),
                                "reported_subtotal": str(item.value),
                                "delta": str(delta),
                            },
                        )
                    )
                    continue

                # Waterfall subtotal — check arithmetic. Two candidate
                # interpretations: (a) waterfall (running_sum) or (b)
                # auto-detected nested (running_sum − anchor). Prefer
                # waterfall; fall back to nested if waterfall delta
                # exceeds tolerance AND nested delta is within it.
                subtotal_idx += 1
                waterfall_delta = _pct_delta(waterfall_running, item.value)
                nested_candidate = waterfall_running - waterfall_anchor
                nested_delta = _pct_delta(nested_candidate, item.value)

                if waterfall_delta <= _IS_TOL:
                    # Accept as waterfall subtotal.
                    results.append(
                        ValidationResult(
                            f"S.IS.SUB{subtotal_idx}",
                            "OK",
                            (
                                f"IS {period}: Σ preceding = "
                                f"{waterfall_running} vs subtotal "
                                f"{item.label!r} = {item.value} "
                                f"(Δ = {waterfall_delta:.4%}; tolerance "
                                f"{_IS_TOL:.1%})."
                            ),
                            data={
                                "subtotal_label": item.label,
                                "computed_sum": str(waterfall_running),
                                "reported_subtotal": str(item.value),
                                "delta": str(waterfall_delta),
                            },
                        )
                    )
                    waterfall_running = item.value
                    waterfall_anchor = item.value
                elif nested_delta <= _IS_TOL:
                    # Auto-detected nested subtotal: waterfall check
                    # fails but sum-since-anchor matches. Examples:
                    # "Finance income/(expenses), net" sums adjacent
                    # finance lines without resetting the waterfall.
                    results.append(
                        ValidationResult(
                            f"S.IS.NESTED{subtotal_idx}",
                            "OK",
                            (
                                f"IS {period}: auto-detected nested "
                                f"subtotal {item.label!r} — Σ items since "
                                f"last waterfall anchor = {nested_candidate}"
                                f" vs reported {item.value} "
                                f"(Δ = {nested_delta:.4%}; tolerance "
                                f"{_IS_TOL:.1%}). Not resetting waterfall. "
                                f"Mark ``skip_in_waterfall: true`` in the "
                                f"extraction to make this explicit."
                            ),
                            data={
                                "subtotal_label": item.label,
                                "computed_sum": str(nested_candidate),
                                "reported_subtotal": str(item.value),
                                "delta": str(nested_delta),
                                "auto_detected_nested": "true",
                            },
                        )
                    )
                    # DO NOT reset waterfall state.
                else:
                    # Genuine FAIL — neither interpretation matches.
                    results.append(
                        ValidationResult(
                            f"S.IS.SUB{subtotal_idx}",
                            "FAIL",
                            (
                                f"IS {period}: subtotal {item.label!r} = "
                                f"{item.value} doesn't match waterfall "
                                f"(Σ preceding = {waterfall_running}, "
                                f"Δ = {waterfall_delta:.4%}) nor nested "
                                f"sum since last anchor "
                                f"({nested_candidate}, "
                                f"Δ = {nested_delta:.4%}); tolerance "
                                f"{_IS_TOL:.1%}."
                            ),
                            data={
                                "subtotal_label": item.label,
                                "waterfall_sum": str(waterfall_running),
                                "waterfall_delta": str(waterfall_delta),
                                "nested_sum": str(nested_candidate),
                                "nested_delta": str(nested_delta),
                                "reported_subtotal": str(item.value),
                            },
                        )
                    )
                    waterfall_running = item.value
                    waterfall_anchor = item.value
            else:
                if item.value is not None:
                    if in_oci:
                        oci_running += item.value
                    else:
                        waterfall_running += item.value
                        saw_waterfall_non_subtotal = True

        if not results:
            results.append(
                ValidationResult(
                    "S.IS.SUB0",
                    "SKIP",
                    f"IS {period}: no verifiable subtotal.",
                )
            )
        return results

    def _check_bs_sections(
        self, bs_data: BalanceSheetPeriod | None, period: str
    ) -> list[ValidationResult]:
        if bs_data is None or not bs_data.line_items:
            return [
                ValidationResult(
                    "S.BS.SECTIONS", "SKIP",
                    f"No BS line_items for primary period {period}.",
                )
            ]
        # Walk each section independently.
        items = _ordered(bs_data.line_items)
        sections = _group_by_section(items)
        out: list[ValidationResult] = []
        for section_number, (section_name, section_items) in enumerate(sections, start=1):
            sub_results = self._walk_subtotals(
                section_items,
                period_label=period,
                check_id_prefix=f"S.BS.{section_name or f'SECTION{section_number}'}",
                tolerance=_BS_SECTION_TOL,
                scope_name=f"BS [{section_name or 'unspecified'}]",
            )
            out.extend(sub_results)
        return out

    def _check_bs_identity(
        self, bs_data: BalanceSheetPeriod | None, period: str
    ) -> ValidationResult:
        """BS identity: Assets = Liabilities + Total equity (incl. NCI).

        Phase 1.5.5: when the BS has both "Total equity attributable to
        owners" (TEP) and "Total equity" (TEP + NCI) as subtotals in
        the equity section, we pick the **last** equity subtotal —
        which is the grand total including NCI — for the identity
        check. Picking TEP would fail by exactly the NCI amount.
        """
        if bs_data is None or not bs_data.line_items:
            return ValidationResult(
                "S.BS.IDENTITY", "SKIP",
                f"No BS line_items for primary period {period}.",
            )
        total_assets = _find_subtotal(bs_data.line_items, _TOTAL_ASSETS_LABEL)
        total_liab = _find_subtotal(bs_data.line_items, _TOTAL_LIAB_LABEL)
        # Find the LAST equity subtotal (grand total incl. NCI).
        total_equity = _find_last_equity_subtotal(bs_data.line_items)
        if (
            total_assets is None or total_liab is None or total_equity is None
            or total_assets.value is None or total_liab.value is None
            or total_equity.value is None
        ):
            return ValidationResult(
                "S.BS.IDENTITY", "SKIP",
                "Cannot find subtotals for Total Assets / Liab / Equity.",
            )
        rhs = total_liab.value + total_equity.value
        delta = _pct_delta(rhs, total_assets.value)
        status: ValidationStatus = (
            "OK" if delta <= _BS_IDENTITY_TOL else "FAIL"
        )
        return ValidationResult(
            "S.BS.IDENTITY",
            status,
            (
                f"BS identity {period}: Assets {total_assets.value} vs "
                f"Liab+Equity {rhs} (Δ = {delta:.4%}; tolerance "
                f"{_BS_IDENTITY_TOL:.2%})."
            ),
            data={
                "assets": str(total_assets.value),
                "liab_plus_equity": str(rhs),
                "equity_subtotal_label": total_equity.label,
                "delta": str(delta),
            },
        )

    def _check_cf_sections(
        self, cf_data: CashFlowPeriod | None, period: str
    ) -> list[ValidationResult]:
        if cf_data is None or not cf_data.line_items:
            return [
                ValidationResult(
                    "S.CF", "SKIP",
                    f"No CF line_items for primary period {period}.",
                )
            ]
        items = _ordered(cf_data.line_items)
        sections = _group_by_section(items)
        out: list[ValidationResult] = []
        for section_number, (section_name, section_items) in enumerate(sections, start=1):
            sub_results = self._walk_subtotals(
                section_items,
                period_label=period,
                check_id_prefix=f"S.CF.{section_name or f'SECTION{section_number}'}",
                tolerance=_CF_TOL,
                scope_name=f"CF [{section_name or 'unspecified'}]",
            )
            out.extend(sub_results)
        return out

    # ==================================================================
    # Walking-subtotals core routine
    # ==================================================================
    def _walk_subtotals(
        self,
        items: list[LineItem],
        *,
        period_label: str,
        check_id_prefix: str,
        tolerance: Decimal,
        scope_name: str,
    ) -> list[ValidationResult]:
        """Walk ``items`` in declared order, verify each subtotal
        matches the running sum of preceding non-subtotals. Reset
        running sum to the subtotal's reported value afterwards
        (subsequent items build off the new anchor — IS waterfall
        semantics).

        A subtotal that appears with **no preceding non-subtotal
        item** in this call is a cross-section grand total (e.g. BS
        "Total assets" which spans current + non-current groups). The
        walker cannot verify it locally — skipped here; covered
        separately by ``S.BS.IDENTITY`` / ``W.CF``.
        """
        running_sum = Decimal("0")
        saw_non_subtotal = False
        results: list[ValidationResult] = []
        subtotal_idx = 0
        for item in items:
            if item.is_subtotal:
                if item.value is None:
                    continue
                if not saw_non_subtotal:
                    # Cross-section grand total: skip the section walk.
                    continue
                subtotal_idx += 1
                delta = _pct_delta(running_sum, item.value)
                status: ValidationStatus = "OK" if delta <= tolerance else "FAIL"
                results.append(
                    ValidationResult(
                        f"{check_id_prefix}.SUB{subtotal_idx}",
                        status,
                        (
                            f"{scope_name} {period_label}: "
                            f"Σ preceding = {running_sum} vs subtotal "
                            f"{item.label!r} = {item.value} "
                            f"(Δ = {delta:.4%}; tolerance {tolerance:.1%})."
                        ),
                        data={
                            "subtotal_label": item.label,
                            "computed_sum": str(running_sum),
                            "reported_subtotal": str(item.value),
                            "delta": str(delta),
                        },
                    )
                )
                running_sum = item.value
            else:
                if item.value is not None:
                    running_sum += item.value
                    saw_non_subtotal = True
        if not results:
            results.append(
                ValidationResult(
                    f"{check_id_prefix}.SUB0",
                    "SKIP",
                    (
                        f"{scope_name} {period_label}: no verifiable subtotal "
                        f"(cross-section grand totals handled elsewhere)."
                    ),
                )
            )
        return results

    # ==================================================================
    # Warn checks
    # ==================================================================
    def _check_cf_identity(
        self, cf_data: CashFlowPeriod | None, period: str
    ) -> ValidationResult:
        """CF Δcash identity.

        Phase 1.5.5: the Δcash anchor is identified by label match on
        /net (increase|decrease|change) in cash/, and lines flagged as
        memo / reconciliation in ``notes`` are skipped. This avoids
        confusing opening / closing cash balances (which some filings
        carry as subtotals in ``section="subtotal"``) with the real
        Δcash line.
        """
        if cf_data is None or not cf_data.line_items:
            return ValidationResult(
                "W.CF", "SKIP", f"No CF for primary period {period}."
            )
        items = _ordered(cf_data.line_items)
        section_totals: dict[str, Decimal] = {}
        for item in items:
            if not item.is_subtotal or item.value is None:
                continue
            if item.section in ("operating", "investing", "financing", "fx_effect"):
                section_totals[item.section] = item.value

        net_change = _find_cf_net_change(cf_data.line_items)
        if net_change is None or net_change.value is None:
            return ValidationResult(
                "W.CF", "SKIP",
                "No Δcash subtotal line to verify (memo lines filtered).",
            )
        computed = sum(section_totals.values(), start=Decimal("0"))
        delta = _pct_delta(computed, net_change.value)
        status: ValidationStatus = "OK" if delta <= _CF_TOL else "WARN"
        return ValidationResult(
            "W.CF",
            status,
            (
                f"CF identity: Σ sections {computed} vs reported Δcash "
                f"{net_change.label!r} = {net_change.value} "
                f"(Δ = {delta:.2%}; tolerance {_CF_TOL:.1%})."
            ),
            data={
                "computed": str(computed),
                "reported": str(net_change.value),
                "net_change_label": net_change.label,
                "delta": str(delta),
            },
        )

    def _check_capex_vs_ppe_movement(
        self,
        cf_data: CashFlowPeriod | None,
        is_data: IncomeStatementPeriod | None,
        bs_data: BalanceSheetPeriod | None,
        period_labels: list[str],
        bs_by_period: dict[str, BalanceSheetPeriod],
    ) -> ValidationResult:
        if cf_data is None or is_data is None or bs_data is None:
            return ValidationResult(
                "W.CAPEX", "SKIP", "Need CF + IS + BS for capex check."
            )
        capex_line = _find_line(cf_data.line_items, _CAPEX_LABEL)
        d_and_a_line = _find_line(is_data.line_items, _DEPRECIATION_LABEL)
        ppe_line = _find_line(bs_data.line_items, _PPE_LABEL)
        if capex_line is None or d_and_a_line is None or ppe_line is None:
            return ValidationResult(
                "W.CAPEX", "SKIP",
                "Need capex / D&A / PPE lines by label match.",
            )
        if (
            capex_line.value is None or d_and_a_line.value is None
            or ppe_line.value is None
        ):
            return ValidationResult(
                "W.CAPEX", "SKIP", "Matching lines have null values.",
            )
        prior_ppe: Decimal | None = None
        for label in period_labels:
            if label in bs_by_period:
                candidate = bs_by_period[label]
                if candidate is bs_data:
                    continue
                prior_line = _find_line(candidate.line_items, _PPE_LABEL)
                if prior_line and prior_line.value is not None:
                    prior_ppe = prior_line.value
                    break
        if prior_ppe is None:
            return ValidationResult(
                "W.CAPEX", "SKIP", "No prior-period PPE to reconcile against.",
            )
        expected = (ppe_line.value - prior_ppe) + abs(d_and_a_line.value)
        actual = abs(capex_line.value)
        delta = _pct_delta(actual, expected) if expected != 0 else Decimal("0")
        status: ValidationStatus = (
            "OK" if delta <= _CAPEX_VS_DELTA_PPE_TOL else "WARN"
        )
        return ValidationResult(
            "W.CAPEX",
            status,
            (
                f"|capex| {actual} vs ΔPPE + |D&A| {expected} "
                f"(Δ = {delta:.2%}; tolerance {_CAPEX_VS_DELTA_PPE_TOL:.0%})."
            ),
            data={
                "computed": str(expected),
                "reported": str(actual),
                "delta": str(delta),
            },
        )

    def _check_dividends_vs_retained(
        self,
        cf_data: CashFlowPeriod | None,
        is_data: IncomeStatementPeriod | None,
        period_labels: list[str],
        bs_by_period: dict[str, BalanceSheetPeriod],
    ) -> ValidationResult:
        if cf_data is None or is_data is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need CF + IS for dividend check.",
            )
        dividends_line = _find_line(cf_data.line_items, _DIVIDENDS_LABEL)
        ni_line = _find_subtotal(is_data.line_items, _NET_INCOME_LABEL)
        if ni_line is None:
            # Some filings don't flag NI as subtotal — fall back to a
            # non-subtotal match (less common but happens on condensed
            # interims).
            ni_line = _find_line(is_data.line_items, _NET_INCOME_LABEL)
        if dividends_line is None or ni_line is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need dividend + NI lines.",
            )
        if dividends_line.value is None or ni_line.value is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Matching lines have null values.",
            )
        primary_re: Decimal | None = None
        prior_re: Decimal | None = None
        for label in period_labels:
            bs = bs_by_period.get(label)
            if bs is None:
                continue
            re_line = _find_line(bs.line_items, _RETAINED_EARNINGS_LABEL)
            if re_line is None or re_line.value is None:
                continue
            if primary_re is None:
                primary_re = re_line.value
            else:
                prior_re = re_line.value
                break
        if primary_re is None or prior_re is None:
            return ValidationResult(
                "W.DIV", "SKIP", "Need two periods of retained_earnings.",
            )
        delta_re = primary_re - prior_re
        expected = ni_line.value - abs(dividends_line.value)
        delta = _pct_delta(delta_re, expected) if expected != 0 else Decimal("0")
        status: ValidationStatus = (
            "OK" if delta <= _DIVIDENDS_VS_RE_TOL else "WARN"
        )
        return ValidationResult(
            "W.DIV",
            status,
            (
                f"ΔRetained earnings {delta_re} vs NI − |dividends| "
                f"{expected} (Δ = {delta:.2%}; tolerance "
                f"{_DIVIDENDS_VS_RE_TOL:.1%})."
            ),
            data={
                "computed": str(expected),
                "reported": str(delta_re),
                "delta": str(delta),
            },
        )

    def _check_shares_consistency(
        self, is_data: IncomeStatementPeriod | None
    ) -> ValidationResult:
        if is_data is None or is_data.earnings_per_share is None:
            return ValidationResult(
                "W.SHARES", "SKIP", "No EPS block for shares check.",
            )
        eps = is_data.earnings_per_share
        basic = eps.basic_weighted_avg_shares
        diluted = eps.diluted_weighted_avg_shares
        if basic is None or diluted is None:
            return ValidationResult(
                "W.SHARES", "SKIP",
                "Need both basic + diluted weighted-average shares.",
            )
        if basic > diluted + Decimal("0.01"):
            return ValidationResult(
                "W.SHARES", "WARN",
                f"Basic shares {basic} > diluted {diluted} — unexpected.",
                data={"basic": str(basic), "diluted": str(diluted)},
            )
        return ValidationResult(
            "W.SHARES", "OK", f"Basic {basic} ≤ diluted {diluted}.",
        )

    def _check_yoy_sanity(self, extraction: RawExtraction) -> ValidationResult:
        labels = self._period_labels(extraction)
        if len(labels) < 2:
            return ValidationResult(
                "W.YOY", "SKIP", "Need ≥ 2 periods for YoY sanity.",
            )
        current = extraction.income_statement.get(labels[0])
        prior = extraction.income_statement.get(labels[1])
        if current is None or prior is None:
            return ValidationResult("W.YOY", "SKIP", "Missing IS for YoY.")
        current_rev = _find_line(current.line_items, _REVENUE_LABEL)
        prior_rev = _find_line(prior.line_items, _REVENUE_LABEL)
        if current_rev is None or prior_rev is None:
            return ValidationResult(
                "W.YOY", "SKIP", "Missing revenue line for YoY.",
            )
        if (
            current_rev.value is None or prior_rev.value is None
            or prior_rev.value == 0
        ):
            return ValidationResult(
                "W.YOY", "SKIP", "Revenue values missing or prior is zero.",
            )
        ratio = abs(current_rev.value) / abs(prior_rev.value)
        status: ValidationStatus = (
            "WARN" if ratio >= _YOY_GROWTH_FLAG_THRESHOLD else "OK"
        )
        return ValidationResult(
            "W.YOY",
            status,
            (
                f"YoY revenue ratio {ratio:.2f}× (flag threshold ≥ "
                f"{_YOY_GROWTH_FLAG_THRESHOLD}×)."
            ),
            data={
                "current": str(current_rev.value),
                "prior": str(prior_rev.value),
                "ratio": str(ratio),
            },
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

    def _note_present(
        self, notes: list[Note], pattern: re.Pattern[str]
    ) -> bool:
        """A note matches if its title matches the pattern AND it has
        at least one populated table or a non-empty narrative summary.
        This avoids stub notes counting toward completeness."""
        for note in notes:
            if not pattern.search(note.title):
                continue
            if note.tables:
                return True
            if note.narrative_summary and note.narrative_summary.strip():
                return True
        return False


def _group_by_section(
    items: list[LineItem],
) -> list[tuple[str | None, list[LineItem]]]:
    """Group ordered items by consecutive equal ``section`` values.

    Preserves declaration order. A ``section=None`` run is kept as
    its own group — strict BS/CF checks will walk it as a
    best-effort block.
    """
    out: list[tuple[str | None, list[LineItem]]] = []
    current_section: str | None = None
    current_items: list[LineItem] = []
    for item in items:
        if item.section != current_section and current_items:
            out.append((current_section, current_items))
            current_items = []
        current_section = item.section
        current_items.append(item)
    if current_items:
        out.append((current_section, current_items))
    return out


__all__ = [
    "ExtractionValidator",
    "ValidationReport",
    "ValidationResult",
    "ValidationStatus",
    "REQUIRED_NOTE_PATTERNS",
    "RECOMMENDED_NOTE_PATTERNS",
    "REQUIRED_NOTES_BY_PROFILE",
    "RECOMMENDED_NOTES_BY_PROFILE",
]
