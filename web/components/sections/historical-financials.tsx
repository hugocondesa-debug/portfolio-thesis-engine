"use client";

import { useMemo, useState } from "react";
import type {
  CanonicalState,
  ReclassifiedStatements,
  StatementLine,
} from "@/lib/types/canonical";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";

type StatementTab = "is" | "bs" | "cf";

interface Props {
  canonical: CanonicalState;
}

/**
 * Section 4 — historical financials browser.
 *
 * The PTE canonical state stores three statements as **arrays of label /
 * value records** under each ``reclassified_statements[].(income_statement|
 * balance_sheet|cash_flow)``. Sprint 1B.1 rewrites this section to:
 *
 * - keep periods in the engine's newest-first order (FY2024, FY2023, …),
 * - pivot line items into a label-rows × period-columns grid via a label
 *   map so the same accounting line aligns across periods,
 * - group BS / CF rows by their ``category`` field
 *   (``current_assets``/``operating``/etc.) — the IS preserves schema order
 *   because that order encodes the build-up (revenue → costs → operating
 *   profit → below-line),
 * - surface the per-period checksum status (``is_checksum_pass``,
 *   ``bs_checksum_pass``, ``cf_checksum_pass``) as badges,
 * - flag adjusted line items with a hover tooltip carrying the adjustment
 *   note,
 * - compute a YoY % against the preceding column when 2+ periods exist.
 */
