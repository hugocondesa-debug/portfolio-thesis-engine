/**
 * Canonical adjustments — DICT BY MODULE.
 *
 * The PTE engine groups adjustments under 11 module categories. Most are
 * lists of :class:`Adjustment` records. Four diverge from that shape and
 * are typed accordingly:
 *
 * - ``module_d_note_decompositions`` — dict keyed by IS/BS/CF line label
 * - ``module_d_coverage`` — dict (segment coverage diagnostics)
 * - ``decision_log`` — list of plain strings (audit trail)
 * - ``estimates_log`` — list of plain strings
 *
 * The :func:`getAdjustmentsForModule` helper coerces to ``Adjustment[]``
 * regardless of the underlying shape, so callers (registry, audit
 * accordion) can treat all 11 modules uniformly when only the proper
 * adjustments are relevant.
 */

import type { DecimalString } from "./api";
import type { FiscalPeriod } from "./canonical";

export type ConfidenceLevel = "REPORTED" | "ESTIMATED" | "INFERRED";

export interface Adjustment {
  module: string;
  description: string;
  amount: DecimalString;
  affected_periods: FiscalPeriod[];
  rationale: string;
  source: AdjustmentSource;
}

export interface AdjustmentSource {
  document: string;
  page: number | null;
  confidence: ConfidenceLevel;
  url: string | null;
  accessed: string | null;
}

/**
 * Real on-the-wire shape of ``canonical.adjustments``. Mirrors the engine
 * output rather than the optimistic spec assumption that all 11 keys are
 * lists of :class:`Adjustment`.
 */
export interface AdjustmentsByModule {
  module_a_taxes: Adjustment[];
  module_b_provisions: Adjustment[];
  module_c_leases: Adjustment[];
  module_d_pensions: Adjustment[];
  module_d_note_decompositions: Record<string, unknown>;
  module_d_coverage: Record<string, unknown> | unknown[] | null;
  module_e_sbc: Adjustment[];
  module_f_capitalize: Adjustment[];
  patches: Adjustment[];
  decision_log: string[];
  estimates_log: string[];
}

export type ModuleCategory = keyof AdjustmentsByModule;

/**
 * Modules whose values are ``Adjustment[]`` directly (not specials).
 */
export const ADJUSTMENT_LIST_MODULES: ReadonlyArray<ModuleCategory> = [
  "module_a_taxes",
  "module_b_provisions",
  "module_c_leases",
  "module_d_pensions",
  "module_e_sbc",
  "module_f_capitalize",
  "patches",
];

/**
 * Returns ``Adjustment[]`` for any module category, falling back to ``[]``
 * for the four special-shape modules. Used by the traceability registry
 * when assembling adjustment chains for a derived value.
 */
export function getAdjustmentsForModule(
  adjustments: AdjustmentsByModule,
  module: ModuleCategory,
): Adjustment[] {
  const value = adjustments[module];
  if (Array.isArray(value)) {
    if (value.length === 0) return [];
    if (typeof value[0] === "object" && value[0] !== null && "module" in value[0]) {
      return value as Adjustment[];
    }
    return [];
  }
  return [];
}

export interface ModuleSummary {
  category: ModuleCategory;
  label: string;
  description: string;
  count: number;
}

export const MODULE_LABELS: Record<
  ModuleCategory,
  { label: string; description: string }
> = {
  module_a_taxes: {
    label: "Module A — Taxes",
    description: "Operating tax rate normalization for NOPAT calculation",
  },
  module_b_provisions: {
    label: "Module B — Provisions",
    description:
      "Provisions and impairments classification (operating vs non-operating)",
  },
  module_c_leases: {
    label: "Module C — Leases",
    description: "Operating lease capitalization (IFRS 16 / ASC 842)",
  },
  module_d_pensions: {
    label: "Module D — Pensions",
    description: "Pension cost reclassification (service cost vs interest)",
  },
  module_d_note_decompositions: {
    label: "Module D — Note decompositions",
    description: "IS/BS/CF reclassifications from financial statement notes",
  },
  module_d_coverage: {
    label: "Module D — Segment coverage",
    description: "Segment data reconciliation across periods",
  },
  module_e_sbc: {
    label: "Module E — Stock-based compensation",
    description: "SBC capitalization treatment (operating vs financing)",
  },
  module_f_capitalize: {
    label: "Module F — R&D capitalization",
    description: "Research and development capitalization decisions",
  },
  patches: {
    label: "Manual patches",
    description: "Analyst-applied corrections to canonical extraction",
  },
  decision_log: {
    label: "Decision log",
    description: "Module-level decision audit trail",
  },
  estimates_log: {
    label: "Estimates log",
    description: "Estimation methodology log",
  },
};

/**
 * Counts the rendered entries inside a module slot regardless of its
 * underlying shape — list length for arrays, key count for dicts, 0 for
 * empty / null.
 */
export function countModuleEntries(
  adjustments: AdjustmentsByModule,
  module: ModuleCategory,
): number {
  const value = adjustments[module];
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}
