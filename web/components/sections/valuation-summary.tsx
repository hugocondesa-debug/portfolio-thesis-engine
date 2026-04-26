import type { CanonicalState } from "@/lib/types/canonical";
import type { ScenarioResult, ValuationSnapshot } from "@/lib/types/valuation";
import {
  formatCurrency,
  formatPercent,
  parseDecimal,
} from "@/lib/utils/format";
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
 *
 * Sprint 1B.1 — adds per-scenario expandable drawer with drivers and IRR
 * decomposition; renders ``∞`` for asymmetry ratios ≥ 999 (engine sentinel
 * for unbounded reward); warns when scenario probabilities don't sum to 100%.
 */
export function ValuationSummary({ valuation, canonical }: Props) {
  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;
  const w = valuation.weighted;
  const upsideFraction = parseDecimal(w.upside_pct) / 100;

  const probSum = valuation.scenarios.reduce(
    (s, sc) => s + parseDecimal(sc.probability),
    0,
  );
  const probSumOK = Math.abs(probSum - 100) < 0.5;

  const asymmetry = parseDecimal(w.asymmetry_ratio);
  const asymmetryDisplay = Number.isFinite(asymmetry)
    ? asymmetry >= 999
      ? "∞"
      : `${asymmetry.toFixed(2)}×`
    : "—";

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

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Metric
          label="Asymmetry ratio"
          value={asymmetryDisplay}
          subtitle={
            asymmetry >= 999 ? "Unbounded reward/risk" : "Reward / risk"
          }
        />
        <Metric
          label="Weighted IRR (3y)"
          value={
            w.weighted_irr_3y
              ? formatPercent(parseDecimal(w.weighted_irr_3y) / 100, 2)
              : "—"
          }
        />
      </div>

      {!probSumOK ? (
        <div className="mt-4 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
          <p className="text-amber-700 dark:text-amber-400">
            Probability sum is {probSum.toFixed(2)}% (expected 100%). Verify
            scenarios.yaml.
          </p>
        </div>
      ) : null}

      <div className="mt-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Scenarios — click row for drivers and IRR breakdown
        </h3>
        <div className="space-y-2">
          {[...valuation.scenarios]
            .sort(
              (a, b) =>
                parseDecimal(b.probability) - parseDecimal(a.probability),
            )
            .map((s) => (
              <ScenarioRow key={s.label} scenario={s} currency={currency} />
            ))}
        </div>
      </div>
    </SectionShell>
  );
}

