# Phase 2 Sprint 3 — follow-ups

**Status:** queued. Sprint 3 (tag `v0.7.0-phase2-sprint3-peers-capital`)
shipped peer-relative valuation + auto-generated WACC with scope-shaping
decisions that deferred five items. This document captures each so the
architect can sequence them against Sprint 4+ work.

Each entry lists the rationale for deferring, the target sprint (when
we have a view), the test-plan sketch, and the files most likely to be
touched. Effort estimates assume Claude Code pace.

---

## 1. Revenue geography auto-extraction from canonical state segments

**Status.** User-curated `data/yamls/companies/<ticker>/revenue_geography.yaml`
is the current input path for CRP weighting. The raw extraction
already captures `RawExtraction.segments.by_geography` but it's dropped
before the canonical state serialises.

**Why deferred.** Sprint 3 scope was large enough; wiring segments
through the canonical state is a pipeline refactor (extraction →
analysis → canonical schema), not an analytical-layer change.
Hand-curated YAML was the low-risk path to validate the WACC
methodology first.

**Target.** Sprint 4 if analyst friction proves high; Sprint 5
otherwise.

**Proposed path.**
1. Extend `CanonicalCompanyState` with an optional `segments:
   SegmentsBlock | None` field mirroring the raw-extraction shape.
2. Copy segments through in `ExtractionCoordinator._build_canonical_state`.
3. Update `capital/loaders.py::load_revenue_geography` to check the
   canonical state first, fall back to the YAML, fall back to
   listing-country CRP.
4. Analyst YAML becomes an optional override for edge cases
   (segments missing, or analyst disagrees with segment classification).

**Tests.**
- `test_canonical_state_persists_segments_by_geography`
- `test_loader_prefers_canonical_segments_over_yaml`
- `test_loader_falls_back_to_yaml_when_segments_absent`
- `test_loader_falls_back_to_listing_country_when_both_absent`

**Files.**
- `src/portfolio_thesis_engine/schemas/company.py` (add `segments`)
- `src/portfolio_thesis_engine/extraction/coordinator.py` (propagate)
- `src/portfolio_thesis_engine/capital/loaders.py`

**Effort.** 2 – 3 h.

---

## 2. FRED live risk-free-rate refresh

**Status.** Rf-by-currency lives in a static YAML snapshot under
`src/portfolio_thesis_engine/reference/data/risk_free_rates_by_currency.yaml`.
Refresh is manual (quarterly).

**Why deferred.** Static data suffices for the methodology validation.
Building a live client adds surface area (API credentials, caching,
retry, rate limits) that wasn't load-bearing for Sprint 3.

**Target.** Sprint 6 (monitoring). Rationale: when the monitoring
sprint adds periodic WACC recomputation for tracked positions, stale
Rf becomes a real signal-quality issue.

**Proposed path.**
1. New `src/portfolio_thesis_engine/market_data/fred_provider.py`
   mirroring the `FMPProvider` pattern (async httpx client, typed
   errors, cost tracker integration).
2. Methods: `get_treasury_10y_yield()`, `get_inflation_expectations(tips_breakeven)`,
   `get_sovereign_yield(country, maturity)`.
3. Caching layer writes to `data/cache/fred/<series_id>_<date>.json`
   with 24-hour TTL so repeated pipeline runs don't hit the API.
4. `DamodaranReference.risk_free_rate` becomes a layered resolver:
   FRED cache → YAML fallback → explicit error.

**Tests.**
- `test_fred_provider_fetches_ust_10y`
- `test_fred_cache_hit_skips_network`
- `test_fred_cache_miss_writes_fresh_data`
- `test_rf_resolver_falls_back_to_yaml_on_fred_failure`
- `test_stale_fred_cache_triggers_refresh`

**Files.**
- `src/portfolio_thesis_engine/market_data/fred_provider.py` (new)
- `src/portfolio_thesis_engine/reference/damodaran.py`
- `src/portfolio_thesis_engine/shared/config.py` (FRED_API_KEY)

**Effort.** 3 – 4 h plus live-API smoke test.

---

## 3. Real FMP adapter for peer fundamentals

**Status.** `PeerProvider` + `PeerFundamentalsProvider` are DI
protocols. The default implementations (`_NoopPeerProvider`,
`_NoopFundamentalsProvider`) return empty data so the CLI works
against analyst-curated `peers.yaml` files without live API access.

**Why deferred.** Sprint 3 proved the schemas + math against static
fixtures. Wiring live FMP is straightforward once the data path is
validated, and it needs a credentialled test environment that's easier
to stand up when the first real analyst workflow demands it.

**Target.** Next practical step — Sprint 4 candidate. This is the
highest-ROI deferred item because every downstream feature that uses
`PeerComparison` (regression signals, peer-relative valuation in the
CLI) is currently "methodologically correct but empty" without it.

**Proposed path.**
1. New `src/portfolio_thesis_engine/peers/fmp_adapter.py` wraps the
   existing `FMPProvider` (already at
   `src/portfolio_thesis_engine/market_data/fmp_provider.py`).
2. Implement `FMPPeerProvider.fetch_peers(ticker)` — FMP profile
   endpoint returns sector + industry; FMP stock-screener endpoint
   filtered to same industry gives peer list; map to
   `PeerCompany`.
3. Implement `FMPPeerFundamentalsProvider.fetch_fundamentals(ticker)` —
   FMP's `key-metrics` + `ratios-ttm` + `profile` endpoints populate
   `PeerFundamentals`. Currency conversion via `forex` endpoint for
   USD market cap.
