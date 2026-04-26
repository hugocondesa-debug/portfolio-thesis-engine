"use client";

import { useState } from "react";
import type { CanonicalState } from "@/lib/types/canonical";
import type {
  ForecastBalanceSheetYear,
  ForecastCashFlowYear,
  ForecastIncomeStatementYear,
  ForecastNumber,
  ForecastRatiosYear,
  ForecastResult,
  SolverConvergence,
  ThreeStatementProjection,
} from "@/lib/types/forecast";
import type { ValuationSnapshot } from "@/lib/types/valuation";
import {
  formatCurrency,
  formatMultiple,
  formatPercent,
  parseDecimal,
} from "@/lib/utils/format";
import { DataField } from "@/components/primitives/data-field";
import { SectionShell } from "@/components/primitives/section-shell";

interface Props {
  forecast: ForecastResult | null;
  valuation: ValuationSnapshot | null;
  canonical: CanonicalState;
}

type StatementTab = "is" | "bs" | "cf" | "ratios";

/**
 * Section 9 — Three-statement forecast detail.
 *
 * Sprint 1B.2 introduces this section. Source is the forecast snapshot
 * (``data/forecast_snapshots/<ticker>/<latest>.json``), which carries up to
 * 7 scenarios (vs the 3 persisted in valuation today). Per scenario we show
 * IS / BS / CF / Forward Ratios across the projection horizon (typically 5
 * years).
 *
 * **Important** — forecast ratios are stored as **fractions** (``0.1756`` ≡
 * 17.56%), so we use :func:`formatPercent` (which multiplies by 100) here.
 * The canonical analytical layer uses :func:`formatPercentDirect` because
 * those ratios are stored as percent strings already.
 */
