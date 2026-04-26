"use client";

import { useState } from "react";
import type {
  Adjustment,
  AdjustmentsByModule,
  ConfidenceLevel,
  ModuleCategory,
} from "@/lib/types/adjustments";
import {
  ADJUSTMENT_LIST_MODULES,
  MODULE_LABELS,
  countModuleEntries,
  getAdjustmentsForModule,
} from "@/lib/types/adjustments";
import type { CanonicalState } from "@/lib/types/canonical";
import type { ValuationSnapshot } from "@/lib/types/valuation";
import { formatCurrency, formatDate } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  canonical: CanonicalState;
  valuation: ValuationSnapshot | null;
}

interface ModuleSummaryEntry {
  category: ModuleCategory;
  label: string;
  description: string;
  count: number;
}

/**
 * Section 16 — Audit / Provenance.
 *
 * Sprint 1C — surfaces the 11-module canonical adjustments dictionary as
 * an accordion. Modules with proper :class:`Adjustment[]` shape (Module
 * A/B/C/D-pensions/E/F/patches) render full descriptions and source
 * documents; the four special-shape modules (note decompositions, segment
 * coverage, decision/estimates logs) get tailored renderers so callers
 * still see the count and contents.
 *
 * Pipeline run timeline (per-stage durations, statuses) requires the
 * Sprint 0.2 backend addition of ``/api/tickers/{ticker}/runs``; until
 * then, this section combines canonical/valuation metadata as the audit
 * trail header.
 */
export function AuditProvenance({ canonical, valuation }: Props) {
  const adjustments = canonical.adjustments as unknown as AdjustmentsByModule;

  const modulesSummary: ModuleSummaryEntry[] = Object.entries(MODULE_LABELS).map(
    ([category, info]) => {
      const cat = category as ModuleCategory;
      return {
        category: cat,
        ...info,
        count: countModuleEntries(adjustments, cat),
      };
    },
  );

  const totalAdjustments = modulesSummary.reduce((sum, m) => sum + m.count, 0);

  return (
    <SectionShell
      title="Audit / Provenance"
      subtitle={`${totalAdjustments} adjustments across 11 module categories · pipeline trace`}
    >
      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Pipeline trace
        </h3>
        <PipelineSummary canonical={canonical} valuation={valuation} />
      </div>

      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Module adjustments trail
        </h3>
        <ModulesAccordion
          modules={modulesSummary}
          adjustments={adjustments}
          canonical={canonical}
        />
      </div>

      <div>
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Source documents
        </h3>
        <SourceDocuments
          canonicalSources={canonical.source_documents ?? []}
          valuationSources={valuation?.source_documents ?? []}
        />
      </div>

      <p className="mt-6 text-xs text-muted-foreground">
        Detailed pipeline run timeline (per-stage durations, statuses, log
        entries) will be available when Sprint 0.2 backend exposes{" "}
        <code className="rounded bg-muted px-1 py-0.5 font-mono">
          /api/tickers/&#123;ticker&#125;/runs
        </code>
        .
      </p>
    </SectionShell>
  );
}

