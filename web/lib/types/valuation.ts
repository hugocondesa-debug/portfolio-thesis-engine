/**
 * Valuation snapshot shape returned by ``/api/tickers/{ticker}/valuation``.
 *
 * Sprint 1A.1 — corrected to match the real PTE schema rather than the
 * Sprint 1A spec assumptions. The headline E[V] lives in ``weighted``;
 * per-scenario fair value lives in ``scenario.targets.dcf_fcff_per_share``;
 * percent-coded fields (``probability``, ``upside_pct``, ``irr_*``) are
 * **strings expressing units of 1%** (e.g. ``"25"`` ≡ 25%, ``"7.795"`` for
 * E[V] is HK$7.795 — only IRR / probability / upside are percentages).
 */

import type { DecimalString } from "./api";

export interface ValuationSnapshot {
  version: number;
  created_at: string;
  created_by: string;
  previous_version: string | null;
  snapshot_id: string;
  ticker: string;
  company_name: string | null;
  profile: string;
  valuation_date: string;
  based_on_extraction_id: string;
  based_on_extraction_date: string;

  market: ValuationMarket;
  scenarios: ScenarioResult[];
  weighted: WeightedValuation;

  reverse: Record<string, unknown> | null;
  cross_checks: Record<string, unknown> | null;
  eps_bridge: unknown | null;
  catalysts: unknown[];
  factor_exposures: unknown[];
  scenario_response: unknown | null;
  sensitivities: unknown[];

  conviction: ConvictionScores;
  guardrails: GuardrailsResult | unknown[];
  forecast_system_version: string | null;
  source_documents: string[];
  total_api_cost_usd: DecimalString | null;
}

export interface ValuationMarket {
  price: DecimalString;
  price_date: string;
  shares_outstanding: DecimalString;
  market_cap: DecimalString;
  cost_of_equity: DecimalString;
  wacc: DecimalString;
  currency: string;
}

export interface WeightedValuation {
  expected_value: DecimalString;
  expected_value_method_used: string;
  fair_value_range_low: DecimalString;
  fair_value_range_high: DecimalString;
  upside_pct: DecimalString;
  asymmetry_ratio: DecimalString;
  weighted_irr_3y: DecimalString | null;
  weighted_irr_5y: DecimalString | null;
}

export interface ScenarioResult {
  /** Scenario name — ``"bear" | "base" | "bull" | ...``. */
  label: string;
  description: string | null;
  /** Percent units stored as a string. ``"25"`` ≡ 25%. */
  probability: DecimalString;
  horizon_years: number | null;
  drivers: ScenarioDrivers;
  targets: ScenarioTargets;
  /** Percent units. ``"17.67"`` ≡ 17.67%. ``null`` when not applicable. */
  irr_3y: DecimalString | null;
  irr_5y: DecimalString | null;
  irr_decomposition: IRRDecomposition | null;
  /** Percent units. ``"62.96"`` ≡ 62.96%. */
  upside_pct: DecimalString | null;
  survival_conditions: unknown[];
  kill_signals: unknown[];
  projection: ScenarioProjectionYear[] | null;
}

export interface ScenarioDrivers {
  revenue_cagr: DecimalString | null;
  terminal_growth: DecimalString | null;
  terminal_margin: DecimalString | null;
  terminal_roic: DecimalString | null;
  terminal_wacc: DecimalString | null;
  terminal_roe: DecimalString | null;
  terminal_payout: DecimalString | null;
  terminal_nim: DecimalString | null;
  terminal_cor_bps: DecimalString | null;
  terminal_cost_income: DecimalString | null;
  terminal_cet1: DecimalString | null;
  custom_drivers: Record<string, DecimalString>;
}

export interface ScenarioTargets {
  equity_value: DecimalString | null;
  /** Per-share fair value — what the headline UI quotes. */
  dcf_fcff_per_share: DecimalString | null;
}

export interface IRRDecomposition {
  /** Percent units. */
  fundamental: DecimalString | null;
  rerating: DecimalString | null;
  dividend: DecimalString | null;
}

export interface ScenarioProjectionYear {
  year: number;
  revenue: DecimalString | null;
  operating_margin_reported: DecimalString | null;
  operating_margin_sustainable: DecimalString | null;
  operating_margin_used: DecimalString | null;
  ebit: DecimalString | null;
  amort_for_ebita: DecimalString | null;
  ebita: DecimalString | null;
  nopat: DecimalString | null;
  depreciation: DecimalString | null;
  capex: DecimalString | null;
  wc_change: DecimalString | null;
  fcff: DecimalString | null;
  discount_factor: DecimalString | null;
  pv_fcff: DecimalString | null;
}

export interface ConvictionScores {
  forecast: ConvictionLevel;
  valuation: ConvictionLevel;
  asymmetry: ConvictionLevel;
  timing_risk: ConvictionLevel;
  liquidity_risk: ConvictionLevel;
  governance_risk: ConvictionLevel;
}

export type ConvictionLevel = "low" | "medium" | "high";

export interface GuardrailsResult {
  categories: Record<string, unknown>;
  overall: "PASS" | "WARN" | "FAIL";
}
