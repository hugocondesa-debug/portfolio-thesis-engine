"use client";

import { useMemo, useState } from "react";
import type {
  CanonicalState,
  ReclassifiedStatements,
  StatementLine,
} from "@/lib/types/canonical";
import { formatCurrency } from "@/lib/utils/format";

type StatementTab = "is" | "bs" | "cf";

interface Props {
  canonical: CanonicalState;
}

/**
 * Section 4 — historical financials browser.
 *
 * The PTE canonical state stores three statements as **arrays of label /
 * value records** under each `reclassified_statements[].(income|balance|
 * cash_flow)`. We pivot that into a label-rows × period-columns grid
 * here so the analyst sees a familiar accountancy table. Periods are
 * ordered chronologically using ``period.year`` (and ``quarter`` when
 * present) to keep the most recent year on the right.
 */
export function HistoricalFinancials({ canonical }: Props) {
  const [tab, setTab] = useState<StatementTab>("is");
  const [showAdjustedOnly, setShowAdjustedOnly] = useState(false);

  const statements = useMemo(
    () => orderedStatements(canonical.reclassified_statements),
    [canonical.reclassified_statements],
  );
  const periods = statements.map((s) => s.period.label);
  const currency = canonical.identity.reporting_currency;

  const linesByLabel = useMemo(
    () => buildLineMatrix(statements, tab),
    [statements, tab],
  );

  const filteredLabels = showAdjustedOnly
    ? linesByLabel.labels.filter((label) =>
        statements.some((s) =>
          pickStatement(s, tab).some(
            (line) => line.label === label && line.is_adjusted,
          ),
        ),
      )
    : linesByLabel.labels;

  return (
    <section className="rounded-md border border-border bg-card p-6">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="font-mono text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Historical Financials
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {periods.length} period{periods.length === 1 ? "" : "s"} · canonical
            state {canonical.extraction_id}
          </p>
        </div>

        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={showAdjustedOnly}
            onChange={(e) => setShowAdjustedOnly(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <span className="text-muted-foreground">Adjusted lines only</span>
        </label>
      </div>

      <div className="mb-4 inline-flex rounded-md border border-border bg-card p-1 text-xs">
        <TabButton active={tab === "is"} onClick={() => setTab("is")}>
          Income Statement
        </TabButton>
        <TabButton active={tab === "bs"} onClick={() => setTab("bs")}>
          Balance Sheet
        </TabButton>
        <TabButton active={tab === "cf"} onClick={() => setTab("cf")}>
          Cash Flow
        </TabButton>
      </div>

      <FinancialTable
        labels={filteredLabels}
        periods={periods}
        matrix={linesByLabel.matrix}
        currency={currency}
      />
    </section>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-3 py-1.5 ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
    >
      {children}
    </button>
  );
}

function FinancialTable({
  labels,
  periods,
  matrix,
  currency,
}: {
  labels: string[];
  periods: string[];
  matrix: Map<string, Map<string, StatementLine>>;
  currency: string;
}) {
  if (labels.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No line items to display for this view.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-muted/30 px-3 py-2 min-w-[16rem]">
              Item
            </th>
            {periods.map((p) => (
              <th key={p} className="px-3 py-2 text-right font-mono">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labels.map((label) => {
            const rowMap = matrix.get(label);
            const isSubtotal = label.toLowerCase().includes("total")
              || label.toLowerCase().startsWith("net ")
              || label.toLowerCase().includes("operating profit")
              || label.toLowerCase().includes("gross profit");
            return (
              <tr
                key={label}
                className={`border-t border-border ${isSubtotal ? "bg-muted/20 font-semibold" : ""}`}
              >
                <td className="sticky left-0 bg-card px-3 py-2">{label}</td>
                {periods.map((p) => {
                  const line = rowMap?.get(p);
                  const value = line?.value;
                  const adjusted = line?.is_adjusted ?? false;
                  return (
                    <td
                      key={p}
                      className="px-3 py-2 text-right font-mono tabular-nums"
                      title={
                        adjusted
                          ? line?.adjustment_note ?? "Adjusted line"
                          : undefined
                      }
                    >
                      {value === undefined || value === null ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <span className={adjusted ? "underline decoration-dotted" : ""}>
                          {formatCurrency(value, { currency, compact: true })}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function orderedStatements(
  statements: ReclassifiedStatements[],
): ReclassifiedStatements[] {
  return [...statements].sort((a, b) => {
    if (a.period.year !== b.period.year) return a.period.year - b.period.year;
    const aq = a.period.quarter ?? 0;
    const bq = b.period.quarter ?? 0;
    return aq - bq;
  });
}

function pickStatement(
  statement: ReclassifiedStatements,
  tab: StatementTab,
): StatementLine[] {
  if (tab === "is") return statement.income_statement;
  if (tab === "bs") return statement.balance_sheet;
  return statement.cash_flow;
}

interface LineMatrix {
  labels: string[];
  matrix: Map<string, Map<string, StatementLine>>;
}

function buildLineMatrix(
  statements: ReclassifiedStatements[],
  tab: StatementTab,
): LineMatrix {
  // Preserve label order from the most recent period (rightmost column).
  const orderedLabels: string[] = [];
  const seen = new Set<string>();
  const matrix = new Map<string, Map<string, StatementLine>>();

  // Walk newest → oldest so the canonical row order follows the latest filing.
  const newestFirst = [...statements].reverse();
  for (const stmt of newestFirst) {
    for (const line of pickStatement(stmt, tab)) {
      if (!seen.has(line.label)) {
        seen.add(line.label);
        orderedLabels.push(line.label);
      }
      let row = matrix.get(line.label);
      if (!row) {
        row = new Map();
        matrix.set(line.label, row);
      }
      row.set(stmt.period.label, line);
    }
  }

  return { labels: orderedLabels, matrix };
}
