import type { CanonicalState } from "@/lib/types/canonical";
import type { ValuationSnapshot } from "@/lib/types/valuation";
import { formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot;
  canonical: CanonicalState;
}

/**
 * Sprint 1A.1 — reads ``valuation.market.{wacc, cost_of_equity}`` (the
 * authoritative path). Geographic-mix breakdown lives in WACC inputs and
 * is not yet persisted in the snapshot — surfaced as a follow-up.
 */
export function WaccBuildup({ valuation, canonical }: Props) {
  const wacc = parseDecimal(valuation.market.wacc) / 100;
  const coe = parseDecimal(valuation.market.cost_of_equity) / 100;
  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;

  return (
    <SectionShell
      title="WACC Build-up"
      subtitle="Cost of capital used in scenario discounting"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Metric label="Cost of equity" value={formatPercent(coe, 2)} />
        <Metric label="WACC" value={formatPercent(wacc, 2)} highlight />
        <Metric label="Currency" value={currency} />
      </div>

      <p className="mt-6 text-xs text-muted-foreground">
        Geographic mix breakdown, Damodaran inputs (Rf, ERP, CRP), and beta
        provenance will be exposed in Sprint 1B once the backend persists the
        full WACC build-up. The current snapshot only stores the aggregate
        cost of capital.
      </p>
    </SectionShell>
  );
}

function Metric({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-md border border-border p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tabular-nums ${highlight ? "text-2xl font-semibold" : "text-xl"}`}
      >
        {value}
      </div>
    </div>
  );
}
