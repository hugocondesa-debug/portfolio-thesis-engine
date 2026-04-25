import type {
  CanonicalState,
  ReclassifiedStatements,
} from "@/lib/types/canonical";
import {
  formatCurrency,
  formatPercent,
  formatPercentDirect,
  parseDecimal,
} from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

/**
 * Section 8 — cost structure.
 *
 * Sprint 1A.1 — derived margins from raw IS line items.
 *
 * Sprint 1B.1 — pulls margin trajectory from
 * ``canonical.analysis.ratios_by_period`` (operating, sustainable operating,
 * EBITDA — already pre-computed by the engine, stored as percent strings),
 * adds an IS-composition table (each line as % of revenue), and computes a
 * lightweight operating-leverage indicator
 * (Δ operating margin ÷ Δ revenue growth) when 2+ periods are available.
 */
export function CostStructure({ canonical }: Props) {
  const statements = canonical.reclassified_statements;
  const ratios = canonical.analysis?.ratios_by_period ?? [];
  const currency = canonical.identity.reporting_currency;

  if (statements.length === 0) {
    return (
      <SectionShell title="Cost Structure" subtitle="Margin trajectory">
        <EmptySectionNote message="No income-statement periods available." />
      </SectionShell>
    );
  }

  const periods = statements.map((s) => s.period.label);
  const latest = statements[0];
  const leverage = computeOperatingLeverage(statements);

  return (
    <SectionShell
      title="Cost Structure"
      subtitle="Margin trajectory + operating expense composition"
    >
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="sticky left-0 bg-muted/30 px-3 py-2">Margin</th>
              {periods.map((p) => (
                <th key={p} className="px-3 py-2 text-right font-mono">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <MarginRow
              label="Operating margin (reported)"
              values={ratios.map((r) => r.operating_margin)}
            />
            <MarginRow
              label="Operating margin (sustainable)"
              values={ratios.map((r) => r.sustainable_operating_margin)}
              indent
            />
            <MarginRow
              label="EBITDA margin"
              values={ratios.map((r) => r.ebitda_margin)}
              emphasize
            />
          </tbody>
        </table>
      </div>

      {leverage !== null ? (
        <div className="mt-4 rounded-md bg-muted/30 p-3 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            Operating leverage indicator (latest period):
          </span>{" "}
          <span className="font-mono tabular-nums">
            {leverage.toFixed(2)}× (
            {leverage > 1 ? "high" : leverage < 0.5 ? "low" : "moderate"})
          </span>
          <p className="mt-1 text-xs text-muted-foreground">
            Δ operating margin ÷ Δ revenue growth. Values above 1× suggest a
            fixed-cost-intensive cost base where revenue swings amplify margin
            moves.
          </p>
        </div>
      ) : null}

      <div className="mt-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Income statement composition — {latest.period.label}
        </h3>
        <ISBreakdown statement={latest} currency={currency} />
      </div>
    </SectionShell>
  );
}

function ISBreakdown({
  statement,
  currency,
}: {
  statement: ReclassifiedStatements;
  currency: string;
}) {
  const items = statement.income_statement;
  const revenue = items.find((i) => i.label.toLowerCase() === "revenue");
  const revenueValue = revenue ? parseDecimal(revenue.value) : 0;

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Line item</th>
            <th className="px-3 py-2 text-right font-mono">Value</th>
            <th className="px-3 py-2 text-right font-mono">% of revenue</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const value = parseDecimal(item.value);
            const pctOfRevenue =
              !Number.isNaN(value) && revenueValue !== 0
                ? value / revenueValue
                : null;
            return (
              <tr key={item.label} className="border-t border-border">
                <td className="px-3 py-2">
                  {item.label}
                  {item.is_adjusted ? (
                    <span
                      className="ml-2 rounded bg-amber-500/20 px-1 text-xs font-mono text-amber-700 dark:text-amber-400"
                      title={item.adjustment_note ?? "Adjusted"}
                    >
                      adj
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatCurrency(item.value, { currency, compact: true })}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {pctOfRevenue !== null ? formatPercent(pctOfRevenue, 1) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MarginRow({
  label,
  values,
  emphasize = false,
  indent = false,
}: {
  label: string;
  values: (string | null)[];
  emphasize?: boolean;
  indent?: boolean;
}) {
  return (
    <tr
      className={`border-t border-border ${emphasize ? "bg-muted/20 font-semibold" : ""}`}
    >
      <td
        className={`sticky left-0 bg-card px-3 py-2 ${indent ? "pl-8" : ""}`}
      >
        {label}
      </td>
      {values.map((v, i) => (
        <td key={i} className="px-3 py-2 text-right font-mono tabular-nums">
          {v === null ? "—" : formatPercentDirect(v, 2)}
        </td>
      ))}
    </tr>
  );
}

function computeOperatingLeverage(
  statements: ReclassifiedStatements[],
): number | null {
  if (statements.length < 2) return null;
  const latest = statements[0];
  const prior = statements[1];

  const findValue = (
    s: ReclassifiedStatements,
    candidates: string[],
  ): number | null => {
    const targets = candidates.map((c) => c.toLowerCase());
    for (const line of s.income_statement) {
      if (targets.includes(line.label.toLowerCase())) {
        const v = parseDecimal(line.value);
        return Number.isNaN(v) ? null : v;
      }
    }
    return null;
  };

  const revLatest = findValue(latest, ["revenue", "total revenue", "sales"]);
  const revPrior = findValue(prior, ["revenue", "total revenue", "sales"]);
  if (
    revLatest === null ||
    revPrior === null ||
    revPrior === 0 ||
    revLatest === 0
  ) {
    return null;
  }

  const revGrowth = (revLatest - revPrior) / revPrior;
  if (Math.abs(revGrowth) < 0.001) return null;

  const opLabels = [
    "operating profit",
    "operating income",
    "profit from operations",
    "ebit",
  ];
  const oiLatest = findValue(latest, opLabels);
  const oiPrior = findValue(prior, opLabels);
  if (oiLatest === null || oiPrior === null) return null;

  const omLatest = oiLatest / revLatest;
  const omPrior = oiPrior / revPrior;
  const omChange = omLatest - omPrior;

  return omChange / revGrowth;
}