function ScenarioRow({
  scenario,
  currency,
}: {
  scenario: ScenarioResult;
  currency: string;
}) {
  const probFraction = parseDecimal(scenario.probability) / 100;
  const upsideFraction =
    scenario.upside_pct !== null ? parseDecimal(scenario.upside_pct) / 100 : null;
  const irr3yFraction =
    scenario.irr_3y !== null ? parseDecimal(scenario.irr_3y) / 100 : null;
  const irr5yFraction =
    scenario.irr_5y !== null ? parseDecimal(scenario.irr_5y) / 100 : null;

  return (
    <details className="overflow-hidden rounded-md border border-border bg-card">
      <summary className="cursor-pointer list-none px-3 py-2 hover:bg-muted/30">
        {/* Mobile: stacked rows (≤768px) */}
        <div className="space-y-1.5 text-sm md:hidden">
          <div className="flex items-center justify-between">
            <span className="font-mono">{scenario.label}</span>
            <span className="font-mono tabular-nums text-xs text-muted-foreground">
              {(probFraction * 100).toFixed(0)}%
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-primary"
              style={{ width: `${Math.min(probFraction * 100, 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Fair value</span>
            <span className="font-mono tabular-nums">
              {formatCurrency(scenario.targets.dcf_fcff_per_share, {
                currency,
                decimals: 2,
              })}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">IRR (3y / 5y)</span>
            <span className="font-mono tabular-nums">
              {irr3yFraction !== null ? formatPercent(irr3yFraction, 1) : "—"}
              {" / "}
              {irr5yFraction !== null ? formatPercent(irr5yFraction, 1) : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Upside</span>
            <span className="font-mono tabular-nums">
              {upsideFraction !== null ? formatPercent(upsideFraction, 2) : "—"}
            </span>
          </div>
        </div>

        {/* Desktop: 12-col grid (≥768px) */}
        <div className="hidden md:grid grid-cols-12 items-center gap-3 text-sm">
          <div className="col-span-2 font-mono">{scenario.label}</div>
          <div className="col-span-3">
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
          </div>
          <div className="col-span-2 text-right font-mono tabular-nums">
            {formatCurrency(scenario.targets.dcf_fcff_per_share, {
              currency,
              decimals: 2,
            })}
          </div>
          <div className="col-span-1 text-right font-mono tabular-nums text-xs">
            {irr3yFraction !== null ? formatPercent(irr3yFraction, 1) : "—"}
          </div>
          <div className="col-span-1 text-right font-mono tabular-nums text-xs">
            {irr5yFraction !== null ? formatPercent(irr5yFraction, 1) : "—"}
          </div>
          <div className="col-span-3 text-right font-mono tabular-nums">
            {upsideFraction !== null ? formatPercent(upsideFraction, 2) : "—"}
          </div>
        </div>
      </summary>

      <div className="border-t border-border bg-muted/20 p-4 text-sm">
        {scenario.description ? (
          <p className="mb-3 text-muted-foreground">{scenario.description}</p>
        ) : null}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <DriversTable drivers={scenario.drivers} />
          <IRRBreakdown scenario={scenario} />
        </div>

        {scenario.survival_conditions.length > 0 ? (
          <div className="mt-4">
            <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
              Survival conditions
            </h4>
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {scenario.survival_conditions.map((c, i) => (
                <li key={i}>{String(c)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {scenario.kill_signals.length > 0 ? (
          <div className="mt-3">
            <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
              Kill signals
            </h4>
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {scenario.kill_signals.map((c, i) => (
                <li key={i}>{String(c)}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function DriversTable({ drivers }: { drivers: ScenarioResult["drivers"] }) {
  const candidates: Array<[string, string | null]> = [
    ["Revenue CAGR", drivers.revenue_cagr],
    ["Terminal growth", drivers.terminal_growth],
    ["Terminal margin", drivers.terminal_margin],
    ["Terminal ROIC", drivers.terminal_roic],
    ["Terminal WACC", drivers.terminal_wacc],
    ["Terminal ROE", drivers.terminal_roe],
    ["Terminal payout", drivers.terminal_payout],
  ];
  const rows = candidates.filter(
    (row): row is [string, string] => row[1] !== null,
  );

  if (rows.length === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-background p-3 text-xs text-muted-foreground">
        No driver values reported for this scenario.
      </div>
    );
  }

  return (
    <div className="rounded border border-border bg-background p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        Drivers
      </h4>
      <dl className="space-y-1 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-mono tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function IRRBreakdown({ scenario }: { scenario: ScenarioResult }) {
  const decomp = scenario.irr_decomposition;
  if (!decomp || !scenario.irr_3y) {
    return (
      <div className="rounded border border-dashed border-border bg-background p-3 text-xs text-muted-foreground">
        IRR decomposition not available.
      </div>
    );
  }

  const total = parseDecimal(scenario.irr_3y);
  const fundamental =
    decomp.fundamental !== null ? parseDecimal(decomp.fundamental) : null;
  const rerating =
    decomp.rerating !== null ? parseDecimal(decomp.rerating) : null;
  const dividend =
    decomp.dividend !== null ? parseDecimal(decomp.dividend) : null;

  return (
    <div className="rounded border border-border bg-background p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        IRR (3y) decomposition
      </h4>
      <dl className="space-y-1 text-xs">
        <BreakdownRow label="Fundamental" value={fundamental} />
        <BreakdownRow label="Re-rating" value={rerating} />
        <BreakdownRow label="Dividend" value={dividend} />
        <div className="my-1 border-t border-border" />
        <BreakdownRow label="Total" value={total} bold />
      </dl>
    </div>
  );
}

function BreakdownRow({
  label,
  value,
  bold = false,
}: {
  label: string;
  value: number | null;
  bold?: boolean;
}) {
  return (
    <div className={`flex justify-between ${bold ? "font-semibold" : ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono tabular-nums">
        {value === null || Number.isNaN(value) ? "—" : `${value.toFixed(2)}%`}
      </dd>
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
