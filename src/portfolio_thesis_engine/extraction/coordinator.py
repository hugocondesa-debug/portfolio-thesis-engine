"""Extraction coordinator — orders modules and threads the shared
:class:`ExtractionContext` through them.

Phase 1 / Sprint 6 loads Modules A and B for P1 Industrial. Sprint 7
extends ``_load_modules_for_profile`` with Module C (leases) and wires
the :class:`AnalysisDeriver` at the end of :meth:`extract`.

Per-company cost cap is enforced **between** modules (once per module,
not per call). Modules themselves are free to make LLM calls — each one
records its spend via the shared :class:`CostTracker`.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    ExtractionModule,
    ExtractionResult,
    parse_fiscal_period,
)
from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes
from portfolio_thesis_engine.extraction.module_b_provisions import ModuleBProvisions
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult as SectionExtractionResult,
)
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError


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
        # ``modules`` explicit override is there for tests and for Sprint
        # 7 when we extend the list; when absent, profile decides.
        self.modules = modules if modules is not None else self._load_modules_for_profile()

    # ------------------------------------------------------------------
    def _load_modules_for_profile(self) -> list[ExtractionModule]:
        if self.profile == Profile.P1_INDUSTRIAL:
            return [
                ModuleATaxes(self.llm, self.cost_tracker),
                ModuleBProvisions(self.llm, self.cost_tracker),
                # Module C (leases) lands in Sprint 7.
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

        Raises :class:`CostLimitExceededError` if the per-company cost
        cap is reached between modules. Individual module failures bubble
        up — callers decide whether to continue or abort.
        """
        primary_period = parse_fiscal_period(section_result.fiscal_period)
        context = ExtractionContext(
            ticker=section_result.ticker,
            fiscal_period_label=section_result.fiscal_period,
            primary_period=primary_period,
            sections=list(section_result.sections),
            wacc_inputs=wacc_inputs,
        )

        modules_run: list[str] = []
        for module in self.modules:
            self._enforce_cost_cap(
                ticker=context.ticker,
                stage=f"extraction_module_{module.module_id or module.__class__.__name__}",
            )
            context = await module.apply(context)
            modules_run.append(module.module_id or module.__class__.__name__)

        return ExtractionResult(
            ticker=context.ticker,
            fiscal_period_label=context.fiscal_period_label,
            primary_period=context.primary_period,
            adjustments=list(context.adjustments),
            decision_log=list(context.decision_log),
            estimates_log=list(context.estimates_log),
            modules_run=modules_run,
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
