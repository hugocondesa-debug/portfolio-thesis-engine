"""PipelineCoordinator — run the full Phase 1.5 pipeline for one ticker.

Stages run in order:

1. **CHECK_INGESTION** — documents must exist in the
   :class:`DocumentRepository` for the ticker (e.g., ``wacc_inputs.md``
   + ``raw_extraction.yaml``).
2. **LOAD_WACC** — parse ``wacc_inputs.md`` → :class:`WACCInputs`.
3. **LOAD_EXTRACTION** — parse ``raw_extraction.yaml`` → normalised
   :class:`RawExtraction`. Replaces Phase 1's LLM-driven section
   extractor; extraction now happens outside the app via Claude.ai.
4. **VALIDATE_EXTRACTION** — run :class:`ExtractionValidator` strict +
   warn + completeness. A strict FAIL raises
   :class:`ExtractionValidationBlocked`; warn + completeness are
   reported on the run log but don't halt.
5. **CROSS_CHECK** — run :class:`CrossCheckGate` over the extracted
   top-level values (revenue, NI, assets, etc.). FAIL blocks the
   pipeline unless ``skip_cross_check=True``.
6. **EXTRACT_CANONICAL** — run
   :class:`ExtractionCoordinator.extract_canonical` on the
   :class:`RawExtraction` directly (Phase 1.5 Sprint 3 removed the
   Sprint-2 adapter shim).
7. **PERSIST** — save the canonical state via :class:`CompanyStateRepository`.
8. **GUARDRAILS** — run Group A + V guardrails.
9. **VALUATE** — compose three scenarios + DCF per scenario + equity
   bridge + IRR, then the final :class:`ValuationSnapshot`. Skipped
   if :attr:`PipelineCoordinator.valuation_repo` is ``None``.
10. **PERSIST_VALUATION** — save the snapshot via :class:`ValuationRepository`.
11. **COMPOSE_FICHA** — aggregate view (:class:`Ficha`) built from the
    canonical state + valuation snapshot and persisted via
    :class:`CompanyRepository`. Skipped when ``ficha_composer`` +
    ``company_repo`` aren't both injected.

Flags:

- ``force`` — bypass cached-stage checks (forces re-extraction).
- ``skip_cross_check`` — bypass the cross-check gate entirely; logs a
  loud warning so the audit trail still shows it was bypassed.
- ``force_cost_override`` — temporarily raise the per-company cost
  cap to 10 000 USD for this run. Emergency use only.

The coordinator accepts fully-formed service instances via
``__init__`` so tests can inject mocks; the CLI builds a default
wiring in :mod:`cli.process_cmd`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any

from portfolio_thesis_engine.cross_check.base import CrossCheckReport, CrossCheckStatus
from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.ficha.composer import FichaComposer
from portfolio_thesis_engine.guardrails.checks import default_guardrails
from portfolio_thesis_engine.guardrails.results import AggregatedResults, ResultAggregator
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.ingestion.raw_extraction_parser import parse_raw_extraction
from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
    ExtractionValidator,
    ValidationReport,
)
from portfolio_thesis_engine.ingestion.wacc_parser import parse_wacc_inputs
from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    MarketDataProvider,
    TickerNotFoundError,
)
from portfolio_thesis_engine.schemas.common import Currency, GuardrailStatus, Profile
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState, CompanyIdentity
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction
from portfolio_thesis_engine.schemas.valuation import MarketSnapshot, ValuationSnapshot
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import PTEError
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import CompanyRow, MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)
from portfolio_thesis_engine.valuation.composer import ValuationComposer
from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

_COST_OVERRIDE_CAP_USD = 10_000.0


class PipelineStage(StrEnum):
    CHECK_INGESTION = "check_ingestion"
    LOAD_WACC = "load_wacc"
    LOAD_EXTRACTION = "load_extraction"
    VALIDATE_EXTRACTION = "validate_extraction"
    CROSS_CHECK = "cross_check"
    EXTRACT_CANONICAL = "extract_canonical"
    PERSIST = "persist"
    GUARDRAILS = "guardrails"
    VALUATE = "valuate"
    PERSIST_VALUATION = "persist_valuation"
    COMPOSE_FICHA = "compose_ficha"


class PipelineError(PTEError):
    """Raised when a pipeline stage fails in a way the caller should
    surface verbatim (e.g., no ingested documents)."""


class CrossCheckBlocked(PipelineError):
    """Raised when the cross-check gate returns a blocking verdict and
    ``skip_cross_check`` is False."""


class ExtractionValidationBlocked(PipelineError):
    """Raised when :meth:`ExtractionValidator.validate_strict` returns
    a FAIL verdict. Pipeline halts so the operator can fix the raw
    extraction before retrying (analogous to cross-check blocking)."""


@dataclass
class StageOutcome:
    """One row in the pipeline run log."""

    stage: PipelineStage
    status: str  # "ok" | "skip" | "fail"
    duration_ms: int
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineOutcome:
    """Final product of :meth:`PipelineCoordinator.process`."""

    ticker: str
    started_at: datetime
    finished_at: datetime
    success: bool
    stages: list[StageOutcome]
    raw_extraction: RawExtraction | None = None
    extraction_validation_strict: ValidationReport | None = None
    extraction_validation_warn: ValidationReport | None = None
    extraction_validation_completeness: ValidationReport | None = None
    cross_check_report: CrossCheckReport | None = None
    canonical_state: CanonicalCompanyState | None = None
    guardrails: AggregatedResults | None = None
    valuation_snapshot: ValuationSnapshot | None = None
    ficha: Ficha | None = None
    log_path: Path | None = None

    @property
    def overall_guardrail_status(self) -> GuardrailStatus:
        if self.guardrails is None:
            return GuardrailStatus.SKIP
        return self.guardrails.overall


# ----------------------------------------------------------------------
# Helpers for extracting top-level values for the cross-check gate
# ----------------------------------------------------------------------
def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _extract_cross_check_values(
    raw_extraction: RawExtraction,
) -> dict[str, Decimal]:
    """Pull top-level values (revenue, NI, total assets, etc.) from the
    :class:`RawExtraction` so the gate can compare against FMP / yfinance."""
    values: dict[str, Decimal] = {}

    is_data = raw_extraction.primary_is
    if is_data is not None:
        if is_data.revenue is not None:
            values["revenue"] = is_data.revenue
        if is_data.operating_income is not None:
            values["operating_income"] = is_data.operating_income
        if is_data.net_income is not None:
            values["net_income"] = is_data.net_income

    bs_data = raw_extraction.primary_bs
    if bs_data is not None:
        if bs_data.cash_and_equivalents is not None:
            values["cash"] = bs_data.cash_and_equivalents
        if bs_data.total_assets is not None:
            values["total_assets"] = bs_data.total_assets
        if bs_data.total_equity is not None:
            values["total_equity"] = bs_data.total_equity

    cf_data = raw_extraction.primary_cf
    if cf_data is not None:
        if cf_data.operating_cash_flow is not None:
            values["operating_cash_flow"] = cf_data.operating_cash_flow
        if cf_data.capex is not None:
            values["capex"] = cf_data.capex

    return values


def _identity_from(
    company_row: CompanyRow | None,
    wacc_inputs: WACCInputs,
    raw_extraction: RawExtraction,
) -> CompanyIdentity:
    """Build a :class:`CompanyIdentity` from the SQLite row + WACC +
    raw extraction metadata. Kept lenient so ``pte process`` works on
    thin metadata."""
    reporting_currency = raw_extraction.metadata.reporting_currency
    if company_row is not None:
        with suppress(ValueError):
            reporting_currency = Currency(company_row.currency)

    return CompanyIdentity(
        ticker=wacc_inputs.ticker,
        name=(
            company_row.name
            if company_row
            else raw_extraction.metadata.company_name
        ),
        reporting_currency=reporting_currency,
        profile=Profile(wacc_inputs.profile),
        fiscal_year_end_month=12,
        country_domicile=(
            company_row.exchange if company_row and company_row.exchange != "?" else "XX"
        ),
        exchange=(
            company_row.exchange if company_row and company_row.exchange != "?" else "—"
        ),
    )


@contextmanager
def _temporary_cost_cap(cap_usd: float) -> Iterator[None]:
    """Temporarily raise ``settings.llm_max_cost_per_company_usd``."""
    original = settings.llm_max_cost_per_company_usd
    settings.llm_max_cost_per_company_usd = cap_usd
    try:
        yield
    finally:
        settings.llm_max_cost_per_company_usd = original


# ----------------------------------------------------------------------
# Coordinator
# ----------------------------------------------------------------------
class PipelineCoordinator:
    """Run the full Phase 1 pipeline end-to-end."""

    def __init__(
        self,
        document_repo: DocumentRepository,
        metadata_repo: MetadataRepository,
        cross_check_gate: CrossCheckGate,
        extraction_coordinator: ExtractionCoordinator,
        state_repo: CompanyStateRepository,
        runs_log_dir: Path | None = None,
        *,
        extraction_validator: ExtractionValidator | None = None,
        valuation_composer: ValuationComposer | None = None,
        scenario_composer: ScenarioComposer | None = None,
        valuation_repo: ValuationRepository | None = None,
        market_data_provider: MarketDataProvider | None = None,
        ficha_composer: FichaComposer | None = None,
        company_repo: CompanyRepository | None = None,
    ) -> None:
        self.document_repo = document_repo
        self.metadata_repo = metadata_repo
        self.cross_check_gate = cross_check_gate
        self.extraction_coordinator = extraction_coordinator
        self.state_repo = state_repo
        self.runs_log_dir = runs_log_dir or (settings.data_dir / "logs" / "runs")
        # Phase 1.5: validator is always-on (block on strict FAIL).
        # Defaulted for convenience so existing tests can skip plumbing.
        self.extraction_validator = extraction_validator or ExtractionValidator()
        # Valuation wiring — optional so tests that don't care about
        # Sprint 9 can skip plumbing a full market-data stack. When any
        # of (composer, scenarios, repo, market_data) is missing, the
        # pipeline SKIPs the VALUATE + PERSIST_VALUATION stages.
        self.valuation_composer = valuation_composer
        self.scenario_composer = scenario_composer
        self.valuation_repo = valuation_repo
        self.market_data_provider = market_data_provider
        # Ficha wiring — Sprint 10. SKIPs if either is absent.
        self.ficha_composer = ficha_composer
        self.company_repo = company_repo

    # ------------------------------------------------------------------
    async def process(
        self,
        ticker: str,
        *,
        wacc_path: Path,
        extraction_path: Path,
        force: bool = False,
        skip_cross_check: bool = False,
        force_cost_override: bool = False,
    ) -> PipelineOutcome:
        """Run every stage and return the aggregate :class:`PipelineOutcome`.

        Raises :class:`PipelineError` when a stage fails in a way the
        caller should surface directly (missing documents, unparseable
        WACC, unparseable raw extraction). Raises
        :class:`ExtractionValidationBlocked` when strict validation
        FAILs. Cross-check FAIL raises :class:`CrossCheckBlocked` when
        ``skip_cross_check=False``.
        """
        started = datetime.now(UTC)
        outcome = PipelineOutcome(
            ticker=ticker,
            started_at=started,
            finished_at=started,
            success=False,
            stages=[],
        )

        if force_cost_override:
            cap_ctx = _temporary_cost_cap(_COST_OVERRIDE_CAP_USD)
        else:
            cap_ctx = _null_ctx()

        with cap_ctx:
            try:
                # Stage 1 — ingestion check
                self._stage_check_ingestion(ticker, outcome, force=force)

                # Stage 2 — WACC
                wacc_inputs = self._stage_load_wacc(wacc_path, outcome)

                # Stage 3 — load raw_extraction.yaml (parse + normalise units)
                raw_extraction = self._stage_load_extraction(extraction_path, outcome)
                outcome.raw_extraction = raw_extraction

                # Stage 4 — validate the extraction (strict / warn / completeness).
                # Strict FAIL blocks; warn + completeness surfaced in the log.
                self._stage_validate_extraction(
                    raw_extraction=raw_extraction,
                    wacc_inputs=wacc_inputs,
                    outcome=outcome,
                )

                # Stage 5 — cross-check (consumes raw_extraction directly)
                cross_check_report = await self._stage_cross_check(
                    ticker=ticker,
                    raw_extraction=raw_extraction,
                    outcome=outcome,
                    skip_cross_check=skip_cross_check,
                )
                outcome.cross_check_report = cross_check_report

                # Stage 6 — extract canonical
                company_row = self.metadata_repo.get_company(ticker)
                identity = _identity_from(company_row, wacc_inputs, raw_extraction)
                canonical = await self._stage_extract_canonical(
                    raw_extraction=raw_extraction,
                    wacc_inputs=wacc_inputs,
                    identity=identity,
                    outcome=outcome,
                )
                outcome.canonical_state = canonical

                # Stage 6 — persist
                self._stage_persist(canonical, outcome)

                # Stage 7 — guardrails
                agg = self._stage_guardrails(
                    canonical=canonical,
                    cross_check_report=cross_check_report,
                    wacc_inputs=wacc_inputs,
                    outcome=outcome,
                )
                outcome.guardrails = agg

                # Stage 8 — valuation (SKIP when wiring isn't provided).
                snapshot = await self._stage_valuate(
                    canonical=canonical,
                    wacc_inputs=wacc_inputs,
                    outcome=outcome,
                )
                outcome.valuation_snapshot = snapshot

                # Stage 9 — persist valuation
                self._stage_persist_valuation(snapshot, outcome)

                # Stage 10 — compose ficha (SKIPs when ficha wiring absent).
                ficha = self._stage_compose_ficha(
                    canonical=canonical,
                    snapshot=snapshot,
                    outcome=outcome,
                )
                outcome.ficha = ficha

                outcome.success = agg.overall not in (GuardrailStatus.FAIL,)
            except PipelineError:
                outcome.success = False
                raise
            except Exception as e:
                outcome.stages.append(
                    StageOutcome(
                        stage=PipelineStage.GUARDRAILS,
                        status="fail",
                        duration_ms=0,
                        message=f"unhandled {type(e).__name__}: {e}",
                    )
                )
                outcome.success = False
                raise
            finally:
                outcome.finished_at = datetime.now(UTC)
                outcome.log_path = self._persist_run_log(outcome)

        return outcome

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------
    def _stage_check_ingestion(
        self, ticker: str, outcome: PipelineOutcome, *, force: bool
    ) -> list[Path]:
        t0 = perf_counter()
        docs = self.document_repo.list_documents(ticker)
        if not docs:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.CHECK_INGESTION,
                    status="fail",
                    duration_ms=_ms_since(t0),
                    message=(
                        f"No documents ingested for {ticker!r}. "
                        "Run 'pte ingest' first."
                    ),
                )
            )
            raise PipelineError(
                f"No documents ingested for {ticker!r}. Run 'pte ingest' first."
            )
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.CHECK_INGESTION,
                status="ok",
                duration_ms=_ms_since(t0),
                message=f"{len(docs)} document(s) found.",
                data={"count": len(docs), "force": force},
            )
        )
        return docs

    def _stage_load_wacc(self, wacc_path: Path, outcome: PipelineOutcome) -> WACCInputs:
        t0 = perf_counter()
        try:
            wacc_inputs = parse_wacc_inputs(wacc_path)
        except Exception as e:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.LOAD_WACC,
                    status="fail",
                    duration_ms=_ms_since(t0),
                    message=f"Failed to parse {wacc_path}: {e}",
                )
            )
            raise PipelineError(f"Failed to parse WACC inputs at {wacc_path}: {e}") from e
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.LOAD_WACC,
                status="ok",
                duration_ms=_ms_since(t0),
                message=f"WACC loaded (wacc={wacc_inputs.wacc:.2f}%).",
                data={"wacc_pct": str(wacc_inputs.wacc)},
            )
        )
        return wacc_inputs

    def _stage_load_extraction(
        self, extraction_path: Path, outcome: PipelineOutcome
    ) -> RawExtraction:
        """Parse ``raw_extraction.yaml`` + normalise unit scale.

        :class:`IngestionError` from the parser is wrapped as
        :class:`PipelineError` so the CLI treats extraction-file
        problems the same way as ingestion / WACC-parse problems.
        """
        t0 = perf_counter()
        try:
            raw = parse_raw_extraction(extraction_path)
        except Exception as e:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.LOAD_EXTRACTION,
                    status="fail",
                    duration_ms=_ms_since(t0),
                    message=f"Failed to parse {extraction_path}: {e}",
                )
            )
            raise PipelineError(
                f"Failed to parse raw_extraction at {extraction_path}: {e}"
            ) from e

        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.LOAD_EXTRACTION,
                status="ok",
                duration_ms=_ms_since(t0),
                message=(
                    f"Loaded + normalised {raw.metadata.document_type.value} for "
                    f"{raw.metadata.ticker} "
                    f"({len(raw.metadata.fiscal_periods)} fiscal period(s))."
                ),
                data={
                    "document_type": raw.metadata.document_type.value,
                    "extraction_type": raw.metadata.extraction_type.value,
                    "fiscal_periods": [
                        fp.period for fp in raw.metadata.fiscal_periods
                    ],
                    "source_file_sha256": raw.metadata.source_file_sha256,
                },
            )
        )
        return raw

    def _stage_validate_extraction(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
        outcome: PipelineOutcome,
    ) -> None:
        """Run strict + warn + completeness. Strict FAIL blocks the run.

        Warn + completeness reports are stored on the outcome and
        rendered via the per-run JSONL log; they don't halt the
        pipeline.
        """
        t0 = perf_counter()
        validator = self.extraction_validator
        strict = validator.validate_strict(raw_extraction)
        warn = validator.validate_warn(raw_extraction)
        profile = Profile(wacc_inputs.profile)
        completeness = validator.validate_completeness(raw_extraction, profile)

        outcome.extraction_validation_strict = strict
        outcome.extraction_validation_warn = warn
        outcome.extraction_validation_completeness = completeness

        strict_status = strict.overall_status
        warn_status = warn.overall_status
        comp_status = completeness.overall_status

        stage_status: str = "ok"
        if strict_status == "FAIL":
            stage_status = "fail"
        elif "WARN" in (warn_status, comp_status):
            stage_status = "ok"  # warns don't flip the stage

        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.VALIDATE_EXTRACTION,
                status=stage_status,
                duration_ms=_ms_since(t0),
                message=(
                    f"strict={strict_status} warn={warn_status} "
                    f"completeness={comp_status} "
                    f"(strict FAIL blocks, warn + completeness surface only)."
                ),
                data={
                    "strict": strict_status,
                    "warn": warn_status,
                    "completeness": comp_status,
                    "strict_fail_checks": [r.check_id for r in strict.fails],
                    "warn_checks": [r.check_id for r in warn.warns],
                    "completeness_fail_checks": [r.check_id for r in completeness.fails],
                },
            )
        )

        if strict_status == "FAIL":
            fail_ids = ", ".join(r.check_id for r in strict.fails)
            raise ExtractionValidationBlocked(
                f"Extraction strict validation FAILed on: {fail_ids}. "
                f"Fix the raw_extraction.yaml and retry."
            )

    async def _stage_cross_check(
        self,
        ticker: str,
        raw_extraction: RawExtraction,
        outcome: PipelineOutcome,
        *,
        skip_cross_check: bool,
    ) -> CrossCheckReport | None:
        t0 = perf_counter()
        if skip_cross_check:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.CROSS_CHECK,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message="Cross-check gate bypassed via --skip-cross-check.",
                )
            )
            return None

        extracted_values = _extract_cross_check_values(raw_extraction)
        report = await self.cross_check_gate.check(
            ticker=ticker,
            extracted_values=extracted_values,
            period=raw_extraction.primary_period.period,
        )
        status = (
            "fail" if report.overall_status == CrossCheckStatus.FAIL else "ok"
        )
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.CROSS_CHECK,
                status=status,
                duration_ms=_ms_since(t0),
                message=(
                    f"overall={report.overall_status.value} blocking={report.blocking} "
                    f"({len(report.metrics)} metrics)"
                ),
                data={
                    "overall_status": report.overall_status.value,
                    "blocking": report.blocking,
                    "metrics": len(report.metrics),
                },
            )
        )
        if report.blocking:
            raise CrossCheckBlocked(
                f"Cross-check blocked: overall={report.overall_status.value}. "
                f"Use --skip-cross-check to bypass (not recommended)."
            )
        return report

    async def _stage_extract_canonical(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
        identity: CompanyIdentity,
        outcome: PipelineOutcome,
    ) -> CanonicalCompanyState:
        t0 = perf_counter()
        doc_id = (
            f"{raw_extraction.metadata.ticker}/"
            f"{raw_extraction.metadata.document_type.value}/"
            f"{raw_extraction.metadata.fiscal_year}"
        )
        result = await self.extraction_coordinator.extract_canonical(
            raw_extraction=raw_extraction,
            wacc_inputs=wacc_inputs,
            identity=identity,
            source_documents=[doc_id],
        )
        if result.canonical_state is None:  # pragma: no cover - defensive
            raise PipelineError("extract_canonical returned no canonical_state")
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.EXTRACT_CANONICAL,
                status="ok",
                duration_ms=_ms_since(t0),
                message=(
                    f"modules={result.modules_run} adjustments={len(result.adjustments)}"
                ),
                data={
                    "modules_run": result.modules_run,
                    "adjustments": len(result.adjustments),
                    "extraction_id": result.canonical_state.extraction_id,
                },
            )
        )
        return result.canonical_state

    def _stage_persist(
        self, canonical: CanonicalCompanyState, outcome: PipelineOutcome
    ) -> None:
        t0 = perf_counter()
        self.state_repo.save(canonical)
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.PERSIST,
                status="ok",
                duration_ms=_ms_since(t0),
                message=f"canonical_state saved (id={canonical.extraction_id}).",
                data={"extraction_id": canonical.extraction_id},
            )
        )

    def _stage_guardrails(
        self,
        canonical: CanonicalCompanyState,
        cross_check_report: CrossCheckReport | None,
        wacc_inputs: WACCInputs,
        outcome: PipelineOutcome,
    ) -> AggregatedResults:
        t0 = perf_counter()
        runner = GuardrailRunner(default_guardrails())
        results = runner.run(
            {
                "canonical_state": canonical,
                "cross_check_report": cross_check_report,
                "wacc_inputs": wacc_inputs,
            },
            stop_on_blocking_fail=False,
        )
        agg = ResultAggregator.aggregate(results)
        status = "ok"
        if agg.overall == GuardrailStatus.FAIL:
            status = "fail"
        elif agg.overall in (GuardrailStatus.WARN, GuardrailStatus.REVIEW):
            status = "ok"  # WARN doesn't turn the stage into a fail

        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.GUARDRAILS,
                status=status,
                duration_ms=_ms_since(t0),
                message=f"overall={agg.overall.value} across {agg.total} checks",
                data={
                    "overall": agg.overall.value,
                    "by_status": {k.value: v for k, v in agg.by_status.items()},
                },
            )
        )
        return agg

    # ------------------------------------------------------------------
    async def _stage_valuate(
        self,
        canonical: CanonicalCompanyState,
        wacc_inputs: WACCInputs,
        outcome: PipelineOutcome,
    ) -> ValuationSnapshot | None:
        t0 = perf_counter()
        if (
            self.valuation_composer is None
            or self.scenario_composer is None
            or self.market_data_provider is None
        ):
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.VALUATE,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message=(
                        "Valuation wiring not provided — "
                        "pass valuation_composer, scenario_composer, and "
                        "market_data_provider to enable the DCF stage."
                    ),
                )
            )
            return None

        market = await self._fetch_market_snapshot(
            canonical=canonical,
            wacc_inputs=wacc_inputs,
        )
        scenarios = self.scenario_composer.compose(
            wacc_inputs=wacc_inputs,
            canonical_state=canonical,
        )
        snapshot = self.valuation_composer.compose(
            canonical_state=canonical,
            scenarios=scenarios,
            market=market,
        )
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.VALUATE,
                status="ok",
                duration_ms=_ms_since(t0),
                message=(
                    f"E[V]={snapshot.weighted.expected_value} "
                    f"range=[{snapshot.weighted.fair_value_range_low}, "
                    f"{snapshot.weighted.fair_value_range_high}] "
                    f"upside={snapshot.weighted.upside_pct:.2f}% "
                    f"across {len(snapshot.scenarios)} scenarios"
                ),
                data={
                    "expected_value": str(snapshot.weighted.expected_value),
                    "fair_value_low": str(snapshot.weighted.fair_value_range_low),
                    "fair_value_high": str(snapshot.weighted.fair_value_range_high),
                    "upside_pct": str(snapshot.weighted.upside_pct),
                    "scenarios": [sc.label for sc in snapshot.scenarios],
                },
            )
        )
        return snapshot

    # ------------------------------------------------------------------
    def _stage_persist_valuation(
        self,
        snapshot: ValuationSnapshot | None,
        outcome: PipelineOutcome,
    ) -> None:
        t0 = perf_counter()
        if snapshot is None or self.valuation_repo is None:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.PERSIST_VALUATION,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message="No valuation snapshot to persist.",
                )
            )
            return
        self.valuation_repo.save(snapshot)
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.PERSIST_VALUATION,
                status="ok",
                duration_ms=_ms_since(t0),
                message=f"valuation snapshot saved (id={snapshot.snapshot_id}).",
                data={"snapshot_id": snapshot.snapshot_id},
            )
        )

    # ------------------------------------------------------------------
    def _stage_compose_ficha(
        self,
        canonical: CanonicalCompanyState,
        snapshot: ValuationSnapshot | None,
        outcome: PipelineOutcome,
    ) -> Ficha | None:
        t0 = perf_counter()
        if self.ficha_composer is None or self.company_repo is None:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.COMPOSE_FICHA,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message=(
                        "Ficha wiring not provided — "
                        "pass ficha_composer and company_repo to persist the aggregate view."
                    ),
                )
            )
            return None
        ficha = self.ficha_composer.compose_and_save(
            canonical_state=canonical,
            valuation_snapshot=snapshot,
            company_repo=self.company_repo,
        )
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.COMPOSE_FICHA,
                status="ok",
                duration_ms=_ms_since(t0),
                message=(
                    f"ficha composed (age={ficha.snapshot_age_days} days, "
                    f"stale={ficha.is_stale})."
                ),
                data={
                    "ticker": ficha.ticker,
                    "snapshot_age_days": ficha.snapshot_age_days,
                    "is_stale": ficha.is_stale,
                },
            )
        )
        return ficha

    # ------------------------------------------------------------------
    async def _fetch_market_snapshot(
        self,
        canonical: CanonicalCompanyState,
        wacc_inputs: WACCInputs,
    ) -> MarketSnapshot:
        """Fetch current price + shares via the market data provider.

        Falls back to the WACC-file ``current_price`` when the provider
        is unavailable (logs an estimate note on the snapshot).
        """
        assert self.market_data_provider is not None
        price = wacc_inputs.current_price
        price_date = wacc_inputs.valuation_date
        shares = canonical.identity.shares_outstanding
        market_cap: Decimal | None = None
        try:
            quote = await self.market_data_provider.get_quote(wacc_inputs.ticker)
            if isinstance(quote, dict):
                p = _to_decimal(quote.get("price"))
                if p is not None and p > 0:
                    price = p
                s = _to_decimal(quote.get("sharesOutstanding"))
                if s is not None and s > 0:
                    shares = s
                mc = _to_decimal(quote.get("marketCap"))
                if mc is not None and mc > 0:
                    market_cap = mc
        except (MarketDataError, TickerNotFoundError):
            # Provider hiccup — fall through with WACC-file price.
            pass
        if market_cap is None and shares is not None:
            market_cap = price * shares

        return MarketSnapshot(
            price=price,
            price_date=price_date,
            shares_outstanding=shares,
            market_cap=market_cap,
            cost_of_equity=wacc_inputs.cost_of_equity,
            wacc=wacc_inputs.wacc,
            currency=canonical.identity.reporting_currency,
        )

    # ------------------------------------------------------------------
    def _persist_run_log(self, outcome: PipelineOutcome) -> Path | None:
        """Write one JSON line per stage to
        ``logs/runs/{ticker}_{timestamp}.jsonl``."""
        self.runs_log_dir.mkdir(parents=True, exist_ok=True)
        ts = outcome.started_at.strftime("%Y%m%dT%H%M%SZ")
        ticker_safe = outcome.ticker.replace(".", "-")
        path = self.runs_log_dir / f"{ticker_safe}_{ts}.jsonl"
        try:
            with path.open("w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "type": "run_header",
                            "ticker": outcome.ticker,
                            "started_at": outcome.started_at.isoformat(),
                            "finished_at": outcome.finished_at.isoformat(),
                            "success": outcome.success,
                        }
                    )
                    + "\n"
                )
                for stage in outcome.stages:
                    fh.write(
                        json.dumps(
                            {
                                "type": "stage",
                                **{k: v for k, v in asdict(stage).items()},
                                "stage": stage.stage.value,
                            }
                        )
                        + "\n"
                    )
                if outcome.guardrails:
                    for r in outcome.guardrails.results:
                        fh.write(
                            json.dumps(
                                {
                                    "type": "guardrail",
                                    "check_id": r.check_id,
                                    "name": r.name,
                                    "status": r.status.value,
                                    "message": r.message,
                                    "blocking": r.blocking,
                                }
                            )
                            + "\n"
                        )
        except OSError:
            # Never let the log write crash the pipeline — we've already
            # done the real work.
            return None
        return path


@contextmanager
def _null_ctx() -> Iterator[None]:
    yield


def _ms_since(t0: float) -> int:
    return int((perf_counter() - t0) * 1000)


# Re-export for convenience
__all__ = [
    "CrossCheckBlocked",
    "PipelineCoordinator",
    "PipelineError",
    "PipelineOutcome",
    "PipelineStage",
    "StageOutcome",
]


