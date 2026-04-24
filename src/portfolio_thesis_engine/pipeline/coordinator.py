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
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any, cast

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
from portfolio_thesis_engine.valuation.dispatcher import ValuationDispatcher
from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

_COST_OVERRIDE_CAP_USD = 10_000.0


class PipelineStage(StrEnum):
    CHECK_INGESTION = "check_ingestion"
    LOAD_WACC = "load_wacc"
    LOAD_EXTRACTION = "load_extraction"
    VALIDATE_EXTRACTION = "validate_extraction"
    CROSS_CHECK = "cross_check"
    DECOMPOSE_NOTES = "decompose_notes"
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


_REVENUE_LABEL = re.compile(r"^revenue$|^total revenue$|^sales$|^turnover$",
                            re.IGNORECASE)
_OP_INCOME_LABEL = re.compile(
    r"^operating (profit|income)$|profit from operations", re.IGNORECASE
)
_NET_INCOME_LABEL = re.compile(
    r"^profit for the (year|period)$|^net (income|profit)$", re.IGNORECASE
)
_CASH_LABEL = re.compile(r"cash (and cash equivalents|at bank|and deposits)",
                         re.IGNORECASE)
_TOTAL_ASSETS_LABEL = re.compile(r"total assets", re.IGNORECASE)
_TOTAL_EQUITY_LABEL = re.compile(r"^total equity$|^total shareholders'?\s?equity",
                                 re.IGNORECASE)
_CFO_LABEL = re.compile(r"net cash (generated|from|used).*operating|"
                        r"cash (flows?|generated) from operating",
                        re.IGNORECASE)
_CAPEX_LABEL = re.compile(
    r"purchas[ae] of (property|plant|equipment|intangib)|"
    r"capital expenditure|additions? to (property|ppe|intangib)",
    re.IGNORECASE,
)


def _first_line_value(items: list[Any], pattern: Any) -> Decimal | None:
    """Scan items (line_items) for a label match (non-subtotal first,
    subtotal fallback); return its value or None."""
    subtotal_hit: Decimal | None = None
    for item in items:
        if item.value is None:
            continue
        if pattern.search(item.label):
            if item.is_subtotal and subtotal_hit is None:
                subtotal_hit = cast(Decimal, item.value)
                continue
            return cast(Decimal, item.value)
    return subtotal_hit


def _first_subtotal_value(items: list[Any], pattern: Any) -> Decimal | None:
    for item in items:
        if not item.is_subtotal or item.value is None:
            continue
        if pattern.search(item.label):
            return cast(Decimal, item.value)
    return None


def _extract_cross_check_values(
    raw_extraction: RawExtraction,
) -> dict[str, Decimal]:
    """Pull top-level values (revenue, NI, total assets, etc.) from the
    as-reported :class:`RawExtraction` by label match, so the gate can
    compare against FMP / yfinance."""
    values: dict[str, Decimal] = {}

    is_data = raw_extraction.primary_is
    if is_data is not None:
        revenue = _first_line_value(is_data.line_items, _REVENUE_LABEL)
        if revenue is not None:
            values["revenue"] = revenue
        op_income = (
            _first_subtotal_value(is_data.line_items, _OP_INCOME_LABEL)
            or _first_line_value(is_data.line_items, _OP_INCOME_LABEL)
        )
        if op_income is not None:
            values["operating_income"] = op_income
        # Phase 1.5.6: prefer parent-attributed NI (matches FMP
        # netIncome semantics). Falls back to group NI subtotal.
        parent_ni: Decimal | None = None
        if is_data.profit_attribution is not None:
            parent_ni = is_data.profit_attribution.parent
        net_income = parent_ni or (
            _first_subtotal_value(is_data.line_items, _NET_INCOME_LABEL)
            or _first_line_value(is_data.line_items, _NET_INCOME_LABEL)
        )
        if net_income is not None:
            values["net_income"] = net_income

    bs_data = raw_extraction.primary_bs
    if bs_data is not None:
        cash = _first_line_value(bs_data.line_items, _CASH_LABEL)
        if cash is not None:
            values["cash"] = cash
        total_assets = _first_subtotal_value(
            bs_data.line_items, _TOTAL_ASSETS_LABEL
        )
        if total_assets is not None:
            values["total_assets"] = total_assets
        total_equity = _first_subtotal_value(
            bs_data.line_items, _TOTAL_EQUITY_LABEL
        )
        if total_equity is not None:
            values["total_equity"] = total_equity

    cf_data = raw_extraction.primary_cf
    if cf_data is not None:
        cfo = (
            _first_subtotal_value(cf_data.line_items, _CFO_LABEL)
            or _first_line_value(cf_data.line_items, _CFO_LABEL)
        )
        if cfo is not None:
            values["operating_cash_flow"] = cfo
        capex = _first_line_value(cf_data.line_items, _CAPEX_LABEL)
        if capex is not None:
            values["capex"] = capex

    return values