export function HistoricalFinancials({ canonical }: Props) {
  const [tab, setTab] = useState<StatementTab>("is");
  const [showAdjustedOnly, setShowAdjustedOnly] = useState(false);

  const statements = canonical.reclassified_statements;
  const periods = statements.map((s) => s.period.label);
  const currency = canonical.identity.reporting_currency;

  const checksums = statements.map((s) => ({
    period: s.period.label,
    is: s.is_checksum_pass,
    bs: s.bs_checksum_pass,
    cf: s.cf_checksum_pass,
  }));

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

      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        {checksums.map((c) => {
          const pass = tab === "is" ? c.is : tab === "bs" ? c.bs : c.cf;
          return (
            <span
              key={c.period}
              className={`rounded border px-2 py-0.5 font-mono ${
                pass
                  ? "border-positive/30 bg-positive/10 text-positive"
                  : "border-destructive/30 bg-destructive/10 text-destructive"
              }`}
            >
              {c.period}: checksum {pass ? "PASS" : "FAIL"}
            </span>
          );
        })}
      </div>

      <FinancialTable
        statements={statements}
        accessor={(s) => pickStatement(s, tab)}
        periods={periods}
        currency={currency}
        showAdjustedOnly={showAdjustedOnly}
        groupBy={tab === "is" ? "schema_order" : "category"}
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

interface FinancialRow {
  label: string;
  category: string | null;
  values: Record<string, StatementLine | null>;
  anyAdjusted: boolean;
}

interface FinancialTableProps {
  statements: ReclassifiedStatements[];
  accessor: (s: ReclassifiedStatements) => StatementLine[];
  periods: string[];
  currency: string;
  showAdjustedOnly: boolean;
  groupBy: "category" | "schema_order";
}

function FinancialTable({
  statements,
  accessor,
  periods,
  currency,
  showAdjustedOnly,
  groupBy,
}: FinancialTableProps) {
  const rows = useMemo(() => {
    const labelMap = new Map<string, FinancialRow>();
    const orderedLabels: string[] = [];

    statements.forEach((stmt) => {
      const items = accessor(stmt);
      items.forEach((item) => {
        let entry = labelMap.get(item.label);
        if (!entry) {
          const values: Record<string, StatementLine | null> = {};
          periods.forEach((p) => {
            values[p] = null;
          });
          entry = {
            label: item.label,
            category: item.category ?? null,
            values,
            anyAdjusted: false,
          };
          labelMap.set(item.label, entry);
          orderedLabels.push(item.label);
        }
        entry.values[stmt.period.label] = item;
        if (item.is_adjusted) entry.anyAdjusted = true;
        if (!entry.category && item.category) entry.category = item.category;
      });
    });

    return orderedLabels
      .map((label) => labelMap.get(label))
      .filter((row): row is FinancialRow => row !== undefined);
  }, [statements, accessor, periods]);

  const filteredRows = showAdjustedOnly
    ? rows.filter((row) => row.anyAdjusted)
    : rows;

  const grouped = useMemo(() => {
    if (groupBy === "category") {
      const groupOrder: string[] = [];
      const groups = new Map<string, FinancialRow[]>();
      filteredRows.forEach((row) => {
        const cat = row.category ?? "Other";
        if (!groups.has(cat)) {
          groups.set(cat, []);
          groupOrder.push(cat);
        }
        groups.get(cat)!.push(row);
      });
      return groupOrder.map((cat) => ({
        category: cat,
        items: groups.get(cat)!,
      }));
    }
    return [{ category: "", items: filteredRows }];
  }, [filteredRows, groupBy]);

  if (filteredRows.length === 0) {
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
            {periods.length >= 2 ? (
              <th className="px-3 py-2 text-right font-mono">YoY %</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {grouped.map((group, groupIdx) => (
            <FinancialGroup
              key={`${groupIdx}-${group.category}`}
              category={group.category}
              items={group.items}
              periods={periods}
              currency={currency}
              colCount={periods.length + (periods.length >= 2 ? 2 : 1)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FinancialGroup({
  category,
  items,
  periods,
  currency,
  colCount,
}: {
  category: string;
  items: FinancialRow[];
  periods: string[];
  currency: string;
  colCount: number;
}) {
  return (
    <>
      {category ? (
        <tr className="bg-muted/40">
          <td
            colSpan={colCount}
            className="sticky left-0 bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase text-muted-foreground"
          >
            {category}
          </td>
        </tr>
      ) : null}
      {items.map((row) => (
        <FinancialRowView
          key={`${category}-${row.label}`}
          row={row}
          periods={periods}
          currency={currency}
        />
      ))}
    </>
  );
}

function FinancialRowView({
  row,
  periods,
  currency,
}: {
  row: FinancialRow;
  periods: string[];
  currency: string;
}) {
  const numericValues = periods.map((p) => {
    const item = row.values[p];
    return item ? parseDecimal(item.value) : null;
  });

  // Periods are newest-first per backend convention. YoY = (latest − prior) / |prior|.
  const yoy =
    numericValues.length >= 2 &&
    numericValues[0] !== null &&
    numericValues[1] !== null &&
    !Number.isNaN(numericValues[0]) &&
    !Number.isNaN(numericValues[1]) &&
    numericValues[1] !== 0
      ? (numericValues[0]! - numericValues[1]!) / Math.abs(numericValues[1]!)
      : null;

  const adjustmentNote =
    Object.values(row.values).find(
      (v) => v?.is_adjusted && v.adjustment_note,
    )?.adjustment_note ?? null;

  const isSubtotal =
    row.label.toLowerCase().includes("total") ||
    row.label.toLowerCase().startsWith("net ") ||
    row.label.toLowerCase().includes("operating profit") ||
    row.label.toLowerCase().includes("gross profit");

  return (
    <tr
      className={`border-t border-border hover:bg-muted/10 ${isSubtotal ? "bg-muted/20 font-semibold" : ""}`}
    >
      <td className="sticky left-0 bg-card px-3 py-2">
        <div className="flex items-center gap-2">
          <span>{row.label}</span>
          {row.anyAdjusted ? <AdjustedMarker note={adjustmentNote} /> : null}
        </div>
      </td>
      {periods.map((p) => {
        const item = row.values[p];
        return (
          <td
            key={p}
            className="px-3 py-2 text-right font-mono tabular-nums"
            title={
              item?.is_adjusted
                ? item.adjustment_note ?? "Adjusted line"
                : undefined
            }
          >
            {item ? (
              <span
                className={item.is_adjusted ? "underline decoration-dotted" : ""}
              >
                {formatCurrency(item.value, { currency, compact: true })}
              </span>
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </td>
        );
      })}
      {periods.length >= 2 ? (
        <td className="px-3 py-2 text-right font-mono tabular-nums text-xs">
          {yoy === null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <span
              className={
                yoy > 0
                  ? "text-positive"
                  : yoy < 0
                    ? "text-negative"
                    : "text-muted-foreground"
              }
            >
              {(yoy * 100).toFixed(1)}%
            </span>
          )}
        </td>
      ) : null}
    </tr>
  );
}

function AdjustedMarker({ note }: { note: string | null }) {
  return (
    <span
      className="rounded bg-amber-500/20 px-1 text-xs font-mono text-amber-700 dark:text-amber-400"
      title={note ?? "Adjusted by Module D"}
    >
      adj
    </span>
  );
}

function pickStatement(
  statement: ReclassifiedStatements,
  tab: StatementTab,
): StatementLine[] {
  if (tab === "is") return statement.income_statement;
  if (tab === "bs") return statement.balance_sheet;
  return statement.cash_flow;
}
