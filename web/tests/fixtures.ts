/**
 * Hand-rolled fixtures matching the real on-the-wire shapes (Sprint 1A.1).
 *
 * Numbers track the live EuroEyes FY2024 audited snapshot:
 *   - E[V] HK$7.80, range HK$4.76 — HK$11.31, upside 194.15%
 *   - 3 scenarios (bear/base/bull), probabilities 25 / 50 / 25
 *   - WACC 8.12%, CoE 8.12%
 *   - audit_status surfaces from canonical.methodology.audit_status
 */

import type { TickerDetail, TickerSummary, YamlListItem } from "@/lib/types/api";
import type {
  CanonicalState,
  CompanyIdentity,
  ReclassifiedStatements,
} from "@/lib/types/canonical";
import type { Ficha } from "@/lib/types/ficha";
import type {
  ScenarioDrivers,
  ValuationSnapshot,
} from "@/lib/types/valuation";

// ----------------------------------------------------------------------
// Ticker summary / detail
// ----------------------------------------------------------------------
export const tickerSummaryFixture: TickerSummary = {
  ticker: "1846.HK",
  name: "EuroEyes International Eye Clinic Limited",
  profile: "P1",
  currency: "HKD",
  exchange: "HKEX",
  isin: null,
  has_extraction: true,
  has_valuation: true,
  has_forecast: true,
  has_ficha: true,
  latest_extraction_at: "2026-04-25T16:18:04Z",
  latest_valuation_at: "2026-04-25T16:18:04Z",
  latest_forecast_at: "2026-04-24T14:20:15Z",
};

export const tickerDetailFixture: TickerDetail = {
  ticker: "1846.HK",
  name: "EuroEyes International Eye Clinic Limited",
  profile: "P1",
  currency: "HKD",
  exchange: "HKEX",
  isin: null,
  extraction_path: null,
  valuation_path: null,
  forecast_path: null,
  ficha_path: null,
};

// ----------------------------------------------------------------------
// Canonical state
// ----------------------------------------------------------------------
export const identityFixture: CompanyIdentity = {
  ticker: "1846.HK",
  isin: null,
  name: "EuroEyes International Eye Clinic Limited",
  legal_name: null,
  reporting_currency: "HKD",
  profile: "P1",
  sector_gics: "Healthcare",
  industry_gics: null,
  fiscal_year_end_month: 12,
  country_domicile: "HK",
  exchange: "HKEX",
  shares_outstanding: "331885000",
  market_contexts: [],
};

const fy2024Statement: ReclassifiedStatements = {
  period: { year: 2024, quarter: null, label: "FY2024" },
  income_statement: [
    { label: "Revenue", value: "715682000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Cost of sales", value: "-429089000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Gross profit", value: "286593000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Operating profit", value: "115778000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Profit for the year", value: "84500000", is_adjusted: false, adjustment_note: null, source: null },
  ],
  balance_sheet: [
    { label: "Property, plant and equipment", value: "567413000", is_adjusted: false, adjustment_note: null, source: null, category: "non_current_assets" },
    { label: "Cash and bank balances", value: "653232000", is_adjusted: false, adjustment_note: null, source: null, category: "current_assets" },
    { label: "Total assets", value: "3700000000", is_adjusted: false, adjustment_note: null, source: null, category: "totals" },
  ],
  cash_flow: [
    { label: "Net cash from operating activities", value: "145000000", is_adjusted: false, adjustment_note: null, source: null, category: "operating" },
  ],
  bs_checksum_pass: true,
  is_checksum_pass: true,
  cf_checksum_pass: true,
  checksum_notes: [],
};

const fy2023Statement: ReclassifiedStatements = {
  period: { year: 2023, quarter: null, label: "FY2023" },
  income_statement: [
    { label: "Revenue", value: "714289000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Cost of sales", value: "-378768000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Gross profit", value: "335521000", is_adjusted: false, adjustment_note: null, source: null },
    { label: "Operating profit", value: "193600000", is_adjusted: true, adjustment_note: "Module B reclassification", source: null },
    { label: "Profit for the year", value: "131000000", is_adjusted: false, adjustment_note: null, source: null },
  ],
  balance_sheet: [
    { label: "Property, plant and equipment", value: "540000000", is_adjusted: false, adjustment_note: null, source: null, category: "non_current_assets" },
    { label: "Cash and bank balances", value: "600000000", is_adjusted: false, adjustment_note: null, source: null, category: "current_assets" },
    { label: "Total assets", value: "3500000000", is_adjusted: false, adjustment_note: null, source: null, category: "totals" },
  ],
  cash_flow: [
    { label: "Net cash from operating activities", value: "180000000", is_adjusted: false, adjustment_note: null, source: null, category: "operating" },
  ],
  bs_checksum_pass: true,
  is_checksum_pass: true,
  cf_checksum_pass: true,
  checksum_notes: [],
};

