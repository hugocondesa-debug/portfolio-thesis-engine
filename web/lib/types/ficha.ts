/**
 * Ficha shape returned by `/api/tickers/{ticker}/ficha`.
 * Mirrors PTE `Ficha` (composed summary for portfolio view).
 */

import type { CompanyIdentity } from "./canonical";

export interface Ficha {
  version: number;
  created_at: string;
  created_by: string;
  previous_version: string | null;
  ticker: string;
  identity: CompanyIdentity;
  thesis: string | null;
  current_extraction_id: string;
  current_valuation_snapshot_id: string;
  position: PositionDetails | null;
  conviction: ConvictionScores;
  monitorables: Monitorable[];
  tags: string[];
  market_contexts: MarketContext[];
  snapshot_age_days: number | null;
  is_stale: boolean;
  next_earnings_expected: string | null;
  narrative_summary: NarrativeSummary | null;
}

export interface PositionDetails {
  shares: string;
  cost_basis: string;
  entry_date: string;
  notes: string | null;
}

export interface ConvictionScores {
  forecast: string;
  valuation: string;
  asymmetry: string;
  timing_risk: string;
  liquidity_risk: string;
  governance_risk: string;
}

export interface Monitorable {
  metric: string;
  threshold?: string | null;
  direction?: string | null;
  rationale?: string | null;
  [key: string]: unknown;
}

export interface MarketContext {
  market: string;
  currency: string;
  share_price: string | null;
  market_cap: string | null;
  shares_outstanding: string | null;
  source: string | null;
  as_of_date: string | null;
  [key: string]: unknown;
}

export interface NarrativeSummary {
  themes: string[];
  risks: string[];
  guidance: string[];
  capital_allocation: string[];
  forward_looking: string[];
}
