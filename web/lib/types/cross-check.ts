/**
 * Cross-check log shape returned by ``/api/tickers/{ticker}/cross-check``.
 *
 * Per-metric comparison of canonical extraction vs external providers (FMP,
 * yfinance) with PASS/WARN/FAIL status against tunable thresholds.
 */

import type { DecimalString } from "./api";

export type CheckStatus = "PASS" | "WARN" | "FAIL";

export interface CrossCheckResponse {
  ticker: string;
  period: string;
  metrics: CrossCheckMetric[];
  overall_status: CheckStatus;
  blocking: boolean;
  generated_at: string;
  log_path: string;
  provider_errors: Record<string, unknown> | null;
}

export interface CrossCheckMetric {
  metric: string;
  extracted_value: DecimalString | null;
  fmp_value: DecimalString | null;
  yfinance_value: DecimalString | null;
  /** Decimal **fraction** (``"0.1033"`` ≡ 10.33%). */
  max_delta_pct: DecimalString | null;
  status: CheckStatus;
  notes: string;
}