function PipelineSummary({
  canonical,
  valuation,
}: {
  canonical: CanonicalState;
  valuation: ValuationSnapshot | null;
}) {
  return (
    <div className="rounded-md border border-border p-4">
      <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        <dt className="text-muted-foreground">Extraction ID</dt>
        <dd className="font-mono text-xs">{canonical.extraction_id}</dd>

        <dt className="text-muted-foreground">Extraction date</dt>
        <dd className="font-mono text-xs">
          {formatDate(canonical.extraction_date)}
        </dd>

        <dt className="text-muted-foreground">As-of date</dt>
        <dd className="font-mono text-xs">{canonical.as_of_date}</dd>

        <dt className="text-muted-foreground">Extraction system</dt>
        <dd className="font-mono text-xs">
          {canonical.methodology?.extraction_system_version ?? "—"}
        </dd>

        {valuation ? (
          <>
            <dt className="text-muted-foreground">Valuation snapshot</dt>
            <dd className="font-mono text-xs">{valuation.snapshot_id}</dd>

            <dt className="text-muted-foreground">Valuation generated</dt>
            <dd className="font-mono text-xs">{formatDate(valuation.created_at)}</dd>

            <dt className="text-muted-foreground">Forecast system</dt>
            <dd className="font-mono text-xs">
              {valuation.forecast_system_version ?? "—"}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function ModulesAccordion({
  modules,
  adjustments,
  canonical,
}: {
  modules: ModuleSummaryEntry[];
  adjustments: AdjustmentsByModule;
  canonical: CanonicalState;
}) {
  const currency = canonical.identity.reporting_currency;

  return (
    <div className="space-y-2">
      {modules.map((module) => (
        <ModuleCard
          key={module.category}
          module={module}
          adjustments={adjustments}
          currency={currency}
        />
      ))}
    </div>
  );
}

function ModuleCard({
  module,
  adjustments,
  currency,
}: {
  module: ModuleSummaryEntry;
  adjustments: AdjustmentsByModule;
  currency: string;
}) {
  const [open, setOpen] = useState(false);
  const empty = module.count === 0;

  return (
    <div
      className={`rounded-md border border-border ${empty ? "opacity-50" : ""}`}
    >
      <button
        type="button"
        onClick={() => !empty && setOpen(!open)}
        disabled={empty}
        className={`flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left ${
          !empty ? "hover:bg-muted/30" : ""
        }`}
      >
        <div className="flex flex-1 flex-wrap items-baseline gap-3">
          <span className="font-mono text-sm font-semibold">{module.label}</span>
          <span className="text-xs text-muted-foreground">
            {module.description}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs">
            {module.count} {module.count === 1 ? "entry" : "entries"}
          </span>
          {!empty ? (
            <span className="text-muted-foreground">{open ? "▲" : "▼"}</span>
          ) : null}
        </div>
      </button>

      {open && !empty ? (
        <div className="border-t border-border p-3">
          <ModuleBody
            category={module.category}
            adjustments={adjustments}
            currency={currency}
          />
        </div>
      ) : null}
    </div>
  );
}

function ModuleBody({
  category,
  adjustments,
  currency,
}: {
  category: ModuleCategory;
  adjustments: AdjustmentsByModule;
  currency: string;
}) {
  // Proper Adjustment[] modules
  if (ADJUSTMENT_LIST_MODULES.includes(category)) {
    const list = getAdjustmentsForModule(adjustments, category);
    return (
      <div className="space-y-2">
        {list.map((adj, idx) => (
          <AdjustmentEntry key={idx} adjustment={adj} currency={currency} />
        ))}
      </div>
    );
  }

  // Special-shape modules
  if (category === "module_d_note_decompositions") {
    const dict = adjustments.module_d_note_decompositions ?? {};
    return <NoteDecompositionsView entries={dict} />;
  }
  if (category === "module_d_coverage") {
    const value = adjustments.module_d_coverage;
    return <RawJsonView value={value} />;
  }
  if (category === "decision_log") {
    return <StringLogView lines={adjustments.decision_log ?? []} />;
  }
  if (category === "estimates_log") {
    return <StringLogView lines={adjustments.estimates_log ?? []} />;
  }
  return null;
}

function NoteDecompositionsView({
  entries,
}: {
  entries: Record<string, unknown>;
}) {
  const keys = Object.keys(entries);
  return (
    <div className="space-y-1 text-xs">
      <p className="text-muted-foreground">
        IS/BS/CF lines reclassified from financial statement notes:
      </p>
      <ul className="list-disc pl-5">
        {keys.map((key) => (
          <li key={key} className="font-mono">
            {key}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RawJsonView({ value }: { value: unknown }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function StringLogView({ lines }: { lines: string[] }) {
  return (
    <ul className="space-y-1 text-xs">
      {lines.map((line, idx) => (
        <li key={idx} className="rounded border border-border bg-background p-2 font-mono">
          {line}
        </li>
      ))}
    </ul>
  );
}

function AdjustmentEntry({
  adjustment,
  currency,
}: {
  adjustment: Adjustment;
  currency: string;
}) {
  const periods = adjustment.affected_periods.map((p) => p.label).join(", ");

  return (
    <div className="rounded border border-border bg-background p-3 text-sm">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-mono text-xs font-semibold">
          {adjustment.module}
        </span>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">{periods}</span>
          <ConfidenceBadge confidence={adjustment.source.confidence} />
        </div>
      </div>

      <p className="mb-1 text-sm font-medium">{adjustment.description}</p>
      <p className="mb-2 text-xs text-muted-foreground">{adjustment.rationale}</p>

      <div className="flex flex-wrap items-baseline justify-between gap-3 text-xs">
        <span className="text-muted-foreground">
          Source:{" "}
          <code className="font-mono">{adjustment.source.document}</code>
          {adjustment.source.page ? ` (p. ${adjustment.source.page})` : ""}
        </span>
        <span className="font-mono tabular-nums font-semibold">
          {formatCurrency(adjustment.amount, { currency, compact: true })}
        </span>
      </div>
    </div>
  );
}

// Sprint QA — same explanatory tooltips as the source panel, kept in
// sync via this local copy (the audit accordion uses the narrower
// ``ConfidenceLevel`` triplet — no DERIVED — because raw adjustments are
// always one of the three reported origins).
const CONFIDENCE_DESCRIPTIONS: Record<ConfidenceLevel, string> = {
  REPORTED:
    "Value taken directly from the source document without modification.",
  ESTIMATED:
    "Value computed using estimation methodology where direct figures are unavailable.",
  INFERRED:
    "Value derived from indirect signals; manual review recommended.",
};

function ConfidenceBadge({ confidence }: { confidence: ConfidenceLevel }) {
  const styles: Record<ConfidenceLevel, string> = {
    REPORTED: "border-positive/30 bg-positive/10 text-positive",
    ESTIMATED: "border-amber-500/30 bg-amber-500/10 text-amber-600",
    INFERRED: "border-destructive/30 bg-destructive/10 text-destructive",
  };
  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-xs ${styles[confidence]}`}
      title={CONFIDENCE_DESCRIPTIONS[confidence]}
    >
      {confidence}
    </span>
  );
}

function SourceDocuments({
  canonicalSources,
  valuationSources,
}: {
  canonicalSources: string[];
  valuationSources: string[];
}) {
  const allSources = Array.from(
    new Set([...canonicalSources, ...valuationSources]),
  );

  if (allSources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No source documents registered.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {allSources.map((source, idx) => (
        <div key={idx} className="rounded-md border border-border p-3 text-sm">
          <div className="flex items-baseline justify-between gap-2">
            <code className="font-mono text-sm">{source}</code>
            <SourceTags
              inCanonical={canonicalSources.includes(source)}
              inValuation={valuationSources.includes(source)}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function SourceTags({
  inCanonical,
  inValuation,
}: {
  inCanonical: boolean;
  inValuation: boolean;
}) {
  return (
    <div className="flex gap-1">
      {inCanonical ? (
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
          canonical
        </span>
      ) : null}
      {inValuation ? (
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
          valuation
        </span>
      ) : null}
    </div>
  );
}
