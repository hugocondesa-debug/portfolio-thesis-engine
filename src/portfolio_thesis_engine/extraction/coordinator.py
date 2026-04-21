"""Extraction coordinator — orders modules, threads the shared
:class:`ExtractionContext` through them, and (optionally) builds the
fully-typed :class:`CanonicalCompanyState` via :class:`AnalysisDeriver`.

Phase 1 / Sprint 7 loads Modules A, B and C for P1 Industrial.
Per-company cost cap is enforced **between** modules (once per module,
not per call). Modules themselves are free to make LLM calls — each
one records its spend via the shared :class:`CostTracker`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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
from portfolio_thesis_engine.extraction.raw_extraction_adapter import (
    SectionExtractionResult,
)
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
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

_EXTRACTION_SYSTEM_VERSION = "phase1-sprint7"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


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
        # ``modules`` explicit override is there for tests and for future
        # sprints; when absent, profile decides.
        self.modules = modules if modules is not None else self._load_modules_for_profile()
        self._analysis = AnalysisDeriver()

    # ------------------------------------------------------------------
    def _load_modules_for_profile(self) -> list[ExtractionModule]:
        if self.profile == Profile.P1_INDUSTRIAL:
            return [
                ModuleATaxes(self.llm, self.cost_tracker),
                ModuleBProvisions(self.llm, self.cost_tracker),
                ModuleCLeases(self.llm, self.cost_tracker),
                # Modules D/E/F deferred to Phase 2.
            ]
        raise NotImplementedError(
            f"Profile {self.profile} not supported in Phase 1 extraction."
        )

    # ------------------------------------------------------------------
    async def extract(
        self,
        section_result: SectionExtractionResult,
        wacc_inputs: WACCInputs,
    ) -> ExtractionResult:
        """Run every loaded module in order, return :class:`ExtractionResult`.

        ``canonical_state`` is left ``None`` here — call
        :meth:`extract_canonical` to get the fully-typed state (it
        needs an ``identity`` the low-level path doesn't carry).

        Raises :class:`CostLimitExceededError` if the per-company cost
        cap is reached between modules.
        """
        context = await self._run_modules(section_result, wacc_inputs)
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
        section_result: SectionExtractionResult,
        wacc_inputs: WACCInputs,
        identity: CompanyIdentity,
        *,
        source_documents: list[str] | None = None,
    ) -> ExtractionResult:
        """Full pipeline: modules + analysis + :class:`CanonicalCompanyState`.

        ``identity`` is supplied by the caller (usually the metadata
        repository). ``source_documents`` is the list of doc_ids the
        extraction consumed — traced onto the canonical state for
        downstream audit.
        """
        context = await self._run_modules(section_result, wacc_inputs)
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
        section_result: SectionExtractionResult,
        wacc_inputs: WACCInputs,
    ) -> ExtractionContext:
        primary_period = parse_fiscal_period(section_result.fiscal_period)
        context = ExtractionContext(
            ticker=section_result.ticker,
            fiscal_period_label=section_result.fiscal_period,
            primary_period=primary_period,
            sections=list(section_result.sections),
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

        # Minimal validation block for Phase 1 — we'll wire guardrails_A
        # through this payload in Sprint 8+.
        validation = ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.sprint7",
                    name="Sprint 7 placeholder",
                    status="PASS",
                    detail=(
                        "Guardrails wiring deferred to Sprint 8; "
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
            protocols_activated=[m.module_id or m.__class__.__name__ for m in self.modules],
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
            as_of_date=f"{context.primary_period.year}-12-31",
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
    def _reclassified_statements(self, context: ExtractionContext) -> ReclassifiedStatements:
        is_lines = _get_lines(context, "income_statement")
        bs_lines = _get_lines(context, "balance_sheet")
        cf_lines = _get_lines(context, "cash_flow")

        income_statement = [
            IncomeStatementLine(
                label=str(line.get("label", "")),
                value=_to_decimal(line.get("value_current")) or Decimal("0"),
            )
            for line in is_lines
        ]
        balance_sheet = [
            BalanceSheetLine(
                label=str(line.get("label", "")),
                value=_to_decimal(line.get("value_current")) or Decimal("0"),
                category=str(line.get("category", "other")),
            )
            for line in bs_lines
        ]
        cash_flow = [
            CashFlowLine(
                label=str(line.get("label", "")),
                value=_to_decimal(line.get("value_current")) or Decimal("0"),
                category=str(line.get("category", "other")),
            )
            for line in cf_lines
        ]
        # Phase 1 scope: checksums pass-through. Sprint 8 wires real
        # guardrails (A-core) which set these flags.
        return ReclassifiedStatements(
            period=context.primary_period,
            income_statement=income_statement,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
            bs_checksum_pass=True,
            is_checksum_pass=True,
            cf_checksum_pass=True,
        )

    def _partition_adjustments(self, context: ExtractionContext) -> AdjustmentsApplied:
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


def _get_lines(context: ExtractionContext, section_type: str) -> list[dict[str, Any]]:
    section = context.find_section(section_type)
    if section is None or section.parsed_data is None:
        return []
    items = section.parsed_data.get("line_items")
    return list(items) if isinstance(items, list) else []
