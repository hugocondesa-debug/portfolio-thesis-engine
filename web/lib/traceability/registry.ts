/**
 * DEEP traceability registry.
 *
 * Resolves "click any number → source path + adjustment chain + formula +
 * cross-statement links" for displayed values across sections 1-12.
 *
 * Design notes:
 *
 * - :data:`FIELD_TO_MODULES` is a hand-curated mapping from canonical
 *   field names to the Module A/B/C/D/E/F categories that derive them.
 *   Unknown fields return an empty chain (correct — raw extraction with
 *   no Module D involvement).
 * - :data:`CROSS_STATEMENT_LINKS` mirrors the conceptual derivation
 *   graph (e.g., ROIC depends on NOPAT and invested capital), used to
 *   power "navigate to source" jumps inside the panel.
 * - :data:`FORMULAS` documents the well-known derivation formula so the
 *   panel can show it alongside the value.
 * - :func:`inferConfidence` propagates the weakest confidence level
 *   from the underlying adjustments. ``DERIVED`` is the new bucket for
 *   metrics computed from REPORTED inputs (ROIC, ratios, etc.).
 */

import type {
  Adjustment,
  AdjustmentsByModule,
  ModuleCategory,
} from "@/lib/types/adjustments";
import { getAdjustmentsForModule } from "@/lib/types/adjustments";
import type { CanonicalState } from "@/lib/types/canonical";
import type {
  AdjustmentChain,
  CrossStatementLink,
  DataRoot,
  SourcePath,
  TraceabilityConfidence,
  TraceabilityResolution,
  ValueFormat,
} from "@/lib/types/traceability";

export interface BuildSourcePathParams {
  root: DataRoot;
  logical: string;
  field: string;
  label: string;
  period?: string;
  value: string | null;
  format: ValueFormat;
}

export function buildSourcePath(params: BuildSourcePathParams): SourcePath {
  return {
    logical: params.logical,
    root: params.root,
    period: params.period,
    field: params.field,
    label: params.label,
    value: params.value,
    format: params.format,
  };
}

const FIELD_TO_MODULES: Record<string, ModuleCategory[]> = {
  // NOPAT-related
  operating_income: [
    "module_a_taxes",
    "module_b_provisions",
    "module_c_leases",
    "module_e_sbc",
  ],
  operating_income_sustainable: [
    "module_a_taxes",
    "module_b_provisions",
    "module_c_leases",
    "module_d_note_decompositions",
    "module_e_sbc",
  ],
  ebitda: [
    "module_b_provisions",
    "module_c_leases",
    "module_d_note_decompositions",
  ],
  ebita: [
    "module_b_provisions",
    "module_c_leases",
    "module_d_note_decompositions",
  ],
  nopat: ["module_a_taxes", "module_b_provisions", "module_c_leases"],

  // Balance sheet items
  invested_capital: ["module_c_leases", "module_d_note_decompositions"],
  operating_assets: ["module_c_leases", "module_d_note_decompositions"],
  operating_liabilities: ["module_c_leases", "module_d_note_decompositions"],
  financial_assets: ["module_d_note_decompositions"],
  financial_liabilities: ["module_c_leases", "module_d_note_decompositions"],
  lease_liabilities: ["module_c_leases"],
  equity_claims: ["module_d_note_decompositions"],
  nci_claims: ["module_d_note_decompositions"],
  goodwill: ["module_b_provisions"],

  // Ratios
  operating_margin: [
    "module_a_taxes",
    "module_b_provisions",
    "module_c_leases",
  ],
  sustainable_operating_margin: [
    "module_a_taxes",
    "module_b_provisions",
    "module_c_leases",
    "module_d_note_decompositions",
  ],
  ebitda_margin: ["module_b_provisions", "module_c_leases"],
  roic: ["module_a_taxes", "module_b_provisions", "module_c_leases"],
  roic_reported: [],
  roic_adj_leases: ["module_c_leases"],
  roe: [],
  ros: ["module_b_provisions"],
  capex_revenue: [],
  net_debt_ebitda: ["module_c_leases"],

  // Cash flow
  fcff: [
    "module_a_taxes",
    "module_c_leases",
    "module_e_sbc",
    "module_f_capitalize",
  ],
  capex: ["module_f_capitalize"],
};