4. CLI `pte peers <ticker>` wires the FMP adapters when
   `FMP_API_KEY` is set; falls back to the no-op provider otherwise.
5. Caching: peer fundamentals TTL ~24 h (market cap shifts faster but
   ratios are stable within a day).

**Tests.**
- `test_fmp_peer_provider_maps_industry_to_peer_set`
- `test_fmp_fundamentals_provider_populates_ratios`
- `test_fmp_adapter_graceful_on_rate_limit`
- `test_fmp_adapter_skips_tickers_not_found`
- Integration: `test_euroeyes_peers_cli_renders_comparison_with_fmp`
  (skipped when `FMP_API_KEY` absent).

**Files.**
- `src/portfolio_thesis_engine/peers/fmp_adapter.py` (new)
- `src/portfolio_thesis_engine/cli/peers_cmd.py` (wire adapter)
- `src/portfolio_thesis_engine/cli/analyze_cmd.py` (peer summary
  section wiring)

**Effort.** 4 – 5 h.

---

## 4. Multi-currency debt handling

**Status.** The WACC generator correctly detects currency regime for
**cost of equity** (USD-base + Fisher conversion when HIGH_INFLATION).
**Cost of debt** currently short-circuits when the company has zero
financial debt (EuroEyes' case) and otherwise uses a single
listing-currency Rf + spread.

Companies that issue debt in multiple currencies (USD-denominated
Eurobonds + local-currency bank loans) or whose effective interest
rate reflects a currency mix need a weighted CoD.

**Why deferred.** No test subject in the current pipeline has
non-trivial foreign-currency debt; EuroEyes has zero debt entirely, so
CoD isn't even applicable. The code is correct *for the companies
actually analysed*; extending it would be over-engineering ahead of
demand.

**Target.** When the first analyst subject with meaningful
foreign-currency debt lands — likely Sprint 7+ (emerging-market
equity analysis).

**Proposed path.**
1. Extend `WACCGeneratorInputs` with `debt_structure:
   list[DebtTranche] | None` where each tranche carries `currency`,
   `book_value`, and optionally `explicit_rate`.
2. `_build_cod` iterates tranches:
   - per-tranche Rf from the Damodaran table
   - per-tranche synthetic rating (or explicit_rate override)
   - weighted CoD = Σ (tranche_weight × tranche_pretax_cod)
3. Handle FX exposure separately: Damodaran's convention is the
   operational-currency Rf — a USD-bond by a Turkish company still
   uses the *functional* currency when the operations are TRY.
4. Audit narrative lists tranches explicitly.

**Tests.**
- `test_cod_single_currency_back_compat`
- `test_cod_weighted_across_two_currencies`
- `test_cod_respects_tranche_explicit_rate`
- `test_cod_narrative_lists_tranches`

**Files.**
- `src/portfolio_thesis_engine/schemas/cost_of_capital.py`
  (new `DebtTranche` schema)
- `src/portfolio_thesis_engine/capital/wacc_generator.py`

**Effort.** 3 h.

---

## 5. HIGH_INFLATION regime live testing

**Status.** `test_coe_requires_usd_conversion_when_inflation_diff_gt_3`
verifies the regime detection flips and `requires_usd_conversion = True`
when inflation differential > 3 pp (TRY vs USD test case). But the
branch has only been exercised synthetically — no end-to-end company
analysis has driven CAPM through the Fisher conversion path.

**Why deferred.** Waiting for a real analyst subject. The fixture test
validates the arithmetic identity; the real-world test validates
table coverage (CRP + Rf for the country's currency, analyst-authored
geography, etc.).

**Target.** When the first analyst subject in a HIGH_INFLATION
currency lands. Candidates: Türkiye Cumhuriyeti issuer, Argentinean
issuer, any LatAm issuer with inflation > 5 %.

**Proposed path.**
1. Pick a test subject (user-driven; likely Sprint 6 – 8 timeframe).
2. Ensure the CRP + Rf + inflation tables cover the country + currency.
3. Run `pte analyze <ticker>` and confirm the WACC section prints
   `Currency regime: HIGH_INFLATION` + `requires_usd_conversion: true`
   and the CoE final value reconciles against a hand-computed
   reference.
4. Smoke-test the Fisher conversion edge cases (differential inflation
   near the 3 pp threshold — DEVELOPED one period, HIGH_INFLATION the
   next, if analyst re-runs quarterly).

**Tests** (live-fixture, not synthetic).
- `test_real_high_inflation_subject_coe_matches_reference`
- `test_threshold_stability_when_near_3pp_differential`

**Files.** Likely none; validation is configuration + reference-table
completeness.

**Effort.** 1 – 2 h once a subject exists.

---

## Sequencing recommendation

Rough priority if we had to sequence these today:

1. **#3 (FMP live fundamentals)** — unlocks everything downstream from
   `PeerComparison`; analyst-visible value returns immediately.
2. **#1 (segments auto-extract)** — removes analyst friction for WACC
   geography. Small refactor, high UX payoff.
3. **#4 (multi-currency debt)** — do only when a subject forces it.
4. **#2 (FRED live Rf)** — pair with Sprint 6 monitoring.
5. **#5 (HIGH_INFLATION validation)** — opportunistic; validates when
   a subject exists.

Items 3 and 1 together are ~6 – 8 h of Claude Code and convert the
Sprint 3 scaffolding into a "real" analyst workflow without needing
Sprint 4's formal scope.
