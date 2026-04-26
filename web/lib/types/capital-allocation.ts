/**
 * Capital allocation YAML shape, parsed via ``js-yaml`` in the frontend.
 *
 * Sprint 1B.2 — backend is frozen for this sprint, so the page fetches the
 * raw YAML through the existing ``/api/tickers/{ticker}/yamls/{name}``
 * proxy and parses with ``js-yaml`` using ``JSON_SCHEMA`` (so ISO dates
 * stay as strings, not ``Date`` objects).
 *
 * Numeric fields here are JSON numbers (capital_allocation YAML doesn't use
 * the Decimal-as-string convention seen in canonical / valuation outputs).
 */

export interface CapitalAllocation {
  target_ticker: string;
  company_name: string;
  last_updated: string;
  generated_by: string;
  source_documents: string[];
  evidence_sources: EvidenceSource[];
  policies: CapitalAllocationPolicies;
  historical_context: HistoricalContext;
}

export type EvidenceCategory =
  | "DIVIDEND"
  | "BUYBACK"
  | "DEBT"
  | "MA"
  | "EQUITY_ISSUANCE"
  | "CAPEX";

export interface EvidenceSource {
  category: EvidenceCategory | string;
  document: string;
  location: string;
  disclosure: string;
  date: string;
}

export type ConfidenceLevel = "LOW" | "MEDIUM" | "HIGH";

export interface CapitalAllocationPolicies {
  dividend_policy: DividendPolicy;
  buyback_policy: BuybackPolicy;
  debt_policy: DebtPolicy;
  ma_policy: MAPolicy;
  share_issuance_policy: ShareIssuancePolicy;
}

export interface DividendPolicy {
  type: "PAYOUT_RATIO" | "FIXED" | "GROWTH" | "ZERO" | string;
  payout_ratio?: number;
  growth_with_ni?: boolean;
  rationale: string;
  confidence: ConfidenceLevel;
  evidence_refs: number[];
}

export interface BuybackPolicy {
  type: "CONDITIONAL" | "REGULAR" | "OPPORTUNISTIC" | "ZERO" | string;
  condition?: string;
  annual_amount_if_condition_met?: number;
  rationale: string;
  confidence: ConfidenceLevel;
  evidence_refs: number[];
}

export interface DebtPolicy {
  type:
    | "MAINTAIN_ZERO"
    | "TARGET_LEVERAGE"
    | "OPPORTUNISTIC"
    | "MAX_GROWTH"
    | string;
  current_debt?: number;
  target_leverage?: number;
  alternative_for_ma?: Record<string, unknown>;
  rationale: string;
  confidence: ConfidenceLevel;
  evidence_refs: number[];
}

export interface MAPolicy {
  type:
    | "OPPORTUNISTIC"
    | "PROGRAMMATIC"
    | "TRANSFORMATIVE"
    | "ZERO"
    | string;
  annual_deployment_target?: number;
  timing_uncertainty?: "LOW" | "MEDIUM" | "HIGH" | string;
  geography_focus?: string[];
  funding_source?: "CASH" | "DEBT" | "EQUITY" | "MIXED" | string;
  rationale: string;
  confidence: ConfidenceLevel;
  evidence_refs: number[];
}

export interface ShareIssuancePolicy {
  type:
    | "ZERO"
    | "ANTI_DILUTIVE"
    | "GROWTH_FUEL"
    | "OPPORTUNISTIC"
    | string;
  annual_dilution_rate?: number;
  rationale: string;
  confidence: ConfidenceLevel;
  evidence_refs: number[];
}

export interface HistoricalContext {
  recent_dividends_paid: DividendHistoryItem[];
  recent_buybacks_executed: BuybackHistoryItem[];
  debt_history: string;
  ma_history: string;
  capital_structure_notes: string;
  cash_evolution: CashEvolutionItem[];
  net_financial_position_notes: string;
}

export interface DividendHistoryItem {
  year: number;
  type: "final" | "interim" | "special" | string;
  amount_per_share: number;
  total: number;
  note?: string;
}

export interface BuybackHistoryItem {
  program: string;
  shares_bought: number;
  avg_price: number;
  price_range?: string;
  total: number;
  cancelled?: boolean;
  cancellation_date?: string;
}

export interface CashEvolutionItem {
  period: string;
  cash: number;
  net_cash: number;
}
