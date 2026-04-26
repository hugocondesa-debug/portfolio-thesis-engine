"use client";

import { useState } from "react";
import type { CanonicalState } from "@/lib/types/canonical";
import type {
  IRRDecomposition,
  ScenarioDrivers,
  ScenarioResult,
  ValuationSnapshot,
} from "@/lib/types/valuation";
import {
  formatCurrency,
  formatPercentDirect,
  parseDecimal,
} from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot | null;
  canonical: CanonicalState;
}

/**
 * Section 10 — per-scenario expandable cards with drivers, targets, IRR
 * decomposition (with bar visualisation), survival conditions and kill
 * signals.
 *
 * Sprint 1B.2 — note that ``ScenarioResult.{probability, upside_pct,
 * irr_3y, irr_5y}`` are **percent strings** (``"25"`` ≡ 25%) per the
 * Sprint 1A.1 valuation type comments. So we feed them through
 * :func:`formatPercentDirect`. Driver fields (terminal margin etc.) are
 * also percent strings per the engine convention.
 */
export function ScenariosDetail({ valuation, canonical }: Props) {
  if (!valuation || valuation.scenarios.length === 0) {
    return (
      <SectionShell
        title="Scenarios Detail"
        subtitle="Drivers, methodology, and IRR decomposition per scenario"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No scenarios in valuation snapshot.
        </p>
      </SectionShell>
    );
  }

  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;
  const scenarios = [...valuation.scenarios].sort(
    (a, b) => parseDecimal(b.probability) - parseDecimal(a.probability),
  );

  return (
    <SectionShell
      title="Scenarios Detail"
      subtitle={`${scenarios.length} scenarios · methodology ${valuation.weighted.expected_value_method_used}`}
    >
      <div className="space-y-3">
        {scenarios.map((s) => (
          <ScenarioCard key={s.label} scenario={s} currency={currency} />
        ))}
      </div>
    </SectionShell>
  );
}