export const canonicalFixture: CanonicalState = {
  extraction_id: "1846-HK_FY2024_20260425161804",
  extraction_date: "2026-04-25T16:18:04Z",
  as_of_date: "2024-12-31",
  identity: identityFixture,
  reclassified_statements: [fy2024Statement, fy2023Statement],
  adjustments: {
    module_a_taxes: [],
    module_b_provisions: [],
    module_c_leases: [],
    module_d_pensions: [],
    module_d_note_decompositions: {},
    module_d_coverage: null,
    module_e_sbc: [],
    module_f_capitalize: [],
    patches: [],
    decision_log: [],
    estimates_log: [],
  },
  analysis: {
    invested_capital_by_period: [
      {
        period: { year: 2024, quarter: null, label: "FY2024" },
        operating_assets: "946203000",
        operating_liabilities: "155288000",
        invested_capital: "790915000",
        financial_assets: "653232000",
        financial_liabilities: "318433000",
        bank_debt: "0",
        lease_liabilities: "318433000",
        operating_working_capital: "-23948000",
        equity_claims: "1092965000",
        nci_claims: "32749000",
        cross_check_residual: "0",
      },
    ],
    nopat_bridge_by_period: [
      {
        period: { year: 2024, quarter: null, label: "FY2024" },
        ebitda: "227993000",
        ebita: "120638000",
        operating_income: "115779000",
        operating_income_sustainable: "92469000",
        non_recurring_operating_items: "23310000",
        non_recurring_items_detail: [
          {
            label: "Gains on fair value change of contingent consideration",
            value: "23145000",
            operational_classification: "non_operational",
            recurrence_classification: "non_recurring",
            action: "exclude",
            matched_rule: "regex:non_operational+non_recurring",
            rationale: "Module D default rule.",
            confidence: "high",
            source_page: null,
            needs_multi_year_validation: true,
          },
        ],
        depreciation: "107355000",
        amortisation: "4859000",
        operating_taxes: "23110000",
        nopat: "69359000",
        nopat_reported: "92669000",
        financial_income: "5000000",
        financial_expense: "8000000",
        non_operating_items: "0",
        reported_net_income: "84500000",
      },
    ],
    // Sprint 1B.1 — ratios are stored as **percent strings** (engine convention),
    // not fractions. ``"8.20"`` ≡ 8.20% — pipe through ``formatPercentDirect``.
    ratios_by_period: [
      {
        period: { year: 2024, quarter: null, label: "FY2024" },
        roic: "8.20",
        roic_reported: "10.17",
        roic_adj_leases: null,
        roe: "7.72",
        ros: null,
        operating_margin: "16.18",
        sustainable_operating_margin: "12.92",
        ebitda_margin: "31.86",
        // Multiple, NOT a percentage — pipe through ``formatMultiple``.
        net_debt_ebitda: "-1.47",
        capex_revenue: "11.23",
        dso: null,
        dpo: null,
        dio: null,
      },
    ],
    capital_allocation: null,
    dupont_decomposition: null,
    cf_quality_analysis: null,
    unit_economics: null,
  },
  quarterly: null,
  validation: {
    universal_checksums: [],
    profile_specific_checksums: [],
    confidence_rating: "HIGH",
    blocking_issues: [],
  },
  vintage: { vintage_tags: [], cascade_log: [] },
  methodology: {
    extraction_system_version: "1.5.16",
    profile_applied: "P1",
    protocols_activated: [],
    sub_modules_active: {},
    tiers: {},
    llm_calls_summary: {},
    total_api_cost_usd: null,
    audit_status: "audited",
    preliminary_flag: null,
    source_document_type: null,
  },
  narrative_context: null,
  source_documents: [],
};

// Convenience for audit-status tests — variant of the canonical fixture
// whose methodology declares preliminary status.
export const canonicalPreliminaryFixture: CanonicalState = {
  ...canonicalFixture,
  methodology: { ...canonicalFixture.methodology, audit_status: "preliminary" },
};

// ----------------------------------------------------------------------
// Valuation — real shape, FY2024 audited, 3-scenario
// ----------------------------------------------------------------------
const emptyDrivers: ScenarioDrivers = {
  revenue_cagr: null,
  terminal_growth: null,
  terminal_margin: null,
  terminal_roic: null,
  terminal_wacc: null,
  terminal_roe: null,
  terminal_payout: null,
  terminal_nim: null,
  terminal_cor_bps: null,
  terminal_cost_income: null,
  terminal_cet1: null,
  custom_drivers: {},
};

