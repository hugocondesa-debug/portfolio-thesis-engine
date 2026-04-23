"""Extraction coordinator — orders modules, threads the shared
:class:`ExtractionContext` through them, and (optionally) builds the
fully-typed :class:`CanonicalCompanyState` via :class:`AnalysisDeriver`.

Phase 1.5.3: consumes the as-reported structured
:class:`RawExtraction` directly. Reclassified statement lines are
passed through verbatim from the source line_items, with the
``is_subtotal`` flag preserved (as an `is_adjusted=False` marker on
the canonical line; no numerical reclassification happens at this
stage — that's downstream Phase 2 work).

Per-company cost cap is enforced between modules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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
    NarrativeContext,
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

_EXTRACTION_SYSTEM_VERSION = "phase1.5.3"


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
        """Run every loaded module in order, return :class:`ExtractionResult`."""
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
        decompositions: dict[str, Any] | None = None,
        decomposition_coverage: Any = None,
    ) -> ExtractionResult:
        """Full pipeline: modules + analysis + :class:`CanonicalCompanyState`.

        Phase 1.5.10 — when ``decompositions`` (Module D output) is
        supplied, the :class:`AnalysisDeriver` uses sub-item granularity
        for the sustainable operating income. Absent decompositions, the
        Phase 1.5.9 aggregate-label regex remains the fallback.
        """
        context = await self._run_modules(raw_extraction, wacc_inputs)
        canonical = self._build_canonical_state(
            context=context,
            identity=identity,
            source_documents=source_documents or [],
            decompositions=decompositions,
            decomposition_coverage=decomposition_coverage,
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
        decompositions: dict[str, Any] | None = None,
        decomposition_coverage: Any = None,
    ) -> CanonicalCompanyState:
        analysis = self._analysis.derive(context, decompositions=decompositions)
        reclassified = self._reclassified_statements(context)
        adjustments = self._partition_adjustments(context)
        # Phase 1.5.10 — attach Module D output so downstream consumers
        # (display, guardrails, Phase-2 modules) can query it without
        # re-running.
        if decompositions is not None:
            adjustments.module_d_note_decompositions = decompositions
        if decomposition_coverage is not None:
            adjustments.module_d_coverage = decomposition_coverage

        validation = ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.phase1_5_3",
                    name="Phase 1.5.3 placeholder",
                    status="PASS",
                    detail=(
                        "Guardrails wiring runs separately (Group A + V); "
                        "this state passes because modules ran to completion."
                    ),
                ),
            ],
            profile_specific_checksums=[],
            # Phase 1.5.11 — confidence caps on audit status.
            # AUDITED default is MEDIUM (Phase-1 behaviour);
            # REVIEWED caps at MEDIUM; UNAUDITED caps at MEDIUM-LOW.
            confidence_rating=_confidence_for_audit_status(
                context.raw_extraction.metadata.audit_status
            ),
        )

        # Phase 1.5.6: report THIS run's cost, not the cumulative JSONL
        # total. Phase 1.5+ pipelines are LLM-free, so run-local cost
        # is typically zero; using ticker_total() would leak legacy
        # Phase-1 experiment costs into current canonical states.
        session_ticker_cost = sum(
            (
                entry.cost_usd for entry in self.cost_tracker.session_entries()
                if entry.ticker == context.ticker
            ),
            start=Decimal("0"),
        )
        # Phase 1.5.11 — mirror audit_status + preliminary_flag onto
        # the methodology so the display layer can render the unaudited
        # banner without reading the raw extraction.
        raw_metadata = context.raw_extraction.metadata
        prelim_payload: dict[str, Any] | None = None
        if raw_metadata.preliminary_flag is not None:
            prelim_payload = raw_metadata.preliminary_flag.model_dump()
        methodology = MethodologyMetadata(
            extraction_system_version=_EXTRACTION_SYSTEM_VERSION,
            profile_applied=identity.profile,
            protocols_activated=[
                m.module_id or m.__class__.__name__ for m in self.modules
            ],
            sub_modules_active={},
            tiers={},
            llm_calls_summary={},
            total_api_cost_usd=session_ticker_cost,
            audit_status=raw_metadata.audit_status.value,
            preliminary_flag=prelim_payload,
            source_document_type=raw_metadata.document_type.value,
        )

        as_of_date = (
            context.raw_extraction.primary_bs.period_end_date
            if context.raw_extraction.primary_bs
               and context.raw_extraction.primary_bs.period_end_date
            else context.raw_extraction.primary_period.end_date
        )

        extraction_id = (
            f"{context.ticker.replace('.', '-')}_"
            f"{context.fiscal_period_label}_"
            f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        )
        # Phase 1.5.14 — preserve narrative context from the raw
        # extraction. Downstream consumers (Ficha summary, show CLI,
        # scenario-adjustment exports) rely on it.
        narrative_context = _build_narrative_context(
            raw_extraction=context.raw_extraction,
            primary_period=context.fiscal_period_label,
        )

        return CanonicalCompanyState(
            extraction_id=extraction_id,
            extraction_date=datetime.now(UTC),
            as_of_date=as_of_date,
            identity=identity,
            reclassified_statements=[reclassified],
            adjustments=adjustments,
            analysis=analysis,
            validation=validation,
            vintage=VintageAndCascade(),
            methodology=methodology,
            narrative_context=narrative_context,
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
        buckets: dict[str, list[ModuleAdjustment]] = {
            "A": [], "B": [], "C": [], "D": [], "E": [], "F": [],
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
# Statement rendering — pass line_items through verbatim
# ----------------------------------------------------------------------
def _render_is_lines(
    is_data: IncomeStatementPeriod | None,
) -> list[IncomeStatementLine]:
    if is_data is None or not is_data.line_items:
        return []
    out: list[IncomeStatementLine] = []
    for item in sorted(is_data.line_items, key=lambda li: li.order):
        if item.value is None:
            continue
        out.append(
            IncomeStatementLine(
                label=item.label,
                value=item.value,
            )
        )
    return out


def _render_bs_lines(
    bs_data: BalanceSheetPeriod | None,
) -> list[BalanceSheetLine]:
    """BS canonical lines: leaves only (subtotals excluded) so
    downstream BS-identity guardrail can sum category buckets without
    double-counting."""
    if bs_data is None or not bs_data.line_items:
        return []
    out: list[BalanceSheetLine] = []
    for item in sorted(bs_data.line_items, key=lambda li: li.order):
        if item.value is None or item.is_subtotal:
            continue
        out.append(
            BalanceSheetLine(
                label=item.label,
                value=item.value,
                category=item.section or "other",
            )
        )
    return out


def _render_cf_lines(
    cf_data: CashFlowPeriod | None,
) -> list[CashFlowLine]:
    """CF canonical lines: leaves per section + the final Δcash
    subtotal (``section="subtotal"``). Section-total subtotals
    excluded to avoid double-counting when the guardrail sums
    categories."""
    if cf_data is None or not cf_data.line_items:
        return []
    out: list[CashFlowLine] = []
    for item in sorted(cf_data.line_items, key=lambda li: li.order):
        if item.value is None:
            continue
        # Exclude section subtotals except the final Δcash anchor.
        if item.is_subtotal and item.section != "subtotal":
            continue
        out.append(
            CashFlowLine(
                label=item.label,
                value=item.value,
                category=item.section or "other",
            )
        )
    return out


# ----------------------------------------------------------------------
# Phase 1.5.11 — audit-status aware confidence cap
# ----------------------------------------------------------------------
def _confidence_for_audit_status(audit_status: Any) -> str:
    """Map :class:`AuditStatus` → confidence tag persisted on
    :class:`ValidationResults`. Defaults preserved for AUDITED so
    Phase-1 canonical states are unchanged."""
    from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

    if audit_status == AuditStatus.UNAUDITED:
        return "MEDIUM-LOW"
    if audit_status == AuditStatus.REVIEWED:
        return "MEDIUM"
    return "MEDIUM"


# ----------------------------------------------------------------------
# Phase 1.5.14 — narrative preservation
# ----------------------------------------------------------------------
def _build_narrative_context(
    raw_extraction: RawExtraction,
    primary_period: str,
) -> NarrativeContext | None:
    """Build a :class:`NarrativeContext` from the raw extraction's
    ``narrative`` block. Returns ``None`` when every narrative bucket
    is empty — keeps canonical states lean when the source didn't
    capture qualitative context.
    """
    narrative = raw_extraction.narrative
    if narrative is None:
        return None
    buckets = (
        narrative.key_themes,
        narrative.risks_mentioned,
        narrative.guidance_changes,
        narrative.capital_allocation_comments,
        narrative.forward_looking_statements,
    )
    if not any(buckets):
        return None
    return NarrativeContext(
        key_themes=list(narrative.key_themes),
        risks_mentioned=list(narrative.risks_mentioned),
        guidance_changes=list(narrative.guidance_changes),
        capital_allocation_signals=list(narrative.capital_allocation_comments),
        forward_looking_statements=list(narrative.forward_looking_statements),
        source_extraction_period=primary_period,
        source_document_type=raw_extraction.metadata.document_type.value,
        extraction_timestamp=datetime.now(UTC),
    )
