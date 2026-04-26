/**
 * Three-statement forecast shape returned by ``/api/tickers/{ticker}/forecast``.
 * Mirrors ``forecast/schemas.py::ForecastResult``.
 *
 * Sprint 1B.2 — the API returns ``dict[str, Any]`` from ``json.loads()``,
 * so numeric fields land in JSON as **numbers** rather than the
 * Decimal-as-string convention used elsewhere in PTE. Types accept both
 * shapes (``string | number``) so callers can pipe values straight into the
 * format helpers (which already coerce both).
 *
 * Ratio fields here are **fractions** (``0.1756`` ≡ 17.56%) — pipe through
 * :func:`formatPercent` (which multiplies by 100), NOT
 * :func:`formatPercentDirect` which is used for canonical-analysis ratios
 * stored as percent strings.
 */

export type ForecastNumber = string | number;

export interface ForecastResult {
  ticker: string;
  generated_at: string;
  projections: ThreeStatementProjection[];
  probability_weighted_ev: ForecastNumber | null;
  expected_forward_eps_y1: ForecastNumber | null;
  expected_forward_per_y1: ForecastNumber | null;
}

export interface ThreeStatementProjection {
  scenario_name: string;
  scenario_probability: ForecastNumber;
  base_year_label: string;
  projection_years: number;
  income_statement: ForecastIncomeStatementYear[];
  balance_sheet: ForecastBalanceSheetYear[];
  cash_flow: ForecastCashFlowYear[];
  forward_ratios: ForecastRatiosYear[];
  solver_convergence: SolverConvergence;
  warnings: string[];
}

export interface SolverConvergence {
  iterations: number;
  final_residual: number;
  converged: boolean;
}

export interface ForecastIncomeStatementYear {
  year: number;
  revenue: ForecastNumber;
  revenue_growth_rate: ForecastNumber;
  operating_margin: ForecastNumber;
  operating_income: ForecastNumber;
  interest_expense: ForecastNumber;
  interest_income: ForecastNumber;
  pre_tax_income: ForecastNumber;
  tax_rate: ForecastNumber;
  tax_expense: ForecastNumber;
  net_income: ForecastNumber;
  shares_outstanding: ForecastNumber;
  eps: ForecastNumber;
}

export interface ForecastBalanceSheetYear {
  year: number;
  ppe_net: ForecastNumber;
  goodwill: ForecastNumber;
  working_capital_net: ForecastNumber;
  cash: ForecastNumber;
  total_assets: ForecastNumber;
  debt: ForecastNumber;
  equity: ForecastNumber;
}

export interface ForecastCashFlowYear {
  year: number;
  cfo: ForecastNumber;
  cfi: ForecastNumber;
  cff: ForecastNumber;
  capex: ForecastNumber;
  ma_deployment: ForecastNumber;
  dividends_paid: ForecastNumber;
  buybacks_executed: ForecastNumber;
  debt_issued: ForecastNumber;
  debt_repaid: ForecastNumber;
  net_interest: ForecastNumber;
  fx_effect: ForecastNumber;
  net_change_cash: ForecastNumber;
}

export interface ForecastRatiosYear {
  year: number;
  per_at_market_price: ForecastNumber | null;
  per_at_fair_value: ForecastNumber | null;
  fcf_yield_at_market: ForecastNumber | null;
  ev_ebitda: ForecastNumber | null;
  roic: ForecastNumber | null;
  roe: ForecastNumber | null;
  debt_to_ebitda: ForecastNumber | null;
  wacc_applied: ForecastNumber | null;
}

// Sprint 1B.2 — short aliases used by the new ForecastDetail component for
// brevity. Kept as type aliases so existing imports keep working.
export type ForecastISYear = ForecastIncomeStatementYear;
export type ForecastBSYear = ForecastBalanceSheetYear;
export type ForecastCFYear = ForecastCashFlowYear;
