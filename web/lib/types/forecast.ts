/**
 * Three-statement forecast shape returned by `/api/tickers/{ticker}/forecast`.
 * Mirrors `forecast/schemas.py::ForecastResult`.
 */

export interface ForecastResult {
  ticker: string;
  generated_at: string;
  projections: ThreeStatementProjection[];
  probability_weighted_ev: string | null;
  expected_forward_eps_y1: string | null;
  expected_forward_per_y1: string | null;
}

export interface ThreeStatementProjection {
  scenario_name: string;
  scenario_probability: string;
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
  revenue: string;
  revenue_growth_rate: string;
  operating_margin: string;
  operating_income: string;
  interest_expense: string;
  interest_income: string;
  pre_tax_income: string;
  tax_rate: string;
  tax_expense: string;
  net_income: string;
  shares_outstanding: string;
  eps: string;
}

export interface ForecastBalanceSheetYear {
  year: number;
  ppe_net: string;
  goodwill: string;
  working_capital_net: string;
  cash: string;
  total_assets: string;
  debt: string;
  equity: string;
}

export interface ForecastCashFlowYear {
  year: number;
  cfo: string;
  cfi: string;
  cff: string;
  capex: string;
  ma_deployment: string;
  dividends_paid: string;
  buybacks_executed: string;
  debt_issued: string;
  debt_repaid: string;
  net_interest: string;
  fx_effect: string;
  net_change_cash: string;
}

export interface ForecastRatiosYear {
  year: number;
  per_at_market_price: string | null;
  per_at_fair_value: string | null;
  fcf_yield_at_market: string | null;
  ev_ebitda: string | null;
  roic: string | null;
  roe: string | null;
  debt_to_ebitda: string | null;
  wacc_applied: string | null;
}
