import type {
  CanonicalState,
  ReclassifiedStatements,
  StatementLine,
} from "@/lib/types/canonical";
import { formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

interface PeriodMargins {
  period: string;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
}

/**
 * Section 8 — cost structure.
 *
 * Margins per period derived from the line-array income statements.
 * Sprint 1B will add fixed/variable cost decomposition; for now we
 * focus on the trajectory of the three headline margins.
 */
export function CostStructure({ canonical }: Props) {
  const trajectories = orderedTrajectories(canonical.reclassified_statements);
  const latest = trajectories[trajectories.length - 1];

  return (
    <SectionShell
      title="Cost Structure"
      subtitle="Margin trajectory and cost composition"
    >
      {trajectories.length === 0 ? (
        <EmptySectionNote message="No income-statement periods available." />
      ) : (
        <>
          {latest ? (
            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
              <Metric
                label={`Gross margin (${latest.period})`}
                value={formatPercent(latest.grossMargin)}
              />
              <Metric
                label={`Operating margin (${latest.period})`}
                value={formatPercent(latest.operatingMargin)}
              />
              <Metric
                label={`Net margin (${latest.period})`}
                value={formatPercent(latest.netMargin)}
              />
            </div>
          ) : null}

          <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Margin trajectory
          </h3>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="sticky left-0 bg-muted/30 px-3 py-2">
                    Margin
                  </th>
                  {trajectories.map((t) => (
                    <th
                      key={t.period}
                      className="px-3 py-2 text-right font-mono"
                    >
                      {t.period}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <TrajectoryRow
                  label="Gross margin"
                  values={trajectories.map((t) => t.grossMargin)}
                />
                <TrajectoryRow
                  label="Operating margin"
                  values={trajectories.map((t) => t.operatingMargin)}
                  emphasize
                />
                <TrajectoryRow
                  label="Net margin"
                  values={trajectories.map((t) => t.netMargin)}
                />
              </tbody>
            </table>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            Sprint 1B will add fixed/variable decomposition and operating
            leverage indicators.
          </p>
        </>
      )}
    </SectionShell>
  );
}

function orderedTrajectories(
  statements: ReclassifiedStatements[],
): PeriodMargins[] {
  const ordered = [...statements].sort((a, b) => {
    if (a.period.year !== b.period.year) return a.period.year - b.period.year;
    return (a.period.quarter ?? 0) - (b.period.quarter ?? 0);
  });
  return ordered.map((s) => computeMargins(s));
}

function computeMargins(s: ReclassifiedStatements): PeriodMargins {
  const revenue = numericLine(s.income_statement, ["revenue", "total revenue", "sales", "turnover"]);
  if (revenue === null || revenue === 0) {
    return {
      period: s.period.label,
      grossMargin: null,
      operatingMargin: null,
      netMargin: null,
    };
  }
  const grossProfit = numericLine(s.income_statement, ["gross profit"]);
  const operatingIncome = numericLine(s.income_statement, [
    "operating profit",
    "operating income",
    "profit from operations",
  ]);
  const netIncome = numericLine(s.income_statement, [
    "profit for the year",
    "profit for the period",
    "net income",
    "net profit",
  ]);

  return {
    period: s.period.label,
    grossMargin: grossProfit === null ? null : grossProfit / revenue,
    operatingMargin:
      operatingIncome === null ? null : operatingIncome / revenue,
    netMargin: netIncome === null ? null : netIncome / revenue,
  };
}

function numericLine(
  lines: StatementLine[],
  candidates: string[],
): number | null {
  const targets = candidates.map((c) => c.toLowerCase());
  for (const line of lines) {
    if (targets.includes(line.label.toLowerCase())) {
      const v = parseDecimal(line.value);
      return Number.isNaN(v) ? null : v;
    }
  }
  return null;
}

function TrajectoryRow({
  label,
  values,
  emphasize = false,
}: {
  label: string;
  values: (number | null)[];
  emphasize?: boolean;
}) {
  return (
    <tr
      className={`border-t border-border ${emphasize ? "bg-muted/20 font-semibold" : ""}`}
    >
      <td className="sticky left-0 bg-card px-3 py-2">{label}</td>
      {values.map((v, i) => (
        <td
          key={i}
          className="px-3 py-2 text-right font-mono tabular-nums"
        >
          {v === null ? "—" : formatPercent(v, 2)}
        </td>
      ))}
    </tr>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold tabular-nums">
        {value}
      </div>
    </div>
  );
}
