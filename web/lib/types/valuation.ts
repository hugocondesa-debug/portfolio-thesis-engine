/**
 * Valuation snapshot shape returned by `/api/tickers/{ticker}/valuation`.
 *
 * Source-of-truth: PTE `ValuationSnapshot` (analyst-facing snapshot — not the
 * intermediate `DCFValuation` produced by the engine). This shape is the one
 * persisted to disk and re-served by the API layer.
 */

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
  scenarios: ValuationScenario[];
  weighted: WeightedSummary;
  reverse: Record<string, unknown>;
  cross_checks: Record<string, unknown>;
  eps_bridge: unknown | null;
  catalysts: unknown[];
  factor_exposures: unknown | null;
  scenario_response: unknown | null;
  sensitivities: unknown | null;
  conviction: ConvictionScores;
  guardrails: unknown[];
  forecast_system_version: string | null;
  source_documents: string[];
  total_api_cost_usd: string | null;
}

export interface ValuationMarket {
  price: string;
  price_date: string;
  shares_outstanding: string;
  market_cap: string;
  cost_of_equity: string;
  wacc: string;
  currency: string;
}

export interface ValuationScenario {
  label: string;
  description: string | null;
  probability: string;
  horizon_years: number | null;
  drivers: ScenarioDrivers;
  targets: ScenarioTargets | null;
  irr_3y: string | null;
  irr_5y: string | null;
  irr_decomposition: unknown | null;
  upside_pct: string | null;
  survival_conditions: string[];
  kill_signals: string[];
  projection: unknown | null;
  terminal: ScenarioTerminal | null;
  enterprise_value_breakdown: EnterpriseValueBreakdown | null;
  equity_bridge: EquityBridge | null;
  sensitivity_grids: unknown | null;
}

export interface ScenarioDrivers {
  revenue_growth?: string | string[] | null;
  operating_margin?: string | null;
  fade_pattern?: string | string[] | null;
  reinvestment_rate?: string | null;
  // Free-form driver bag — analyst yamls evolve.
  [key: string]: unknown;
}

export interface ScenarioTargets {
  fair_value_per_share: string | null;
  enterprise_value: string | null;
  equity_value: string | null;
  multiple_at_exit: string | null;
  [key: string]: unknown;
}

export interface ScenarioTerminal {
  method: string;
  growth_rate: string | null;
  exit_multiple: string | null;
  exit_metric: string | null;
  terminal_value: string | null;
  [key: string]: unknown;
}

export interface EnterpriseValueBreakdown {
  pv_explicit: string | null;
  pv_terminal: string | null;
  enterprise_value: string;
  [key: string]: unknown;
}

export interface EquityBridge {
  enterprise_value: string;
  net_debt: string | null;
  non_operating_assets: string | null;
  equity_value: string;
  shares_outstanding: string | null;
  fair_value_per_share: string | null;
  [key: string]: unknown;
}

export interface WeightedSummary {
  expected_value: string;
  expected_value_method_used: string;
  fair_value_range_low: string;
  fair_value_range_high: string;
  upside_pct: string | null;
  asymmetry_ratio: string | null;
  weighted_irr_3y: string | null;
  weighted_irr_5y: string | null;
}

export interface ConvictionScores {
  forecast: string;
  valuation: string;
  asymmetry: string;
  timing_risk: string;
  liquidity_risk: string;
  governance_risk: string;
  [key: string]: string;
}