# Ticker-suffix → exchange / domicile map (Phase 1.5.6).
# Defaults when SQLite row is absent. Covers the main issuer
# exchanges in the portfolio universe; extend as new tickers arrive.
_TICKER_SUFFIX_EXCHANGE: dict[str, tuple[str, str]] = {
    # suffix: (exchange code, ISO-3166-1 alpha-2 domicile)
    "HK": ("HKEX", "HK"),
    "L": ("LSE", "GB"),
    "DE": ("XETRA", "DE"),
    "PA": ("EURONEXT_PARIS", "FR"),
    "AS": ("EURONEXT_AMSTERDAM", "NL"),
    "BR": ("EURONEXT_BRUSSELS", "BE"),
    "LS": ("EURONEXT_LISBON", "PT"),
    "MC": ("BME", "ES"),
    "MI": ("BORSA_ITALIANA", "IT"),
    "SW": ("SIX", "CH"),
    "ST": ("NASDAQ_STOCKHOLM", "SE"),
    "CO": ("NASDAQ_COPENHAGEN", "DK"),
    "OL": ("OSLO_BORS", "NO"),
    "HE": ("NASDAQ_HELSINKI", "FI"),
    "TO": ("TSX", "CA"),
    "V": ("TSXV", "CA"),
    "T": ("TSE", "JP"),
    "SS": ("SSE", "CN"),
    "SZ": ("SZSE", "CN"),
    "AX": ("ASX", "AU"),
    "NZ": ("NZX", "NZ"),
}

# Phase 1.5.7 — shares-unit → base-unit factor.
_SHARES_UNIT_FACTOR: dict[str, Decimal] = {
    "units": Decimal("1"),
    "unit": Decimal("1"),
    "thousands": Decimal("1000"),
    "thousand": Decimal("1000"),
    "'000": Decimal("1000"),
    "millions": Decimal("1000000"),
    "million": Decimal("1000000"),
    "'000,000": Decimal("1000000"),
}


def _shares_factor(unit: str | None) -> Decimal:
    """Return the multiplier to convert a share count reported in
    ``unit`` to base units. Defaults to 1 when ``unit`` is absent or
    unrecognised (assume as-reported).
    """
    if unit is None:
        return Decimal("1")
    return _SHARES_UNIT_FACTOR.get(unit.strip().lower(), Decimal("1"))


def _derive_shares_outstanding(raw: RawExtraction) -> Decimal | None:
    """Phase 1.5.7: extract shares_outstanding (in base units) from the
    primary period's EPS footer.

    Priority:
    1. ``earnings_per_share.basic_weighted_avg_shares`` scaled by
       ``earnings_per_share.shares_unit`` — always present when the
       issuer discloses EPS. Weighted-average is a close proxy for
       year-end issued shares (within ~1–2 %); exact year-end counts
       require the shareholders' equity movement note which is not
       yet typed.
    2. ``None`` if the EPS block is absent.

    The parser does NOT scale EPS / share counts by ``unit_scale``
    (they're dimensionally distinct from monetary values), so this
    helper is the single source of truth for share-count scaling.
    """
    is_data = raw.primary_is
    if is_data is None or is_data.earnings_per_share is None:
        return None
    eps = is_data.earnings_per_share
    if eps.basic_weighted_avg_shares is None:
        return None
    return eps.basic_weighted_avg_shares * _shares_factor(eps.shares_unit)


