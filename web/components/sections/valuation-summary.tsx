import type { CanonicalState } from "@/lib/types/canonical";
import type { ScenarioResult, ValuationSnapshot } from "@/lib/types/valuation";
import { formatCurrency, formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot;
  canonical: CanonicalState;
}

/**
 * Sprint 1A.1 — reads E[V] / range from ``valuation.weighted``; per-scenario
 * fair value from ``scenario.targets.dcf_fcff_per_share``; converts the
 * percent-coded probability / IRR / upside strings (e.g. ``"25"`` ≡ 25%)
 * into fractions before passing to ``formatPercent``.
 */
export function ValuationSummary({ valuation, canonical }: Props) {
  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;
  const w = valuation.weighted;
  const upsideFraction = parseDecimal(w.upside_pct) / 100;

  return (
    <SectionShell
      title="Valuation Summary"
      subtitle={`Probability-weighted across ${valuation.scenarios.length} scenarios · method ${w.expected_value_method_used}`}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric
          label="E[V] per share"
          value={formatCurrency(w.expected_value, { currency, decimals: 2 })}
          highlight
        />
        <Metric
          label="P25 — P75 range"
          value={`${formatCurrency(w.fair_value_range_low, { currency, decimals: 2 })} — ${formatCurrency(w.fair_value_range_high, { currency, decimals: 2 })}`}
        />
        <Metric
          label="Market price"
          value={formatCurrency(valuation.market.price, { currency, decimals: 2 })}
          subtitle={valuation.market.price_date}
        />
        <Metric
          label="Upside"
          value={formatPercent(upsideFraction, 2)}
          tone={
            Number.isNaN(upsideFraction) || upsideFraction === 0
              ? "neutral"
              : upsideFraction > 0
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

      {w.weighted_irr_3y ? (
        <div className="mt-6 rounded-md bg-muted/40 p-3 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            Probability-weighted IRR (3y):
          </span>{" "}
          <span className="font-mono tabular-nums">
            {formatPercent(parseDecimal(w.weighted_irr_3y) / 100, 2)}
          </span>
        </div>
      ) : null}
    </SectionShell>
  );
}

function ScenariosTable({
  scenarios,
  currency,
}: {
  scenarios: ScenarioResult[];
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
            <th className="px-3 py-2 w-1/4">Probability</th>
            <th className="px-3 py-2 text-right">Fair value</th>
            <th className="px-3 py-2 text-right">IRR (3y)</th>
            <th className="px-3 py-2 text-right">IRR (5y)</th>
            <th className="px-3 py-2 text-right">Upside</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const probFraction = parseDecimal(s.probability) / 100;
            const upsideFraction =
              s.upside_pct !== null ? parseDecimal(s.upside_pct) / 100 : null;
            const irr3yFraction =
              s.irr_3y !== null ? parseDecimal(s.irr_3y) / 100 : null;
            const irr5yFraction =
              s.irr_5y !== null ? parseDecimal(s.irr_5y) / 100 : null;

            return (
              <tr key={s.label} className="border-t border-border">
                <td className="px-3 py-2 font-mono">{s.label}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded bg-muted">
                      <div
                        className="h-full bg-primary"
                        style={{
                          width: `${Math.min(probFraction * 100, 100)}%`,
                        }}
                      />
                    </div>
                    <span className="font-mono tabular-nums text-xs text-muted-foreground">
                      {(probFraction * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatCurrency(s.targets.dcf_fcff_per_share, {
                    currency,
                    decimals: 2,
                  })}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {irr3yFraction !== null
                    ? formatPercent(irr3yFraction, 2)
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {irr5yFraction !== null
                    ? formatPercent(irr5yFraction, 2)
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {upsideFraction !== null
                    ? formatPercent(upsideFraction, 2)
                    : "—"}
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
