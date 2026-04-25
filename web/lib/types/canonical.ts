/**
 * Canonical company state shape returned by `/api/tickers/{ticker}/canonical`.
 *
 * Source-of-truth: PTE Phase 1.5 `CanonicalCompanyState` schema. This file
 * mirrors the **on-the-wire** shape (label-keyed line arrays, period dicts
 * with `year/quarter/label`) — not the optimistic per-period dictionaries
 * the original Sprint 1A spec assumed.
 */

export interface CanonicalState {
  extraction_id: string;
  extraction_date: string;
  as_of_date: string;
  identity: CompanyIdentity;
  reclassified_statements: ReclassifiedStatements[];
  adjustments: AdjustmentsApplied;
  analysis: AnalysisDerived;
  quarterly: unknown | null;
  validation: ValidationResults;
  vintage: VintageAndCascade;
  methodology: MethodologyMetadata;
  narrative_context: NarrativeContext | null;
  source_documents: string[];
}

export interface CompanyIdentity {
  ticker: string;
  isin: string | null;
  name: string;
  legal_name: string | null;
  reporting_currency: string;
  profile: string;
  sector_gics: string | null;
  industry_gics: string | null;
  fiscal_year_end_month: number;
  country_domicile: string;
  exchange: string;
  shares_outstanding: string | null;
  market_contexts: string[];
}

export interface FiscalPeriod {
  year: number;
  quarter: number | null;
  label: string;
}

export interface StatementLine {
  label: string;
  value: string;
  is_adjusted: boolean;
  adjustment_note: string | null;
  source: unknown | null;
  category?: string;
}

export interface ReclassifiedStatements {
  period: FiscalPeriod;
  income_statement: StatementLine[];
  balance_sheet: StatementLine[];
  cash_flow: StatementLine[];
  bs_checksum_pass: boolean;
  is_checksum_pass: boolean;
  cf_checksum_pass: boolean;
  checksum_notes: string[];
}

export interface InvestedCapital {
  period: FiscalPeriod;
  operating_assets: string;
  operating_liabilities: string;
  invested_capital: string;
  financial_assets: string;
  financial_liabilities: string;
  bank_debt?: string;
  lease_liabilities?: string;
  operating_working_capital?: string;
  equity_claims: string;
  nci_claims: string;
  cross_check_residual: string;
}

export interface NopatBridge {
  period: FiscalPeriod;
  ebitda: string;
  ebita: string | null;
  operating_income: string | null;
  operating_income_sustainable: string | null;
  non_recurring_operating_items: string;
  depreciation: string;
  amortisation: string;
  operating_taxes: string;
  nopat: string;
  nopat_reported: string | null;
  financial_income: string;
  financial_expense: string;
  non_operating_items: string;
  reported_net_income: string;
}

export interface KeyRatios {
  period: FiscalPeriod;
  roic: string | null;
  roic_reported: string | null;
  roic_adj_leases: string | null;
  roe: string | null;
  ros: string | null;
  operating_margin: string | null;
  sustainable_operating_margin: string | null;
  ebitda_margin: string | null;
  net_debt_ebitda: string | null;
  capex_revenue: string | null;
  dso: string | null;
  dpo: string | null;
  dio: string | null;
  sector_specific?: Record<string, string>;
}

export interface AnalysisDerived {
  invested_capital_by_period: InvestedCapital[];
  nopat_bridge_by_period: NopatBridge[];
  ratios_by_period: KeyRatios[];
  capital_allocation: unknown | null;
  dupont_decomposition: unknown | null;
  cf_quality_analysis: unknown | null;
  unit_economics: unknown | null;
}

export interface AdjustmentsApplied {
  module_a_taxes: unknown[];
  module_b_provisions: unknown[];
  module_c_leases: unknown[];
  module_d_pensions: unknown[];
  module_d_note_decompositions: Record<string, LineDecomposition>;
  module_d_coverage: unknown | null;
  module_e_sbc: unknown[];
  module_f_capitalize: unknown[];
  patches: unknown[];
  decision_log: string[];
  estimates_log: string[];
}

export interface LineDecomposition {
  parent_line: string;
  sub_items: SubItem[];
  unallocated_residual: string | null;
  source_note?: string | null;
}

export interface SubItem {
  label: string;
  amount: string;
  source_note?: string | null;
  category?: string | null;
}

export interface ValidationResults {
  universal_checksums: ValidationResult[];
  profile_specific_checksums: ValidationResult[];
  confidence_rating: string;
  blocking_issues: string[];
}

export interface ValidationResult {
  check_id: string;
  name: string;
  status: string;
  detail: string;
  blocking: boolean;
}

export interface VintageAndCascade {
  vintage_tags: unknown[];
  cascade_log: unknown[];
}

export interface MethodologyMetadata {
  extraction_system_version: string;
  profile_applied: string;
  protocols_activated: string[];
  sub_modules_active: Record<string, boolean>;
  tiers: Record<string, number>;
  llm_calls_summary: Record<string, number>;
  total_api_cost_usd: string | null;
  audit_status: string;
  preliminary_flag: Record<string, unknown> | null;
  source_document_type: string | null;
}

export interface NarrativeContext {
  key_themes: unknown[];
  risks_mentioned: unknown[];
  guidance_changes: unknown[];
  capital_allocation_signals: unknown[];
  forward_looking_statements: unknown[];
  source_extraction_period: string;
  source_document_type: string;
  extraction_timestamp: string;
}