_ISIN_FROM_NOTES_PATTERN = re.compile(
    r"\bISIN[:\s]+([A-Z]{2}[A-Z0-9]{9}\d)\b"
)


def _derive_exchange_domicile(ticker: str) -> tuple[str, str]:
    """Return ``(exchange, country_domicile)`` from the ticker suffix.

    Example: ``"1846.HK"`` → ``("HKEX", "HK")``.  US tickers without a
    suffix default to ``("NYSE_or_NASDAQ", "US")``.  Fall back to
    ``("UNKNOWN", "XX")`` for unrecognised suffixes.
    """
    if "." not in ticker:
        # US convention: no suffix. We don't know NYSE vs NASDAQ here.
        return ("US", "US")
    suffix = ticker.rsplit(".", 1)[1].upper()
    if suffix in _TICKER_SUFFIX_EXCHANGE:
        return _TICKER_SUFFIX_EXCHANGE[suffix]
    return ("UNKNOWN", "XX")


def _identity_from(
    company_row: CompanyRow | None,
    wacc_inputs: WACCInputs,
    raw_extraction: RawExtraction,
) -> CompanyIdentity:
    """Build a :class:`CompanyIdentity` from SQLite row + WACC + raw
    extraction metadata.

    Phase 1.5.6 improvements:
    - Prefer ``metadata.company_name`` over ticker fallback for name.
    - Derive exchange + country_domicile from ticker suffix when
      SQLite row is missing or stale (``"?"`` in legacy rows).
    - Scavenge ISIN from ``extraction_notes`` free text when present.
    """
    reporting_currency = raw_extraction.metadata.reporting_currency
    if company_row is not None:
        with suppress(ValueError):
            reporting_currency = Currency(company_row.currency)

    # Exchange + domicile — prefer SQLite row; else derive from ticker.
    derived_exchange, derived_domicile = _derive_exchange_domicile(
        wacc_inputs.ticker
    )
    if company_row and company_row.exchange not in ("", "?"):
        exchange = company_row.exchange
        country_domicile = company_row.exchange  # legacy: same field
    else:
        exchange = derived_exchange
        country_domicile = derived_domicile

    # ISIN — look in extraction_notes for "ISIN: XXXXXXXXXXXX" pattern.
    isin: str | None = None
    notes_blob = raw_extraction.metadata.extraction_notes or ""
    match = _ISIN_FROM_NOTES_PATTERN.search(notes_blob)
    if match:
        isin = match.group(1)

    # Phase 1.5.7 — shares outstanding from EPS footer (base units).
    shares_outstanding = _derive_shares_outstanding(raw_extraction)

    # Phase 1.5.9.1 — prefer the extraction's ``metadata.company_name``
    # over the SQLite bootstrap row. The SQLite row is often just the
    # ticker repeated (``"1846.HK"``); the extraction carries the full
    # legal name ("EuroEyes International Eye Clinic Limited"). Fall
    # back to the row when the extraction omits the name, then to the
    # ticker as a last resort (the :class:`CompanyIdentity` schema
    # requires a non-empty string).
    name: str = (
        raw_extraction.metadata.company_name
        or (company_row.name if company_row else None)
        or wacc_inputs.ticker
    )

    return CompanyIdentity(
        ticker=wacc_inputs.ticker,
        isin=isin,
        name=name,
        reporting_currency=reporting_currency,
        profile=Profile(wacc_inputs.profile),
        fiscal_year_end_month=12,
        country_domicile=country_domicile,
        exchange=exchange,
        shares_outstanding=shares_outstanding,
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
        extraction_path: Path | None = None,
        base_period: str | None = None,
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

        Phase 1.5.13 — :param:`base_period` selects between multiple
        ingested extractions:

        - ``None`` / ``"AUTO"`` — most recent by mtime (warns via a
          :class:`StageOutcome` message when the selection is unaudited).
        - ``"LATEST-AUDITED"`` — most recent ``AUDITED`` file; raises
          :class:`PipelineError` when no audited extraction exists.
        - any other string — explicit period label (``"FY2024"``,
          ``"H1_2025"``, ``"FY2025-preliminary"``), matched against the
          primary-period label or filename stem.

        When both :param:`extraction_path` and :param:`base_period` are
        given, ``extraction_path`` wins (explicit > policy).
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

                # Phase 1.5.13 — resolve which extraction file to load
                # based on ``base_period`` policy. When an explicit
                # ``extraction_path`` was passed it wins; otherwise the
                # coordinator picks among every ``raw_extraction*.yaml``
                # discoverable for the ticker.
                if extraction_path is None:
                    extraction_path = self._select_base_extraction(
                        ticker=ticker,
                        base_period=base_period,
                        outcome=outcome,
                    )

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

                # Stage 5b — Module D decomposition. Runs before
                # extract_canonical so the analysis layer can consume
                # sub-item granularity. Ticket calls this
                # ``decompose_notes``; it's functionally sequenced
                # before the canonical build, not after, because the
                # NOPAT bridge's sustainable margin reads it.
                decompositions, decomposition_coverage = (
                    self._stage_decompose_notes(
                        ticker=ticker,
                        raw_extraction=raw_extraction,
                        outcome=outcome,
                    )
                )

                # Stage 6 — extract canonical
                company_row = self.metadata_repo.get_company(ticker)
                identity = _identity_from(company_row, wacc_inputs, raw_extraction)
                canonical = await self._stage_extract_canonical(
                    raw_extraction=raw_extraction,
                    wacc_inputs=wacc_inputs,
                    identity=identity,
                    outcome=outcome,
                    decompositions=decompositions,
                    decomposition_coverage=decomposition_coverage,
                )
                outcome.canonical_state = canonical

                # Stage 6 — persist
                self._stage_persist(canonical, outcome)

                # Stage 7 — guardrails
                agg = self._stage_guardrails(
                    canonical=canonical,
                    cross_check_report=cross_check_report,
                    wacc_inputs=wacc_inputs,
                    raw_extraction=raw_extraction,
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

    # ------------------------------------------------------------------
    # Phase 1.5.13 — base-period selection
    # ------------------------------------------------------------------
    def _select_base_extraction(
        self,
        ticker: str,
        base_period: str | None,
        outcome: PipelineOutcome,
    ) -> Path:
        """Phase 1.5.13 — resolve which ``raw_extraction*.yaml`` to load.

        Walks :class:`DocumentRepository` + ``~/data_inputs/<ticker>/``
        for every ``raw_extraction*.yaml``, peeks metadata (audit_status
        + document_type + primary period) on each, and applies the
        policy. Emits :class:`StageOutcome` messages for transparency.
        """
        candidates = _candidate_extractions(ticker, self.document_repo)
        if not candidates:
            raise PipelineError(
                f"No ingested raw_extraction*.yaml found for {ticker}."
            )
        policy = (base_period or "AUTO").upper()
        metadata = [(p, *_peek_audit_metadata(p)) for p in candidates]

        # Single-candidate shortcut only applies to AUTO — LATEST-
        # AUDITED must still enforce the audit filter even when one
        # file exists.
        if len(candidates) == 1 and policy == "AUTO":
            return candidates[0]

        if policy == "AUTO":
            path, audit, _doc, period = metadata[0]
            if audit == "unaudited":
                outcome.stages.append(
                    StageOutcome(
                        stage=PipelineStage.CHECK_INGESTION,
                        status="ok",
                        duration_ms=0,
                        message=(
                            f"AUTO selected unaudited extraction "
                            f"({path.name}, period={period}). Pass "
                            "--base-period LATEST-AUDITED to skip "
                            "preliminary sources."
                        ),
                        data={
                            "base_period_policy": policy,
                            "selected": path.name,
                            "audit_status": audit,
                        },
                    )
                )
            return path

        if policy == "LATEST-AUDITED":
            for path, audit, _doc, _period in metadata:
                if audit == "audited":
                    return path
            raise PipelineError(
                f"No audited extraction found for {ticker} "
                f"(checked {len(metadata)} candidate(s): "
                + ", ".join(f"{p.name}→{a}" for p, a, *_ in metadata)
                + "). Remove --base-period LATEST-AUDITED or ingest "
                "an audited source."
            )

        # Explicit period label — qualifier-aware match against the
        # candidate's primary period + audit status. Filename-stem
        # substring match survives as a secondary signal (some legacy
        # fixtures don't set the period label consistently).
        target = base_period or ""
        target_lower = target.lower()
        matches = [
            (p, audit, doc, period)
            for p, audit, doc, period in metadata
            if _match_period(audit, period, target)
            or target_lower in p.stem.lower()
        ]
        if not matches:
            available = ", ".join(
                f"{p.name} (period={per}, audit={aud})"
                for p, aud, _doc, per in metadata
            )
            raise PipelineError(
                f"--base-period {base_period!r} did not match any extraction "
                f"for {ticker}. Candidates: {available}"
            )
        # Prefer audited → reviewed → unaudited when multiple match.
        _priority = {"audited": 0, "reviewed": 1, "unaudited": 2}
        matches.sort(key=lambda m: _priority.get(m[1], 3))
        return matches[0][0]

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

        # Phase 1.5.13 — stage message surfaces document_type +
        # primary period + audit_status so it's immediately obvious
        # which document the pipeline is processing (especially in
        # multi-document runs driven by --base-period).
        primary = (
            raw.primary_period.period if raw.metadata.fiscal_periods else "n/a"
        )
        audit_status = raw.metadata.audit_status.value
        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.LOAD_EXTRACTION,
                status="ok",
                duration_ms=_ms_since(t0),
                message=(
                    f"Loaded + normalised {raw.metadata.document_type.value} for "
                    f"{raw.metadata.ticker} (period={primary}, "
                    f"audit_status={audit_status}, "
                    f"{len(raw.metadata.fiscal_periods)} fiscal period(s))."
                ),
                data={
                    "document_type": raw.metadata.document_type.value,
                    "extraction_type": raw.metadata.extraction_type.value,
                    "primary_period": primary,
                    "audit_status": audit_status,
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
        from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

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

        # Phase 1.5.11 — unaudited sources (preliminary investor
        # presentation, pre-audit announcement) won't be in FMP /
        # yfinance yet. Skipping is the honest outcome — SKIP not
        # WARN, because the external source doesn't *disagree*, it
        # doesn't exist.
        #
        # Phase 1.5.13.2 — also skip for REVIEWED (interim reports):
        # FMP / yfinance snapshot annual data; comparing an H1 /
        # quarterly figure against an annual snapshot produces huge
        # false-positive deltas.
        non_audited = (AuditStatus.UNAUDITED, AuditStatus.REVIEWED)
        if raw_extraction.metadata.audit_status in non_audited:
            audit_label = raw_extraction.metadata.audit_status.value
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.CROSS_CHECK,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message=(
                        f"cross_check skipped — {audit_label} source; "
                        "external providers (FMP / yfinance) snapshot "
                        "annual audited figures only."
                    ),
                    data={
                        "audit_status": audit_label,
                    },
                )
            )
            return None

        extracted_values = _extract_cross_check_values(raw_extraction)
        # Sprint 4A-alpha.7 — pass the int fiscal year so the gate can
        # filter provider responses by period. ``raw_extraction.metadata
        # .fiscal_year`` is already ``int | None``; when ``None`` the gate
        # falls back to its pre-4A-alpha.7 latest-annual path.
        report = await self.cross_check_gate.check(
            ticker=ticker,
            extracted_values=extracted_values,
            period=raw_extraction.primary_period.period,
            fiscal_year=raw_extraction.metadata.fiscal_year,
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

    def _stage_decompose_notes(
        self,
        ticker: str,
        raw_extraction: RawExtraction,
        outcome: PipelineOutcome,
    ) -> tuple[dict[str, Any], Any]:
        """Phase 1.5.10 — run Module D decomposition + attach overrides.

        Loads ``{portfolio_dir}/<ticker>/overrides.yaml`` when it
        exists. The status flips to WARN when more than half of IS
        leaves fell back to ``not_decomposable`` (a high fallback rate
        usually signals the extraction is missing note references).
        """
        t0 = perf_counter()
        try:
            from portfolio_thesis_engine.extraction.module_d import ModuleD
            from portfolio_thesis_engine.extraction.module_d_overrides import (
                load_overrides,
            )

            overrides = load_overrides(ticker)
            module_d = ModuleD(overrides=overrides)
            decompositions = module_d.decompose_all(raw_extraction)
            coverage = module_d.compute_coverage(raw_extraction, decompositions)
        except Exception as exc:
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.DECOMPOSE_NOTES,
                    status="fail",
                    duration_ms=_ms_since(t0),
                    message=f"Module D raised {type(exc).__name__}: {exc}",
                )
            )
            return {}, None

        from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

        is_total = coverage.is_total
        is_not_decomposable = coverage.is_not_decomposable
        status: str = "ok"
        unaudited = raw_extraction.metadata.audit_status == AuditStatus.UNAUDITED
        if unaudited:
            # Phase 1.5.11 — preliminary sources carry few notes by
            # design; a low decomposition rate is expected and
            # shouldn't be annotated as a warning.
            note_suffix = " (preliminary source — note disclosure limited)"
        elif is_total > 0 and is_not_decomposable * 2 > is_total:
            status = "ok"  # elevated fallback rate but not blocking
            note_suffix = " (high fallback rate — review note references)"
        else:
            note_suffix = ""

        outcome.stages.append(
            StageOutcome(
                stage=PipelineStage.DECOMPOSE_NOTES,
                status=status,
                duration_ms=_ms_since(t0),
                message=(
                    f"decomposed IS:{coverage.is_decomposed}/{coverage.is_total}, "
                    f"BS:{coverage.bs_decomposed}/{coverage.bs_total}, "
                    f"CF:{coverage.cf_decomposed}/{coverage.cf_total}"
                    f"{note_suffix}"
                ),
                data={
                    "is": {
                        "total": coverage.is_total,
                        "decomposed": coverage.is_decomposed,
                        "fallback": coverage.is_fallback,
                        "not_decomposable": coverage.is_not_decomposable,
                    },
                    "overrides_count": len(overrides.sub_item_classifications),
                },
            )
        )
        return decompositions, coverage

    async def _stage_extract_canonical(
        self,
        raw_extraction: RawExtraction,
        wacc_inputs: WACCInputs,
        identity: CompanyIdentity,
        outcome: PipelineOutcome,
        decompositions: dict[str, Any] | None = None,
        decomposition_coverage: Any = None,
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
            decompositions=decompositions,
            decomposition_coverage=decomposition_coverage,
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
        raw_extraction: RawExtraction,
        outcome: PipelineOutcome,
    ) -> AggregatedResults:
        t0 = perf_counter()
        runner = GuardrailRunner(default_guardrails())
        results = runner.run(
            {
                "canonical_state": canonical,
                "cross_check_report": cross_check_report,
                "wacc_inputs": wacc_inputs,
                # Phase 1.5.6: guardrails that need the structured
                # line_items (walking subtotals, is_subtotal flag) read
                # directly from the raw extraction.
                "raw_extraction": raw_extraction,
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
        # Phase 1.5.9 — dispatcher chooses engine by profile. For P1 it
        # resolves to :class:`FCFFDCFEngine` (the only implemented
        # engine); P2/P3a/P3b stubs raise on call. We don't *invoke*
        # the dispatcher here (the :class:`ScenarioComposer` does the
        # per-scenario call under the hood), but we log the choice for
        # audit purposes.
        dispatcher = ValuationDispatcher()
        engine = dispatcher.select_engine(canonical)
        if not engine.describe().get("implemented", True):
            # Phase 1.5.9 — a stub engine was selected: the pipeline
            # must skip valuation cleanly rather than raising deep in
            # the scenario loop.
            outcome.stages.append(
                StageOutcome(
                    stage=PipelineStage.VALUATE,
                    status="skip",
                    duration_ms=_ms_since(t0),
                    message=(
                        f"Profile {canonical.identity.profile.value} routes to "
                        f"{engine.describe().get('method')} engine (not yet "
                        "implemented — Phase 2)."
                    ),
                    data=engine.describe(),
                )
            )
            return None
        sensitivities = self.scenario_composer.compose_sensitivity(
            wacc_inputs=wacc_inputs,
            canonical_state=canonical,
            labels=("base",),
        )
        snapshot = self.valuation_composer.compose(
            canonical_state=canonical,
            scenarios=scenarios,
            market=market,
            sensitivities=sensitivities,
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


# ----------------------------------------------------------------------
# Phase 1.5.13 — base-period helpers (module level for testability)
# ----------------------------------------------------------------------
# Phase 1.5.13.1 — pattern is anchored at the end (``\.yaml$``) but
# NOT at the start, so ingest-renamed files like
# ``2025-06-30_raw_extraction_interim_h1_2025.yaml`` are discovered.
# We keep the pattern fragment ``raw_extraction`` to exclude unrelated
# YAMLs (``wacc_inputs.yaml`` etc.). Callers must use ``.search()``
# (not ``.match()``) so the pattern fires anywhere in the filename.
_EXTRACTION_FILE_PATTERN = re.compile(r"raw_extraction.*\.yaml$", re.IGNORECASE)


def _candidate_extractions(
    ticker: str, document_repo: DocumentRepository
) -> list[Path]:
    """Every ``raw_extraction*.yaml`` file we can find for a ticker,
    across the :class:`DocumentRepository` + the ``~/data_inputs/``
    layout. Sorted newest-first by mtime so ``AUTO`` picks index 0."""
    seen: set[Path] = set()
    try:
        for path in document_repo.list_documents(ticker):
            if _EXTRACTION_FILE_PATTERN.search(path.name):
                seen.add(path)
    except Exception:
        # A missing / unreadable repo shouldn't crash the resolver;
        # fall through to the ``data_inputs`` fallback.
        pass
    try:
        from portfolio_thesis_engine.storage.base import normalise_ticker

        base = Path.home() / "data_inputs" / normalise_ticker(ticker)
        if base.exists():
            # Phase 1.5.13.1 — leading ``*`` so date-prefixed files
            # (``2025-06-30_raw_extraction_interim_h1_2025.yaml``)
            # are discovered alongside legacy un-prefixed ones.
            for path in base.glob("*raw_extraction*.yaml"):
                seen.add(path)
    except Exception:
        pass
    return sorted(seen, key=lambda p: p.stat().st_mtime, reverse=True)


# Phase 1.5.13.2/13.3 — document-type → audit-status default.
# Canonical mapping lives on :mod:`schemas.raw_extraction` so the
# :class:`DocumentMetadata` model_validator and this selector apply
# the same heuristic. Re-exported here as the previously-public
# ``_audit_from_document_type`` name so existing tests keep working.
from portfolio_thesis_engine.schemas.raw_extraction import (  # noqa: E402
    _AUDIT_STATUS_BY_DOC_TYPE as _AUDIT_STATUS_BY_DOC_TYPE,
    audit_status_for_document_type as _audit_from_document_type,
)


# Phase 1.5.13.2 — period-label qualifier parsing
_PERIOD_QUALIFIERS: frozenset[str] = frozenset(
    {"preliminary", "audited", "reviewed", "unaudited"}
)


def _parse_period_label(label: str) -> tuple[str, str | None]:
    """Split an explicit ``--base-period`` label into ``(base, qualifier)``.

    Examples::

        FY2024              → ("FY2024", None)
        FY2025-preliminary  → ("FY2025", "preliminary")
        H1_2025             → ("H1_2025", None)
        FY2024-audited      → ("FY2024", "audited")

    Only the suffixes in :data:`_PERIOD_QUALIFIERS` are treated as
    qualifiers; everything else stays part of the base. Preserves the
    caller's casing so downstream matches honour ``FY`` / ``H1`` etc.
    """
    lowered = label.lower()
    for qualifier in _PERIOD_QUALIFIERS:
        suffix = f"-{qualifier}"
        if lowered.endswith(suffix):
            base = label[: -len(suffix)]
            return base, qualifier
    return label, None


def _match_period(
    audit: str,
    period: str,
    target_label: str,
) -> bool:
    """Return ``True`` when the candidate's ``(audit, period)`` satisfies
    the target label. Qualifier semantics:

    - ``preliminary`` → audit must be ``unaudited``.
    - ``audited`` / ``reviewed`` / ``unaudited`` → literal match.

    Literal equality always wins — some extractions encode the
    qualifier directly in ``metadata.fiscal_periods[].period`` (e.g.
    ``"FY2025-preliminary"``), in which case we honour the caller's
    target verbatim without splitting.
    """
    if period.lower() == target_label.lower():
        return True
    target_base, qualifier = _parse_period_label(target_label)
    if period.lower() != target_base.lower():
        return False
    if qualifier is None:
        return True
    if qualifier == "preliminary":
        return audit == "unaudited"
    return audit == qualifier


def _peek_audit_metadata(path: Path) -> tuple[str, str, str]:
    """Cheap YAML peek: return ``(audit_status, document_type, period)``
    without parsing the whole extraction.

    Phase 1.5.13.2 — three-tier audit-status resolution:

    1. ``metadata.audit_status`` (top-level, explicit) wins.
    2. First primary ``fiscal_periods[*].audit_status`` (per-period,
       how interim reports typically carry it).
    3. Document-type default via :data:`_AUDIT_STATUS_BY_DOC_TYPE`
       (``interim_report`` → ``reviewed``, ``preliminary_results`` →
       ``unaudited``, ``annual_report`` → ``audited``, etc.).

    Fixes a cascading bug where interim YAMLs — which carry
    ``audit_status`` per-period instead of top-level — were defaulted
    to ``"audited"`` and consequently beat real audited ARs in the
    ``LATEST-AUDITED`` policy race.
    """
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return "audited", "unknown", ""
    metadata = raw.get("metadata") or {}
    doc_type = str(metadata.get("document_type") or "unknown")

    fps = metadata.get("fiscal_periods") or []
    period = ""
    if fps and isinstance(fps, list) and isinstance(fps[0], dict):
        period = str(fps[0].get("period") or "")

    explicit = metadata.get("audit_status")
    if explicit:
        return str(explicit).lower(), doc_type, period

    # Per-period fallback — pick the primary period's status; if no
    # period is flagged primary, use the first entry.
    primary_audit: Any = None
    for fp in fps:
        if isinstance(fp, dict) and fp.get("is_primary"):
            primary_audit = fp.get("audit_status")
            break
    if primary_audit is None and fps and isinstance(fps[0], dict):
        primary_audit = fps[0].get("audit_status")
    if primary_audit:
        return str(primary_audit).lower(), doc_type, period

    # Tier 3 — derive from document type.
    return _audit_from_document_type(doc_type), doc_type, period


# Re-export for convenience
__all__ = [
    "CrossCheckBlocked",
    "PipelineCoordinator",
    "PipelineError",
    "PipelineOutcome",
    "PipelineStage",
    "StageOutcome",
]


