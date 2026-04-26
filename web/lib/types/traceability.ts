/**
 * DEEP traceability types — describe a "click any number → resolve source"
 * round trip across the data model.
 *
 * Sprint 1C — used by :mod:`lib/traceability/registry` and the
 * :func:`SourcePanel` drawer to surface source path, formula, adjustment
 * chain and cross-statement navigation hints for any displayed value.
 */

import type { DecimalString } from "./api";
import type { Adjustment, ModuleCategory } from "./adjustments";

export type DataRoot =
  | "canonical"
  | "valuation"
  | "forecast"
  | "ficha"
  | "capital_allocation"
  | "cross_check"
  | "peers";

export type ValueFormat =
  | "currency"
  | "percent_fraction"
  | "percent_direct"
  | "multiple"
  | "number"
  | "date"
  | "string";

export interface SourcePath {
  /** Full logical path inside the data model — used as a stable key. */
  logical: string;
  /** Top-level data root the field lives under. */
  root: DataRoot;
  /** Period label (``"FY2024"``) when the value is period-scoped. */
  period?: string;
  /** Field name (last meaningful segment of the path). */
  field: string;
  /** Display label (human-readable). */
  label: string;
  /** Raw value as stored on the wire. */
  value: DecimalString | null;
  /** Hint for how to format the value in the panel header. */
  format: ValueFormat;
}

export interface AdjustmentChain {
  field: string;
  affected_modules: ModuleCategory[];
  adjustments: Adjustment[];
  total_adjustment_amount: number | null;
}

export interface CrossStatementLink {
  target_section: string;
  target_row_label: string;
  target_period: string;
  description: string;
}

export type TraceabilityConfidence =
  | "REPORTED"
  | "ESTIMATED"
  | "INFERRED"
  | "DERIVED";

export interface TraceabilityResolution {
  source: SourcePath;
  adjustments: AdjustmentChain;
  cross_links: CrossStatementLink[];
  related_metrics: SourcePath[];
  documents: string[];
  formula?: string;
  confidence: TraceabilityConfidence;
}
