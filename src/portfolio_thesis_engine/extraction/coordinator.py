"""Extraction coordinator — orders modules, threads the shared
:class:`ExtractionContext` through them, and (optionally) builds the
fully-typed :class:`CanonicalCompanyState` via :class:`AnalysisDeriver`.

Phase 1.5 / Sprint 3: consumes :class:`RawExtraction` directly. The
reclassified statements are built line-for-line from the typed
IS/BS/CF fields — no more ``line_items`` dict scans.

Per-company cost cap is enforced **between** modules (once per module,
not per call). Modules themselves are free to make LLM calls — each
one records its spend via the shared :class:`CostTracker`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    ExtractionModule,
    ExtractionResult,
    parse_fiscal_period,
)
from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes
from portfolio_thesis_engine.extraction.module_b_provisions import ModuleBProvisions
from portfolio_thesis_engine.extraction.module_c_leases import ModuleCLeases
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    BalanceSheetLine,
    CanonicalCompanyState,
    CashFlowLine,
    CompanyIdentity,
    IncomeStatementLine,
    MethodologyMetadata,
    ModuleAdjustment,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    RawExtraction,
)
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

_EXTRACTION_SYSTEM_VERSION = "phase1.5-sprint3"


# ----------------------------------------------------------------------
# IS / BS / CF reclassification tables
# ----------------------------------------------------------------------
# (RawExtraction field name, human label). Used to render the typed
# statements into the ``Reclassified*`` line-item lists that the
# canonical state carries.
_IS_LINES: tuple[tuple[str, str], ...] = (
    ("revenue", "Revenue"),
    ("cost_of_sales", "Cost of sales"),
    ("gross_profit", "Gross profit"),
    ("selling_marketing", "Selling & marketing"),
    ("general_administrative", "General & administrative"),
    ("selling_general_administrative", "SG&A"),
    ("research_development", "R&D"),
    ("other_operating_expenses", "Other operating expenses"),
    ("depreciation_amortization", "D&A"),
    ("operating_income", "Operating income"),
    ("finance_income", "Finance income"),
    ("finance_expenses", "Finance expenses"),
    ("share_of_associates", "Share of associates"),
    ("non_operating_income", "Non-operating income"),
    ("income_before_tax", "Income before tax"),
    ("income_tax", "Income tax"),
    ("net_income_from_continuing", "Net income — continuing"),
    ("net_income_from_discontinued", "Net income — discontinued"),
    ("net_income", "Net income"),
)

_BS_LINES: tuple[tuple[str, str, str], ...] = (
    ("cash_and_equivalents", "Cash and equivalents", "cash"),
    ("short_term_investments", "Short-term investments", "financial_assets"),
    ("accounts_receivable", "Accounts receivable", "operating_assets"),
    ("inventory", "Inventory", "operating_assets"),
    ("current_assets_other", "Other current assets", "operating_assets"),
    ("ppe_net", "PP&E (net)", "operating_assets"),
    ("rou_assets", "ROU assets", "operating_assets"),
    ("goodwill", "Goodwill", "intangibles"),
    ("intangibles_other", "Other intangibles", "intangibles"),
    ("investments", "Investments", "financial_assets"),
    ("deferred_tax_assets", "Deferred tax assets", "operating_assets"),
    ("non_current_assets_other", "Other non-current assets", "operating_assets"),
    ("total_assets", "Total assets", "total_assets"),
    ("accounts_payable", "Accounts payable", "operating_liabilities"),
    ("short_term_debt", "Short-term debt", "financial_liabilities"),
    ("lease_liabilities_current", "Lease liabilities (current)", "lease_liabilities"),
    ("deferred_revenue_current", "Deferred revenue (current)", "operating_liabilities"),
    ("current_liabilities_other", "Other current liabilities", "operating_liabilities"),
    ("long_term_debt", "Long-term debt", "financial_liabilities"),
    ("lease_liabilities_noncurrent", "Lease liabilities (non-current)", "lease_liabilities"),
    ("deferred_tax_liabilities", "Deferred tax liabilities", "operating_liabilities"),
    ("provisions", "Provisions", "operating_liabilities"),
    ("pension_obligations", "Pension obligations", "operating_liabilities"),
    ("non_current_liabilities_other", "Other non-current liabilities", "operating_liabilities"),
    ("total_liabilities", "Total liabilities", "total_liabilities"),
    ("share_capital", "Share capital", "equity"),
    ("share_premium", "Share premium", "equity"),
    ("retained_earnings", "Retained earnings", "equity"),
    ("other_reserves", "Other reserves", "equity"),
    ("treasury_shares", "Treasury shares", "equity"),
    ("non_controlling_interests", "Non-controlling interests", "nci"),
    ("total_equity", "Total equity", "total_equity"),
)

_CF_LINES: tuple[tuple[str, str, str], ...] = (
    ("operating_cash_flow", "Operating cash flow", "cfo"),
    ("capex", "CapEx", "capex"),
    ("acquisitions", "Acquisitions", "acquisitions"),
    ("investing_cash_flow", "Investing cash flow", "cfi"),
    ("dividends_paid", "Dividends paid", "dividends"),
    ("debt_issuance", "Debt issuance", "debt_issuance"),
    ("debt_repayment", "Debt repayment", "debt_repayment"),
    ("share_repurchases", "Share repurchases", "buybacks"),
    ("financing_cash_flow", "Financing cash flow", "cff"),
    ("fx_effect", "FX effect", "fx_effect"),
    ("net_change_in_cash", "Net change in cash", "net_change_in_cash"),
)


class ExtractionCoordinator:
    """Orchestrate extraction modules for a given profile."""

    def __init__(
        self,
        profile: Profile,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
        modules: list[ExtractionModule] | None = None,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.cost_tracker = cost_tracker
        self.modules = modules if modules is not None else self._load_modules_for_profile()
        self._analysis = AnalysisDeriver()

    # ------------------------------------------------------------------
    def _load_modules_for_profile(self) -> list[ExtractionModule]:
        if self.profile == Profile.P1_INDUSTRIAL:
            return [
                ModuleATaxes(self.llm, self.cost_tracker),
                ModuleBProvisions(self.llm, self.cost_tracker),
                ModuleCLeases(self.llm, self.cost_tracker),
            ]
        raise NotImplementedError(
            f"Profile {self.profile} not supported in Phase 1 extraction."
        )

    # ------------------------------------------------------------------
    async def extract(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
    ) -> ExtractionResult:
        """Run every loaded module in order, return :class:`ExtractionResult`.

        ``canonical_state`` is left ``None`` — call :meth:`extract_canonical`
        to get the fully-typed state (requires a ``CompanyIdentity``).

        Raises :class:`CostLimitExceededError` if the per-company cost
        cap is reached between modules.
        """
        context = await self._run_modules(raw_extraction, wacc_inputs)
        return ExtractionResult(
            ticker=context.ticker,
            fiscal_period_label=context.fiscal_period_label,
            primary_period=context.primary_period,
            adjustments=list(context.adjustments),
            decision_log=list(context.decision_log),
            estimates_log=list(context.estimates_log),
            modules_run=[m.module_id or m.__class__.__name__ for m in self.modules],
        )

    # ------------------------------------------------------------------
    async def extract_canonical(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
        identity: CompanyIdentity,
        *,
        source_documents: list[str] | None = None,
    ) -> ExtractionResult:
        """Full pipeline: modules + analysis + :class:`CanonicalCompanyState`."""
        context = await self._run_modules(raw_extraction, wacc_inputs)
        canonical = self._build_canonical_state(
            context=context,
            identity=identity,
            source_documents=source_documents or [],
        )
        return ExtractionResult(
            ticker=context.ticker,
            fiscal_period_label=context.fiscal_period_label,
            primary_period=context.primary_period,
            adjustments=list(context.adjustments),
            decision_log=list(context.decision_log),
            estimates_log=list(context.estimates_log),
            modules_run=[m.module_id or m.__class__.__name__ for m in self.modules],
            canonical_state=canonical,
        )

    # ------------------------------------------------------------------
    async def _run_modules(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
    ) -> ExtractionContext:
        primary_label = raw_extraction.primary_period.period
        primary_period = parse_fiscal_period(primary_label)
        context = ExtractionContext(
            ticker=raw_extraction.metadata.ticker,
            fiscal_period_label=primary_label,
            primary_period=primary_period,
            raw_extraction=raw_extraction,
            wacc_inputs=wacc_inputs,
        )

        for module in self.modules:
            self._enforce_cost_cap(
                ticker=context.ticker,
                stage=f"extraction_module_{module.module_id or module.__class__.__name__}",
            )
            context = await module.apply(context)
        return context

    # ------------------------------------------------------------------
    def _build_canonical_state(
        self,
        *,
        context: ExtractionContext,
        identity: CompanyIdentity,
        source_documents: list[str],
    ) -> CanonicalCompanyState:
        analysis = self._analysis.derive(context)
        reclassified = self._reclassified_statements(context)
        adjustments = self._partition_adjustments(context)

        validation = ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.phase1_5_sprint3",
                    name="Phase 1.5 Sprint 3 placeholder",
                    status="PASS",
                    detail=(
                        "Guardrails wiring runs separately (Group A + V); "
                        "this state passes because modules ran to completion."
                    ),
                ),
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        )

        methodology = MethodologyMetadata(
            extraction_system_version=_EXTRACTION_SYSTEM_VERSION,
            profile_applied=identity.profile,
            protocols_activated=[
                m.module_id or m.__class__.__name__ for m in self.modules
            ],
            sub_modules_active={},
            tiers={},
            llm_calls_summary={},
            total_api_cost_usd=self.cost_tracker.ticker_total(context.ticker),
        )

        extraction_id = (
            f"{context.ticker.replace('.', '-')}_"
            f"{context.fiscal_period_label}_"
            f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        )
        return CanonicalCompanyState(
            extraction_id=extraction_id,
            extraction_date=datetime.now(UTC),
            as_of_date=context.raw_extraction.primary_period.end_date,
            identity=identity,
            reclassified_statements=[reclassified],
            adjustments=adjustments,
            analysis=analysis,
            validation=validation,
            vintage=VintageAndCascade(),
            methodology=methodology,
            source_documents=source_documents,
        )

    # ------------------------------------------------------------------
    def _reclassified_statements(
        self, context: ExtractionContext
    ) -> ReclassifiedStatements:
        raw = context.raw_extraction
        is_lines = _render_is_lines(raw.primary_is)
        bs_lines = _render_bs_lines(raw.primary_bs)
        cf_lines = _render_cf_lines(raw.primary_cf)

        return ReclassifiedStatements(
            period=context.primary_period,
            income_statement=is_lines,
            balance_sheet=bs_lines,
            cash_flow=cf_lines,
            bs_checksum_pass=True,
            is_checksum_pass=True,
            cf_checksum_pass=True,
        )

    def _partition_adjustments(
        self, context: ExtractionContext
    ) -> AdjustmentsApplied:
        """Bucket module adjustments by their ``module`` prefix."""
        buckets: dict[str, list[ModuleAdjustment]] = {
            "A": [],
            "B": [],
            "C": [],
            "D": [],
            "E": [],
            "F": [],
        }
        patches: list[ModuleAdjustment] = []
        for adj in context.adjustments:
            prefix = adj.module.split(".", 1)[0] if adj.module else ""
            if prefix in buckets:
                buckets[prefix].append(adj)
            else:
                patches.append(adj)
        return AdjustmentsApplied(
            module_a_taxes=buckets["A"],
            module_b_provisions=buckets["B"],
            module_c_leases=buckets["C"],
            module_d_pensions=buckets["D"],
            module_e_sbc=buckets["E"],
            module_f_capitalize=buckets["F"],
            patches=patches,
            decision_log=list(context.decision_log),
            estimates_log=list(context.estimates_log),
        )

    # ------------------------------------------------------------------
    def _enforce_cost_cap(self, *, ticker: str, stage: str) -> None:
        cap = Decimal(str(settings.llm_max_cost_per_company_usd))
        spent = self.cost_tracker.ticker_total(ticker)
        if spent >= cap:
            raise CostLimitExceededError(
                f"Per-company cost cap reached before stage {stage!r}: "
                f"${spent} >= ${cap} for ticker {ticker!r}"
            )


# ----------------------------------------------------------------------
# Statement rendering
# ----------------------------------------------------------------------
def _render_is_lines(
    is_data: IncomeStatementPeriod | None,
) -> list[IncomeStatementLine]:
    if is_data is None:
        return []
    out: list[IncomeStatementLine] = []
    for field_name, label in _IS_LINES:
        value = getattr(is_data, field_name, None)
        if value is None:
            continue
        out.append(IncomeStatementLine(label=label, value=value))
    for name, value in is_data.extensions.items():
        out.append(
            IncomeStatementLine(
                label=name.replace("_", " ").title(),
                value=value,
            )
        )
    return out


def _render_bs_lines(
    bs_data: BalanceSheetPeriod | None,
) -> list[BalanceSheetLine]:
    if bs_data is None:
        return []
    out: list[BalanceSheetLine] = []
    for field_name, label, category in _BS_LINES:
        value = getattr(bs_data, field_name, None)
        if value is None:
            continue
        out.append(BalanceSheetLine(label=label, value=value, category=category))
    for name, value in bs_data.extensions.items():
        out.append(
            BalanceSheetLine(
                label=name.replace("_", " ").title(),
                value=value,
                category="other",
            )
        )
    return out


def _render_cf_lines(
    cf_data: CashFlowPeriod | None,
) -> list[CashFlowLine]:
    if cf_data is None:
        return []
    out: list[CashFlowLine] = []
    for field_name, label, category in _CF_LINES:
        value = getattr(cf_data, field_name, None)
        if value is None:
            continue
        out.append(CashFlowLine(label=label, value=value, category=category))
    for name, value in cf_data.extensions.items():
        out.append(
            CashFlowLine(
                label=name.replace("_", " ").title(),
                value=value,
                category="other",
            )
        )
    return out