export const valuationFixture: ValuationSnapshot = {
  version: 1,
  created_at: "2026-04-25T16:18:04Z",
  created_by: "phase1.5.9",
  previous_version: null,
  snapshot_id: "1846-HK_20260425T161804Z",
  ticker: "1846.HK",
  company_name: "EuroEyes International Eye Clinic Limited",
  profile: "P1",
  valuation_date: "2026-04-25T16:18:04Z",
  based_on_extraction_id: "1846-HK_FY2024_20260425161804",
  based_on_extraction_date: "2026-04-25T16:18:04Z",
  market: {
    price: "2.65",
    price_date: "2026-02-10",
    shares_outstanding: "331885000",
    market_cap: "879494250",
    cost_of_equity: "8.12",
    wacc: "8.12",
    currency: "HKD",
  },
  scenarios: [
    {
      label: "bear",
      description: "Bear case",
      probability: "25",
      horizon_years: 3,
      drivers: { ...emptyDrivers, revenue_cagr: "2.0", terminal_growth: "1.5", terminal_margin: "10.0" },
      targets: { equity_value: "1570619152", dcf_fcff_per_share: "4.76" },
      irr_3y: "17.68",
      irr_5y: null,
      irr_decomposition: { fundamental: "2.00", rerating: "15.68", dividend: "0" },
      upside_pct: "62.96",
      survival_conditions: [],
      kill_signals: [],
      projection: [],
    },
    {
      label: "base",
      description: "Base case",
      probability: "50",
      horizon_years: 5,
      drivers: { ...emptyDrivers, revenue_cagr: "8.0", terminal_growth: "2.5", terminal_margin: "16.0" },
      targets: { equity_value: "2587766250", dcf_fcff_per_share: "7.80" },
      irr_3y: "27.22",
      irr_5y: null,
      irr_decomposition: { fundamental: "8.00", rerating: "19.22", dividend: "0" },
      upside_pct: "194.34",
      survival_conditions: [],
      kill_signals: [],
      projection: [],
    },
    {
      label: "bull",
      description: "Bull case",
      probability: "25",
      horizon_years: 5,
      drivers: { ...emptyDrivers, revenue_cagr: "13.0", terminal_growth: "3.0", terminal_margin: "22.0" },
      targets: { equity_value: "3753687850", dcf_fcff_per_share: "11.31" },
      irr_3y: "62.45",
      irr_5y: null,
      irr_decomposition: { fundamental: "13.00", rerating: "49.45", dividend: "0" },
      upside_pct: "326.79",
      survival_conditions: [],
      kill_signals: [],
      projection: [],
    },
  ],
  weighted: {
    expected_value: "7.80",
    expected_value_method_used: "DCF_FCFF",
    fair_value_range_low: "4.76",
    fair_value_range_high: "11.31",
    upside_pct: "194.15",
    asymmetry_ratio: "999",
    weighted_irr_3y: "37.32",
    weighted_irr_5y: null,
  },
  reverse: null,
  cross_checks: null,
  eps_bridge: null,
  catalysts: [],
  factor_exposures: [],
  scenario_response: null,
  sensitivities: [],
  conviction: {
    forecast: "medium",
    valuation: "medium",
    asymmetry: "medium",
    timing_risk: "medium",
    liquidity_risk: "medium",
    governance_risk: "medium",
  },
  guardrails: { categories: {}, overall: "PASS" },
  forecast_system_version: "phase1.5.9",
  source_documents: [],
  total_api_cost_usd: null,
};

// Convenience: valuation with reverse populated (for the populated-state branch).
export const valuationWithReverseFixture: ValuationSnapshot = {
  ...valuationFixture,
  reverse: { implied_revenue_growth: "0.12", implied_margin: "0.20" },
};

// ----------------------------------------------------------------------
// Ficha
// ----------------------------------------------------------------------
export const fichaFixture: Ficha = {
  version: 1,
  created_at: "2026-04-25T16:18:04Z",
  created_by: "system",
  previous_version: null,
  ticker: "1846.HK",
  identity: identityFixture,
  thesis: "Net-cash compounding M&A platform; market underprices European roll-up.",
  current_extraction_id: "1846-HK_FY2024_20260425161804",
  current_valuation_snapshot_id: "1846-HK_20260425T161804Z",
  position: null,
  conviction: {
    forecast: "medium",
    valuation: "medium",
    asymmetry: "medium",
    timing_risk: "medium",
    liquidity_risk: "medium",
    governance_risk: "medium",
  },
  monitorables: [],
  tags: [],
  market_contexts: [
    {
      market: "HK",
      currency: "HKD",
      share_price: "2.92",
      market_cap: "969182200",
      shares_outstanding: "331885000",
      source: "yfinance",
      as_of_date: "2026-04-24",
    },
  ],
  snapshot_age_days: 0,
  is_stale: false,
  next_earnings_expected: null,
  narrative_summary: null,
};

// ----------------------------------------------------------------------
// Yamls
// ----------------------------------------------------------------------
export const yamlListFixture: YamlListItem[] = [
  {
    name: "scenarios",
    filename: "scenarios.yaml",
    last_modified: "2026-04-23T19:24:00Z",
    size_bytes: 9673,
    versions_count: 2,
  },
  {
    name: "capital_allocation",
    filename: "capital_allocation.yaml",
    last_modified: "2026-04-24T13:06:13Z",
    size_bytes: 8734,
    versions_count: 0,
  },
];
