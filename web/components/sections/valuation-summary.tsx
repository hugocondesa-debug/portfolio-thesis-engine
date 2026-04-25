import type { CanonicalState } from "@/lib/types/canonical";
import type { ValuationSnapshot, ValuationScenario } from "@/lib/types/valuation";
import { formatCurrency, formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot;
  canonical: CanonicalState;
}

export function ValuationSummary({ valuation, canonical }: Props) {
  const currency = valuation.market.currency || canonical.identity.reporting_currency;
  const weighted = valuation.weighted;
  const upside = weighted.upside_pct;
  const upsideNum = parseDecimal(upside);

  return (
    <SectionShell
      title="Valuation Summary"
      subtitle="Probability-weighted expected value across scenarios"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric
          label="E[V] per share"
          value={formatCurrency(weighted.expected_value, { currency, decimals: 2 })}
          highlight
        />
        <Metric
          label={`P25 — P75 range (${weighted.expected_value_method_used})`}
          value={`${formatCurrency(weighted.fair_value_range_low, { currency, decimals: 2 })} — ${formatCurrency(weighted.fair_value_range_high, { currency, decimals: 2 })}`}
        />
        <Metric
          label="Market price"
          value={formatCurrency(valuation.market.price, { currency, decimals: 2 })}
          subtitle={valuation.market.price_date}
        />
        <Metric
          label="Upside"
          value={formatPercent(upside)}
          tone={
            Number.isNaN(upsideNum) || upsideNum === 0
              ? "neutral"
              : upsideNum > 0
                ? "positive"
                : "negative"
          }
        />
      </div>

      <div className="mt-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Scenarios
        </h3>
        <ScenariosTable scenarios={valuation.scenarios} currency={currency} />
      </div>
    </SectionShell>
  );
}

function ScenariosTable({
  scenarios,
  currency,
}: {
  scenarios: ValuationScenario[];
  currency: string;
}) {
  const sorted = [...scenarios].sort(
    (a, b) => parseDecimal(b.probability) - parseDecimal(a.probability),
  );

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Scenario</th>
            <th className="px-3 py-2 w-1/3">Probability</th>
            <th className="px-3 py-2 text-right">Fair value</th>
            <th className="px-3 py-2 text-right">IRR (3y)</th>
            <th className="px-3 py-2 text-right">IRR (5y)</th>
            <th className="px-3 py-2 text-right">Upside</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const probPct = parseDecimal(s.probability);
            const probDisplay = Number.isNaN(probPct)
              ? "—"
              : `${(probPct > 1.5 ? probPct : probPct * 100).toFixed(0)}%`;
            const probWidth = Number.isNaN(probPct)
              ? 0
              : probPct > 1.5
                ? probPct
                : probPct * 100;
            const fvps = s.equity_bridge?.fair_value_per_share ?? s.targets?.fair_value_per_share ?? null;
            return (
              <tr key={s.label} className="border-t border-border">
                <td className="px-3 py-2 font-mono text-xs">{s.label}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded bg-muted">
                      <div
                        className="h-full bg-primary"
                        style={{ width: `${Math.min(probWidth, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono tabular-nums text-xs text-muted-foreground">
                      {probDisplay}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatCurrency(fvps, { currency, decimals: 2 })}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatPercent(s.irr_3y)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatPercent(s.irr_5y)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatPercent(s.upside_pct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Metric({
  label,
  value,
  subtitle,
  highlight = false,
  tone = "neutral",
}: {
  label: string;
  value: string;
  subtitle?: string;
  highlight?: boolean;
  tone?: "positive" | "negative" | "neutral";
}) {
  const toneClass = {
    positive: "text-positive",
    negative: "text-negative",
    neutral: "",
  }[tone];

  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tabular-nums ${highlight ? "text-2xl font-semibold" : "text-lg"} ${toneClass}`}
      >
        {value}
      </div>
      {subtitle ? (
        <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div>
      ) : null}
    </div>
  );
}