function ScenarioCard({
  scenario,
  currency,
}: {
  scenario: ScenarioResult;
  currency: string;
}) {
  const [open, setOpen] = useState(false);
  const probFraction = parseDecimal(scenario.probability) / 100;

  return (
    <div className="rounded-md border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-muted/30"
      >
        <div className="flex flex-1 items-center gap-3">
          <span className="font-mono text-sm font-semibold">{scenario.label}</span>
          <ScenarioBadge probability={probFraction} />
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="text-right">
            <div className="text-xs text-muted-foreground">Fair value</div>
            <div className="font-mono tabular-nums">
              {formatCurrency(scenario.targets.dcf_fcff_per_share, {
                currency,
                decimals: 2,
              })}
            </div>
          </div>
          <div className="hidden text-right md:block">
            <div className="text-xs text-muted-foreground">Upside</div>
            <div className="font-mono tabular-nums">
              {formatPercentDirect(scenario.upside_pct, 1)}
            </div>
          </div>
          <span className="text-muted-foreground">{open ? "▲" : "▼"}</span>
        </div>
      </button>

      {open ? (
        <div className="border-t border-border p-4">
          {scenario.description ? (
            <p className="mb-4 text-sm text-muted-foreground">
              {scenario.description}
            </p>
          ) : null}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <DriversTable drivers={scenario.drivers} />
            <TargetsAndIRR scenario={scenario} currency={currency} />
          </div>

          {scenario.survival_conditions.length > 0 ? (
            <div className="mt-4">
              <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                Survival conditions
              </h4>
              <ul className="list-disc pl-5 text-sm">
                {scenario.survival_conditions.map((c, i) => (
                  <li key={i}>{String(c)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {scenario.kill_signals.length > 0 ? (
            <div className="mt-3">
              <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                Kill signals
              </h4>
              <ul className="list-disc pl-5 text-sm">
                {scenario.kill_signals.map((c, i) => (
                  <li key={i}>{String(c)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
            <DataField
              label="IRR (3y)"
              value={
                scenario.irr_3y
                  ? formatPercentDirect(scenario.irr_3y, 2)
                  : "—"
              }
            />
            <DataField
              label="IRR (5y)"
              value={
                scenario.irr_5y
                  ? formatPercentDirect(scenario.irr_5y, 2)
                  : "—"
              }
            />
            <DataField
              label="Horizon"
              value={
                scenario.horizon_years !== null
                  ? `${scenario.horizon_years} years`
                  : "—"
              }
            />
            <DataField
              label="Equity value"
              value={formatCurrency(scenario.targets.equity_value, {
                currency,
                compact: true,
              })}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ScenarioBadge({ probability }: { probability: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="h-1.5 w-16 overflow-hidden rounded bg-muted md:w-24">
        <div
          className="h-full bg-primary"
          style={{ width: `${Math.min(probability * 100, 100)}%` }}
        />
      </div>
      <span className="font-mono tabular-nums">
        {(probability * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function DriversTable({ drivers }: { drivers: ScenarioDrivers }) {
  const candidates: Array<[string, string | null, "percent" | "raw"]> = [
    ["Revenue CAGR", drivers.revenue_cagr, "percent"],
    ["Terminal growth", drivers.terminal_growth, "percent"],
    ["Terminal margin", drivers.terminal_margin, "percent"],
    ["Terminal ROIC", drivers.terminal_roic, "percent"],
    ["Terminal WACC", drivers.terminal_wacc, "percent"],
    ["Terminal ROE", drivers.terminal_roe, "percent"],
    ["Terminal payout", drivers.terminal_payout, "percent"],
    ["Terminal NIM", drivers.terminal_nim, "percent"],
    ["Terminal cost-of-risk (bps)", drivers.terminal_cor_bps, "raw"],
    ["Terminal cost/income", drivers.terminal_cost_income, "percent"],
    ["Terminal CET1", drivers.terminal_cet1, "percent"],
  ];
  const rows = candidates.filter(
    (row): row is [string, string, "percent" | "raw"] => row[1] !== null,
  );

  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
        No drivers populated.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-background p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        Drivers
      </h4>
      <dl className="space-y-1 text-sm">
        {rows.map(([label, value, type]) => (
          <Row
            key={label}
            label={label}
            value={
              type === "percent" ? formatPercentDirect(value, 2) : String(value)
            }
          />
        ))}
      </dl>
    </div>
  );
}

function TargetsAndIRR({
  scenario,
  currency,
}: {
  scenario: ScenarioResult;
  currency: string;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-background p-3">
        <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Targets
        </h4>
        <dl className="space-y-1 text-sm">
          <Row
            label="Equity value"
            value={formatCurrency(scenario.targets.equity_value, {
              currency,
              compact: true,
            })}
          />
          <Row
            label="DCF FCFF / share"
            value={formatCurrency(scenario.targets.dcf_fcff_per_share, {
              currency,
              decimals: 2,
            })}
            emphasize
          />
        </dl>
      </div>

      {scenario.irr_decomposition && scenario.irr_3y ? (
        <IRRBreakdown
          decomp={scenario.irr_decomposition}
          totalIRR={scenario.irr_3y}
        />
      ) : null}
    </div>
  );
}

function IRRBreakdown({
  decomp,
  totalIRR,
}: {
  decomp: IRRDecomposition;
  totalIRR: string;
}) {
  const total = parseDecimal(totalIRR);
  const fundamental =
    decomp.fundamental !== null ? parseDecimal(decomp.fundamental) : 0;
  const rerating =
    decomp.rerating !== null ? parseDecimal(decomp.rerating) : 0;
  const dividend =
    decomp.dividend !== null ? parseDecimal(decomp.dividend) : 0;

  const max = Math.max(
    Math.abs(fundamental),
    Math.abs(rerating),
    Math.abs(dividend),
    Math.abs(total),
  );

  return (
    <div className="rounded-md border border-border bg-background p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        IRR (3y) decomposition
      </h4>
      <div className="space-y-2 text-sm">
        <IRRBar label="Fundamental" value={fundamental} max={max} />
        <IRRBar label="Re-rating" value={rerating} max={max} />
        <IRRBar label="Dividend" value={dividend} max={max} />
        <div className="my-2 border-t border-border" />
        <Row label="Total IRR" value={`${total.toFixed(2)}%`} emphasize />
      </div>
    </div>
  );
}

function IRRBar({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const widthPct = max > 0 ? (Math.abs(value) / max) * 100 : 0;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">{value.toFixed(2)}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
        <div
          className={value >= 0 ? "h-full bg-primary" : "h-full bg-destructive"}
          style={{ width: `${widthPct}%` }}
        />
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  emphasize = false,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <div className={`flex justify-between ${emphasize ? "font-semibold" : ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}

function DataField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm tabular-nums">{value}</div>
    </div>
  );
}
