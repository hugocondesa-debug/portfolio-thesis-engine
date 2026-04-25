/**
 * API response types — wire formats from FastAPI in api/schemas/responses.py.
 *
 * Decimal values are returned as **strings** to preserve precision; never
 * coerce them with Number() for arithmetic. Use parseDecimal() in
 * lib/utils/format.ts for display only.
 */

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
}

export interface TickerSummary {
  ticker: string;
  name: string;
  profile: string;
  currency: string;
  exchange: string;
  isin: string | null;
  has_extraction: boolean;
  has_valuation: boolean;
  has_forecast: boolean;
  has_ficha: boolean;
  latest_extraction_at: string | null;
  latest_valuation_at: string | null;
  latest_forecast_at: string | null;
}

export interface TickerDetail {
  ticker: string;
  name: string;
  profile: string;
  currency: string;
  exchange: string;
  isin: string | null;
  extraction_path: string | null;
  valuation_path: string | null;
  forecast_path: string | null;
  ficha_path: string | null;
}

export interface YamlListItem {
  name: string;
  filename: string;
  last_modified: string;
  size_bytes: number;
  versions_count: number;
}

export interface YamlVersion {
  filename: string;
  modified_at: string;
  size_bytes: number;
}

export interface ValidationError {
  type: string;
  loc?: (string | number)[];
  message: string;
  input?: unknown;
}

export interface YamlUploadResult {
  success: boolean;
  validation_errors: ValidationError[] | null;
  backup_path: string | null;
  new_filename: string | null;
}

export interface ApiErrorBody {
  error?: string;
  detail?: string | YamlUploadResult | unknown;
}