export function resolveAdjustmentChain(
  field: string,
  adjustments: AdjustmentsByModule,
  period?: string,
): AdjustmentChain {
  const affectedModules = FIELD_TO_MODULES[field] ?? [];
  const allAdjustments: Adjustment[] = [];

  for (const moduleName of affectedModules) {
    const moduleAdjustments = getAdjustmentsForModule(adjustments, moduleName);
    for (const adj of moduleAdjustments) {
      if (period) {
        const matches = adj.affected_periods.some((p) => p.label === period);
        if (!matches) continue;
      }
      allAdjustments.push(adj);
    }
  }

  const totalAmount = allAdjustments.reduce((sum, adj) => {
    const amount = parseFloat(adj.amount);
    return Number.isNaN(amount) ? sum : sum + amount;
  }, 0);

  return {
    field,
    affected_modules: affectedModules,
    adjustments: allAdjustments,
    total_adjustment_amount: allAdjustments.length > 0 ? totalAmount : null,
  };
}

const CROSS_STATEMENT_LINKS: Record<
  string,
  (period: string) => CrossStatementLink[]
> = {
  operating_income: (period) => [
    {
      target_section: "historical-financials",
      target_row_label: "Operating profit",
      target_period: period,
      description: "Income statement line",
    },
    {
      target_section: "economic-balance-sheet",
      target_row_label: "NOPAT bridge",
      target_period: period,
      description: "NOPAT derivation",
    },
  ],
  invested_capital: (period) => [
    {
      target_section: "economic-balance-sheet",
      target_row_label: "Invested capital",
      target_period: period,
      description: "Operating side decomposition",
    },
  ],
  operating_margin: (period) => [
    {
      target_section: "historical-financials",
      target_row_label: "Revenue",
      target_period: period,
      description: "Margin denominator",
    },
    {
      target_section: "historical-financials",
      target_row_label: "Operating profit",
      target_period: period,
      description: "Margin numerator",
    },
  ],
  roic: (period) => [
    {
      target_section: "economic-balance-sheet",
      target_row_label: "Invested capital",
      target_period: period,
      description: "ROIC denominator",
    },
    {
      target_section: "economic-balance-sheet",
      target_row_label: "NOPAT bridge",
      target_period: period,
      description: "ROIC numerator",
    },
  ],
  ebitda: (period) => [
    {
      target_section: "economic-balance-sheet",
      target_row_label: "NOPAT bridge",
      target_period: period,
      description: "EBITDA → EBITA → Operating income chain",
    },
  ],
};

export function resolveCrossStatementLinks(
  field: string,
  period?: string,
): CrossStatementLink[] {
  const resolver = CROSS_STATEMENT_LINKS[field];
  if (!resolver || !period) return [];
  return resolver(period);
}

const FORMULAS: Record<string, string> = {
  roic: "ROIC = NOPAT / Invested Capital",
  roic_reported:
    "ROIC (reported) = Operating income × (1 − tax rate) / Invested Capital",
  roic_adj_leases:
    "ROIC (lease-adj) = NOPAT (with leases) / Invested Capital (with lease assets)",
  roe: "ROE = Net Income / Average Equity",
  operating_margin: "Operating margin = Operating income / Revenue",
  sustainable_operating_margin:
    "Sustainable OM = Operating income (excl. non-recurring) / Revenue",
  ebitda_margin: "EBITDA margin = EBITDA / Revenue",
  net_debt_ebitda: "Net debt / EBITDA = (Total debt − Cash) / EBITDA",
  capex_revenue: "Capex / Revenue = Capex / Revenue",
  fcff: "FCFF = NOPAT + D&A − Capex − ΔNWC",
};

export function resolveFormula(field: string): string | undefined {
  return FORMULAS[field];
}

export function inferConfidence(
  _field: string,
  adjustments: Adjustment[],
): TraceabilityConfidence {
  if (adjustments.length === 0) return "REPORTED";
  const confidences = adjustments.map((a) => a.source.confidence);
  if (confidences.includes("INFERRED")) return "INFERRED";
  if (confidences.includes("ESTIMATED")) return "ESTIMATED";
  return "DERIVED";
}

/**
 * Top-level resolver — given a clicked source + canonical state, returns
 * everything the panel needs to render.
 */
export function resolveTraceability(
  source: SourcePath,
  canonical: CanonicalState,
): TraceabilityResolution {
  const adjustments = canonical.adjustments as unknown as AdjustmentsByModule;
  const chain = resolveAdjustmentChain(source.field, adjustments, source.period);
  const crossLinks = resolveCrossStatementLinks(source.field, source.period);
  const formula = resolveFormula(source.field);
  const confidence = inferConfidence(source.field, chain.adjustments);
  const documents = canonical.source_documents ?? [];

  return {
    source,
    adjustments: chain,
    cross_links: crossLinks,
    related_metrics: [],
    documents,
    formula,
    confidence,
  };
}