export function ForecastDetail({ forecast, valuation, canonical }: Props) {
  if (!forecast || forecast.projections.length === 0) {
    return (
      <SectionShell
        title="Three-Statement Forecast Detail"
        subtitle="5-year projections per scenario"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No forecast snapshot available. Run{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            pte process {canonical.identity.ticker}
          </code>{" "}
          to populate.
        </p>
      </SectionShell>
    );
  }

  const currency = canonical.identity.reporting_currency;
  const projections = forecast.projections;

  const defaultScenario =
    projections.find((p) => p.scenario_name === "base")?.scenario_name ??
    projections[0].scenario_name;

  return (
    <SectionShell
      title="Three-Statement Forecast Detail"
      subtitle={`${projections.length} scenarios · ${projections[0]?.projection_years ?? 5}-year horizon · base year ${projections[0]?.base_year_label ?? "—"}`}
    >
      <ProbabilitySumIndicator projections={projections} />

      <ScenarioTabs
        projections={projections}
        defaultScenario={defaultScenario}
        currency={currency}
        valuation={valuation}
      />

      {forecast.expected_forward_eps_y1 ||
      forecast.expected_forward_per_y1 ||
      forecast.probability_weighted_ev ? (
        <div className="mt-6 rounded-md bg-muted/30 p-4">
          <h4 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Probability-weighted forward metrics
          </h4>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <SummaryMetric
              label="Forward EPS Y1"
              value={
                forecast.expected_forward_eps_y1 !== null
                  ? formatCurrency(forecast.expected_forward_eps_y1, {
                      currency,
                      decimals: 3,
                    })
                  : "—"
              }
            />
            <SummaryMetric
              label="Forward PER Y1"
              value={
                forecast.expected_forward_per_y1 !== null
                  ? formatMultiple(forecast.expected_forward_per_y1, 1)
                  : "—"
              }
            />
            <SummaryMetric
              label="Probability-weighted EV"
              value={
                forecast.probability_weighted_ev !== null
                  ? formatCurrency(forecast.probability_weighted_ev, {
                      currency,
                      decimals: 2,
                    })
                  : "—"
              }
            />
          </div>
        </div>
      ) : null}
    </SectionShell>
  );
}

function ScenarioTabs({
  projections,
  defaultScenario,
  currency,
  valuation,
}: {
  projections: ThreeStatementProjection[];
  defaultScenario: string;
  currency: string;
  valuation: ValuationSnapshot | null;
}) {
  const [activeScenario, setActiveScenario] = useState(defaultScenario);
  const [activeTab, setActiveTab] = useState<StatementTab>("is");

  const projection =
    projections.find((p) => p.scenario_name === activeScenario) ?? projections[0];

  const matchingValuationScenario = valuation?.scenarios.find(
    (s) => s.label === activeScenario,
  );

  return (
    <>
      <div className="mb-4">
        <ScenarioSelector
          projections={projections}
          activeScenario={activeScenario}
          onChange={setActiveScenario}
        />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <ProbabilityBadge probability={projection.scenario_probability} />
        <ConvergenceBadge convergence={projection.solver_convergence} />
        {matchingValuationScenario ? (
          <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
            Valuation:{" "}
            {formatCurrency(
              matchingValuationScenario.targets.dcf_fcff_per_share,
              { currency, decimals: 2 },
            )}{" "}
            per share
          </span>
        ) : null}
        {projection.warnings.length > 0 ? (
          <span
            className="rounded border border-amber-500/30 bg-amber-50 px-2 py-0.5 font-mono text-xs text-amber-700 dark:bg-amber-950/20 dark:text-amber-400"
            title={projection.warnings.join("\n")}
          >
            ⚠ {projection.warnings.length} warnings
          </span>
        ) : null}
      </div>

      <div className="mb-4 flex flex-wrap rounded-md border border-border bg-card p-1 text-xs">
        <SubTabButton
          active={activeTab === "is"}
          onClick={() => setActiveTab("is")}
        >
          Income Statement
        </SubTabButton>
        <SubTabButton
          active={activeTab === "bs"}
          onClick={() => setActiveTab("bs")}
        >
          Balance Sheet
        </SubTabButton>
        <SubTabButton
          active={activeTab === "cf"}
          onClick={() => setActiveTab("cf")}
        >
          Cash Flow
        </SubTabButton>
        <SubTabButton
          active={activeTab === "ratios"}
          onClick={() => setActiveTab("ratios")}
        >
          Forward Ratios
        </SubTabButton>
      </div>

      {activeTab === "is" ? (
        <ISTable years={projection.income_statement} currency={currency} />
      ) : null}
      {activeTab === "bs" ? (
        <BSTable years={projection.balance_sheet} currency={currency} />
      ) : null}
      {activeTab === "cf" ? (
        <CFTable years={projection.cash_flow} currency={currency} />
      ) : null}
      {activeTab === "ratios" ? (
        <RatiosTable years={projection.forward_ratios} />
      ) : null}
    </>
  );
}

function ScenarioSelector({
  projections,
  activeScenario,
  onChange,
}: {
  projections: ThreeStatementProjection[];
  activeScenario: string;
  onChange: (s: string) => void;
}) {
  return (
    <>
      <select
        value={activeScenario}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm md:hidden"
      >
        {projections.map((p) => (
          <option key={p.scenario_name} value={p.scenario_name}>
            {p.scenario_name} ({(parseDecimal(p.scenario_probability) * 100).toFixed(0)}%)
          </option>
        ))}
      </select>

      <div className="hidden flex-wrap gap-1 md:flex">
        {projections.map((p) => (
          <button
            key={p.scenario_name}
            type="button"
            onClick={() => onChange(p.scenario_name)}
            className={`rounded-md border px-3 py-1.5 font-mono text-xs ${
              p.scenario_name === activeScenario
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-card text-muted-foreground hover:bg-accent"
            }`}
          >
            {p.scenario_name}{" "}
            <span className="opacity-70">
              ({(parseDecimal(p.scenario_probability) * 100).toFixed(0)}%)
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

function ProbabilityBadge({ probability }: { probability: ForecastNumber }) {
  const pct = parseDecimal(probability) * 100;
  return (
    <span className="rounded border border-border px-2 py-0.5 font-mono text-xs">
      Prob: {pct.toFixed(1)}%
    </span>
  );
}

function ConvergenceBadge({
  convergence,
}: {
  convergence: SolverConvergence;
}) {
  if (convergence.converged) {
    return (
      <span className="rounded border border-positive/30 bg-positive/10 px-2 py-0.5 font-mono text-xs text-positive">
        ✓ Converged ({convergence.iterations} iter, residual{" "}
        {convergence.final_residual.toExponential(2)})
      </span>
    );
  }
  return (
    <span className="rounded border border-destructive/30 bg-destructive/10 px-2 py-0.5 font-mono text-xs text-destructive">
      ✗ Failed convergence ({convergence.iterations} iter)
    </span>
  );
}

function SubTabButton({
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
      className={`rounded px-3 py-1.5 ${
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

// === Statement tables ===

function ISTable({
  years,
  currency,
}: {
  years: ForecastIncomeStatementYear[];
  currency: string;
}) {
  if (years.length === 0) return <EmptyTable />;

  const config: TableConfig<ForecastIncomeStatementYear> = {
    groups: [
      {
        label: "Revenue & Profitability",
        rows: [
          { label: "Revenue", accessor: (y) => y.revenue, format: "currency" },
          {
            label: "Revenue growth",
            accessor: (y) => y.revenue_growth_rate,
            format: "percent_fraction",
          },
          {
            label: "Operating margin",
            accessor: (y) => y.operating_margin,
            format: "percent_fraction",
          },
          {
            label: "Operating income",
            accessor: (y) => y.operating_income,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Below the line",
        rows: [
          {
            label: "Interest expense",
            accessor: (y) => y.interest_expense,
            format: "currency",
          },
          {
            label: "Interest income",
            accessor: (y) => y.interest_income,
            format: "currency",
          },
          {
            label: "Pre-tax income",
            accessor: (y) => y.pre_tax_income,
            format: "currency",
          },
          {
            label: "Tax rate",
            accessor: (y) => y.tax_rate,
            format: "percent_fraction",
          },
          {
            label: "Tax expense",
            accessor: (y) => y.tax_expense,
            format: "currency",
          },
          {
            label: "Net income",
            accessor: (y) => y.net_income,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Per-share",
        rows: [
          {
            label: "Shares outstanding",
            accessor: (y) => y.shares_outstanding,
            format: "number_compact",
          },
          {
            label: "EPS",
            accessor: (y) => y.eps,
            format: "currency_full",
            emphasize: true,
          },
        ],
      },
    ],
  };

  return <ForecastTable years={years} currency={currency} config={config} />;
}

function BSTable({
  years,
  currency,
}: {
  years: ForecastBalanceSheetYear[];
  currency: string;
}) {
  if (years.length === 0) return <EmptyTable />;

  const config: TableConfig<ForecastBalanceSheetYear> = {
    groups: [
      {
        label: "Assets",
        rows: [
          { label: "Cash", accessor: (y) => y.cash, format: "currency" },
          { label: "PPE (net)", accessor: (y) => y.ppe_net, format: "currency" },
          { label: "Goodwill", accessor: (y) => y.goodwill, format: "currency" },
          {
            label: "Working capital (net)",
            accessor: (y) => y.working_capital_net,
            format: "currency",
          },
          {
            label: "Total assets",
            accessor: (y) => y.total_assets,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Capital structure",
        rows: [
          { label: "Debt", accessor: (y) => y.debt, format: "currency" },
          {
            label: "Equity",
            accessor: (y) => y.equity,
            format: "currency",
            emphasize: true,
          },
        ],
      },
    ],
  };

  return <ForecastTable years={years} currency={currency} config={config} />;
}

function CFTable({
  years,
  currency,
}: {
  years: ForecastCashFlowYear[];
  currency: string;
}) {
  if (years.length === 0) return <EmptyTable />;

  const config: TableConfig<ForecastCashFlowYear> = {
    groups: [
      {
        label: "Operating",
        rows: [
          {
            label: "CFO",
            accessor: (y) => y.cfo,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Investing",
        rows: [
          { label: "Capex", accessor: (y) => y.capex, format: "currency" },
          {
            label: "M&A deployment",
            accessor: (y) => y.ma_deployment,
            format: "currency",
          },
          {
            label: "CFI",
            accessor: (y) => y.cfi,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Financing",
        rows: [
          {
            label: "Dividends paid",
            accessor: (y) => y.dividends_paid,
            format: "currency",
          },
          {
            label: "Buybacks executed",
            accessor: (y) => y.buybacks_executed,
            format: "currency",
          },
          {
            label: "Debt issued",
            accessor: (y) => y.debt_issued,
            format: "currency",
          },
          {
            label: "Debt repaid",
            accessor: (y) => y.debt_repaid,
            format: "currency",
          },
          {
            label: "Net interest",
            accessor: (y) => y.net_interest,
            format: "currency",
          },
          {
            label: "CFF",
            accessor: (y) => y.cff,
            format: "currency",
            emphasize: true,
          },
        ],
      },
      {
        label: "Reconciliation",
        rows: [
          { label: "FX effect", accessor: (y) => y.fx_effect, format: "currency" },
          {
            label: "Net change in cash",
            accessor: (y) => y.net_change_cash,
            format: "currency",
            emphasize: true,
          },
        ],
      },
    ],
  };

  return <ForecastTable years={years} currency={currency} config={config} />;
}

function RatiosTable({ years }: { years: ForecastRatiosYear[] }) {
  if (years.length === 0) return <EmptyTable />;

  const config: TableConfig<ForecastRatiosYear> = {
    groups: [
      {
        label: "Returns on capital",
        rows: [
          {
            label: "ROIC",
            accessor: (y) => y.roic,
            format: "percent_fraction",
            emphasize: true,
          },
          { label: "ROE", accessor: (y) => y.roe, format: "percent_fraction" },
        ],
      },
      {
        label: "Leverage",
        rows: [
          {
            label: "Debt / EBITDA",
            accessor: (y) => y.debt_to_ebitda,
            format: "multiple",
          },
          {
            label: "WACC applied",
            accessor: (y) => y.wacc_applied,
            format: "percent_fraction",
          },
        ],
      },
      {
        label: "Valuation",
        rows: [
          {
            label: "PER at market",
            accessor: (y) => y.per_at_market_price,
            format: "multiple",
          },
          {
            label: "PER at fair value",
            accessor: (y) => y.per_at_fair_value,
            format: "multiple",
          },
          {
            label: "FCF yield (market)",
            accessor: (y) => y.fcf_yield_at_market,
            format: "percent_fraction",
          },
          {
            label: "EV / EBITDA",
            accessor: (y) => y.ev_ebitda,
            format: "multiple",
          },
        ],
      },
    ],
  };

  return <ForecastTable years={years} currency="" config={config} />;
}

// === Generic forecast table component ===

type FormatType =
  | "currency"
  | "currency_full"
  | "percent_fraction"
  | "multiple"
  | "number_compact";

interface RowConfig<T> {
  label: string;
  accessor: (year: T) => ForecastNumber | null;
  format: FormatType;
  emphasize?: boolean;
}

interface GroupConfig<T> {
  label: string;
  rows: RowConfig<T>[];
}

interface TableConfig<T> {
  groups: GroupConfig<T>[];
}

function ForecastTable<T extends { year: number }>({
  years,
  currency,
  config,
}: {
  years: T[];
  currency: string;
  config: TableConfig<T>;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-muted/30 px-3 py-2 min-w-[14rem]">
              Item
            </th>
            {years.map((y) => (
              <th key={y.year} className="px-3 py-2 text-right font-mono">
                Y{y.year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {config.groups.map((group, idx) => (
            <ForecastGroup
              key={`${idx}-${group.label}`}
              group={group}
              years={years}
              currency={currency}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ForecastGroup<T extends { year: number }>({
  group,
  years,
  currency,
}: {
  group: GroupConfig<T>;
  years: T[];
  currency: string;
}) {
  return (
    <>
      <tr className="bg-muted/40">
        <td
          colSpan={years.length + 1}
          className="sticky left-0 bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase text-muted-foreground"
        >
          {group.label}
        </td>
      </tr>
      {group.rows.map((row) => (
        <tr
          key={row.label}
          className={`border-t border-border ${row.emphasize ? "bg-muted/20 font-semibold" : ""}`}
        >
          <td className="sticky left-0 bg-card px-3 py-2">{row.label}</td>
          {years.map((y) => (
            <td
              key={y.year}
              className="px-3 py-2 text-right font-mono tabular-nums"
            >
              {formatValue(row.accessor(y), row.format, currency)}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function formatValue(
  value: ForecastNumber | null,
  format: FormatType,
  currency: string,
): string {
  if (value === null || value === undefined) return "—";

  switch (format) {
    case "currency":
      return formatCurrency(value, { currency, compact: true });
    case "currency_full":
      return formatCurrency(value, { currency, decimals: 3 });
    case "percent_fraction":
      // Forecast ratios are stored as fractions; formatPercent multiplies by 100.
      return formatPercent(value, 2);
    case "multiple":
      return formatMultiple(value, 2);
    case "number_compact": {
      const num = parseDecimal(value);
      if (Number.isNaN(num)) return "—";
      if (Math.abs(num) >= 1_000_000) {
        return `${(num / 1_000_000).toFixed(1)}M`;
      }
      return num.toFixed(0);
    }
    default:
      return String(value);
  }
}

function EmptyTable() {
  return (
    <div className="rounded-md border border-dashed border-border bg-card p-4 text-sm text-muted-foreground">
      No data for this statement.
    </div>
  );
}

function ProbabilitySumIndicator({
  projections,
}: {
  projections: ThreeStatementProjection[];
}) {
  const sum = projections.reduce(
    (s, p) => s + parseDecimal(p.scenario_probability),
    0,
  );
  const sumPct = sum * 100;
  const ok = Math.abs(sumPct - 100) < 0.5;

  if (ok) return null;

  return (
    <div className="mb-4 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
      <p className="text-amber-700 dark:text-amber-400">
        Probability sum across scenarios is {sumPct.toFixed(2)}% (expected
        100%). Verify forecast snapshot.
      </p>
    </div>
  );
}

// Sprint QA — uses the DataField primitive. We render through a tiny
// wrapper that keeps the existing call-sites' API (label + value props)
// while letting DataField own the markup.
function SummaryMetric({ label, value }: { label: string; value: string }) {
  return <DataField label={label} value={value} mono />;
}
