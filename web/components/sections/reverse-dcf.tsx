import type { ValuationSnapshot } from "@/lib/types/valuation";
import { formatPercent, formatMultiple } from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

/**
 * The PTE valuation snapshot keeps reverse-DCF outputs in a free-form
 * ``reverse`` block (today an empty object for most tickers). We render
 * whatever metrics are present and fall back to an empty-state note
 * otherwise — Sprint 1B is responsible for adding a richer layout once
 * the API ships a structured payload.
 */
interface Props {
  valuation: ValuationSnapshot;
}

export function ReverseDCF({ valuation }: Props) {
  const reverse = valuation.reverse;
  const entries = reverse ? Object.entries(reverse) : [];

  return (
    <SectionShell
      title="Reverse DCF"
      subtitle="Market-implied assumptions vs base scenario"
    >
      {entries.length === 0 ? (
        <EmptySectionNote message="No reverse-DCF block in the latest valuation snapshot. Run `pte reverse` to populate." />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {entries.map(([key, value]) => (
            <ImpliedMetric
              key={key}
              label={prettifyKey(key)}
              value={formatReverseValue(key, value)}
            />
          ))}
        </div>
      )}
    </SectionShell>
  );
}

function prettifyKey(key: string): string {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatReverseValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" || typeof value === "string") {
    if (key.includes("multiple")) return formatMultiple(value);
    if (key.includes("growth") || key.includes("margin") || key.includes("rate")) {
      return formatPercent(value);
    }
    return String(value);
  }
  return JSON.stringify(value);
}

function ImpliedMetric({ label, value }: { label: string; value: string }) {
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
