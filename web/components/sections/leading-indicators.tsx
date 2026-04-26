"use client";

import { useState } from "react";
import type { CanonicalState } from "@/lib/types/canonical";
import type {
  SensitivityGrid,
  ValuationSnapshot,
} from "@/lib/types/valuation";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot | null;
  canonical: CanonicalState;
}

/**
 * Section 14 — Leading Indicators (sensitivities).
 *
 * Sprint 1C — renders ``valuation.sensitivities`` as 3×3 (or n×m) CSS
 * heatmaps. Each cell colours by deviation from the probability-weighted
 * E[V]: green tint above E[V], red tint below. Per-share fair values
 * are formatted in the reporting currency.
 */
export function LeadingIndicators({ valuation, canonical }: Props) {
  if (
    !valuation ||
    !valuation.sensitivities ||
    valuation.sensitivities.length === 0
  ) {
    return (
      <SectionShell
        title="Leading Indicators"
        subtitle="Sensitivity heatmaps and scenario response"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No sensitivity grids in valuation snapshot. Run{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            pte process {canonical.identity.ticker}
          </code>{" "}
          with sensitivity analysis enabled.
        </p>
      </SectionShell>
    );
  }

  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;
  const sensitivities = valuation.sensitivities;

  return (
    <SectionShell
      title="Leading Indicators"
      subtitle={`${sensitivities.length} sensitivity grids · per-share E[V] vs ±1 step on key drivers`}
    >
      <SensitivityTabs sensitivities={sensitivities} currency={currency} />

      <p className="mt-6 text-xs text-muted-foreground">
        Heatmap shows fair value per share under different parameter
        combinations. Color intensity reflects deviation from
        probability-weighted E[V] (
        <span className="font-mono">
          {formatCurrency(valuation.weighted.expected_value, {
            currency,
            decimals: 2,
          })}
        </span>
        ). Green = above E[V], red = below.
      </p>
    </SectionShell>
  );
}

function SensitivityTabs({
  sensitivities,
  currency,
}: {
  sensitivities: SensitivityGrid[];
  currency: string;
}) {
  const [activeIdx, setActiveIdx] = useState(0);
  const active = sensitivities[activeIdx];

  return (
    <>
      <div className="mb-4">
        <select
          value={activeIdx}
          onChange={(e) => setActiveIdx(Number(e.target.value))}
          className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm md:hidden"
        >
          {sensitivities.map((s, idx) => (
            <option key={idx} value={idx}>
              {s.scenario_label} · {s.axis_x} × {s.axis_y}
            </option>
          ))}
        </select>

        <div className="hidden flex-wrap gap-1 md:flex">
          {sensitivities.map((s, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setActiveIdx(idx)}
              className={`rounded-md border px-3 py-1.5 font-mono text-xs ${
                idx === activeIdx
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-input bg-card text-muted-foreground hover:bg-accent"
              }`}
            >
              {s.scenario_label}{" "}
              <span className="opacity-70">
                ({s.axis_x} × {s.axis_y})
              </span>
            </button>
          ))}
        </div>
      </div>

      <Heatmap grid={active} currency={currency} />
    </>
  );
}

function Heatmap({
  grid,
  currency,
}: {
  grid: SensitivityGrid;
  currency: string;
}) {
  const allValues = grid.target_per_share.flat().map(parseDecimal);
  const validValues = allValues.filter((v) => !Number.isNaN(v));

  if (validValues.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        Sensitivity grid is empty.
      </div>
    );
  }

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  const mid = (min + max) / 2;

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        <span className="font-mono font-semibold">
          {formatAxisLabel(grid.axis_x)}
        </span>{" "}
        → (columns) ·{" "}
        <span className="font-mono font-semibold">
          {formatAxisLabel(grid.axis_y)}
        </span>{" "}
        ↓ (rows)
      </div>

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/30 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-right">
                {formatAxisLabel(grid.axis_y)} ↓
              </th>
              {grid.x_values.map((x, idx) => (
                <th key={idx} className="px-3 py-2 text-right font-mono">
                  {formatDriverValue(x, grid.axis_x)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.target_per_share.map((row, yIdx) => (
              <tr key={yIdx} className="border-t border-border">
                <td className="px-3 py-2 text-right font-mono text-xs text-muted-foreground">
                  {formatDriverValue(grid.y_values[yIdx], grid.axis_y)}
                </td>
                {row.map((cell, xIdx) => {
                  const value = parseDecimal(cell);
                  const intensity = computeIntensity(value, min, max, mid);
                  return (
                    <td
                      key={xIdx}
                      className="px-3 py-2 text-right font-mono tabular-nums"
                      style={{ backgroundColor: intensity.color }}
                    >
                      <span style={{ color: intensity.textColor }}>
                        {formatCurrency(cell, { currency, decimals: 2 })}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <div
            className="h-3 w-12 rounded"
            style={{
              background:
                "linear-gradient(to right, hsl(0 60% 70%), hsl(60 60% 90%), hsl(120 60% 70%))",
            }}
          />
          <span>
            {formatCurrency(min, { currency, decimals: 2 })} →{" "}
            {formatCurrency(max, { currency, decimals: 2 })}
          </span>
        </div>
        <div>Range: {formatCurrency(max - min, { currency, decimals: 2 })}</div>
      </div>
    </div>
  );
}

interface IntensityResult {
  color: string;
  textColor: string;
}

function computeIntensity(
  value: number,
  min: number,
  max: number,
  mid: number,
): IntensityResult {
  if (Number.isNaN(value)) {
    return { color: "transparent", textColor: "inherit" };
  }
  const range = max - min;
  if (range === 0) {
    return { color: "hsl(60 30% 95%)", textColor: "inherit" };
  }
  const position = (value - mid) / (range / 2);

  if (position > 0) {
    const intensity = Math.min(Math.abs(position), 1);
    const lightness = 95 - intensity * 25;
    return {
      color: `hsl(120 50% ${lightness}%)`,
      textColor: lightness < 80 ? "hsl(120 80% 20%)" : "inherit",
    };
  }

  const intensity = Math.min(Math.abs(position), 1);
  const lightness = 95 - intensity * 25;
  return {
    color: `hsl(0 50% ${lightness}%)`,
    textColor: lightness < 80 ? "hsl(0 80% 30%)" : "inherit",
  };
}

function formatAxisLabel(axis: string): string {
  return axis
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatDriverValue(value: string, axis: string): string {
  const lowerAxis = axis.toLowerCase();
  if (
    lowerAxis.includes("wacc") ||
    lowerAxis.includes("growth") ||
    lowerAxis.includes("margin") ||
    lowerAxis.includes("rate")
  ) {
    const num = parseFloat(value);
    if (Number.isNaN(num)) return value;
    return `${num.toFixed(2)}%`;
  }
  return value;
}
