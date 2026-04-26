"use client";

import { useState } from "react";
import type {
  BuybackHistoryItem,
  BuybackPolicy,
  CapitalAllocation,
  CashEvolutionItem,
  ConfidenceLevel,
  DebtPolicy,
  DividendHistoryItem,
  DividendPolicy,
  EvidenceCategory,
  EvidenceSource,
  HistoricalContext,
  MAPolicy,
  ShareIssuancePolicy,
} from "@/lib/types/capital-allocation";
import type { CanonicalState } from "@/lib/types/canonical";
import type { ForecastResult } from "@/lib/types/forecast";
import { formatCurrency } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  capitalAllocation: CapitalAllocation | null;
  forecast: ForecastResult | null;
  canonical: CanonicalState;
}

/**
 * Section 11 — capital allocation policies + evidence trail.
 *
 * Sprint 1B.2 introduces this section. Source is
 * ``data/yamls/companies/<ticker>/capital_allocation.yaml`` parsed via
 * ``js-yaml`` in :func:`getCapitalAllocation` (frontend-only — backend is
 * frozen for this sprint). Combines:
 *
 * - 5 policy cards (dividend, buyback, debt, M&A, share issuance) with
 *   type + confidence (HIGH/MEDIUM/LOW) + rationale
 * - historical context (recent dividends/buybacks, cash evolution, free
 *   text fields)
 * - 5-year deployment chart pulled from the base scenario of the forecast
 *   snapshot
 * - filterable evidence trail across all disclosures
 *
 * Sprint 1C will hyperlink ``policies.*.evidence_refs`` to specific
 * entries in ``evidence_sources``; for now we just surface both side-by-side.
 */
export function CapitalAllocationSection({
  capitalAllocation,
  forecast,
  canonical,
}: Props) {
  if (!capitalAllocation) {
    return (
      <SectionShell
        title="Capital Allocation"
        subtitle="Capex, dividends, buybacks, debt, M&A — policy + evidence"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No capital_allocation.yaml available for this ticker. Sprint 1C will
          allow editing via the yaml workflow.
        </p>
      </SectionShell>
    );
  }

  const currency = canonical.identity.reporting_currency;

  return (
    <SectionShell
      title="Capital Allocation"
      subtitle={`Policies + evidence trail · last updated ${capitalAllocation.last_updated}`}
    >
      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Policies
        </h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <DividendPolicyCard policy={capitalAllocation.policies.dividend_policy} />
          <BuybackPolicyCard policy={capitalAllocation.policies.buyback_policy} />
          <DebtPolicyCard policy={capitalAllocation.policies.debt_policy} />
          <MAPolicyCard policy={capitalAllocation.policies.ma_policy} />
          <ShareIssuancePolicyCard
            policy={capitalAllocation.policies.share_issuance_policy}
          />
        </div>
      </div>

      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Historical context
        </h3>
        <HistoricalContextView
          context={capitalAllocation.historical_context}
        />
      </div>

      {forecast && forecast.projections.length > 0 ? (
        <div className="mb-6">
          <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
            5-year deployment forecast (base scenario)
          </h3>
          <DeploymentChart forecast={forecast} currency={currency} />
        </div>
      ) : null}

      <EvidenceTrail evidenceSources={capitalAllocation.evidence_sources} />

      <div className="mt-6">
        <h3 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Source documents
        </h3>
        <ul className="list-disc pl-5 text-xs text-muted-foreground">
          {capitalAllocation.source_documents.map((doc, idx) => (
            <li key={idx}>{doc}</li>
          ))}
        </ul>
      </div>
    </SectionShell>
  );
}

// === Policy cards ===

function PolicyShell({
  title,
  type,
  confidence,
  rationale,
  children,
}: {
  title: string;
  type: string;
  confidence: ConfidenceLevel;
  rationale: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-mono text-sm font-semibold">{title}</h4>
        <ConfidenceBadge level={confidence} />
      </div>
      <div className="mb-2 inline-block rounded bg-muted px-2 py-0.5 font-mono text-xs">
        {type}
      </div>
      {children}
      <p className="mt-3 text-xs text-muted-foreground">{rationale}</p>
    </div>
  );
}

function DividendPolicyCard({ policy }: { policy: DividendPolicy }) {
  return (
    <PolicyShell
      title="Dividend"
      type={policy.type}
      confidence={policy.confidence}
      rationale={policy.rationale}
    >
      <dl className="space-y-1 text-xs">
        {policy.payout_ratio !== undefined ? (
          <Row
            label="Payout ratio"
            value={`${(policy.payout_ratio * 100).toFixed(1)}%`}
          />
        ) : null}
        {policy.growth_with_ni !== undefined ? (
          <Row
            label="Grows with NI"
            value={policy.growth_with_ni ? "Yes" : "No"}
          />
        ) : null}
      </dl>
    </PolicyShell>
  );
}

function BuybackPolicyCard({ policy }: { policy: BuybackPolicy }) {
  return (
    <PolicyShell
      title="Buyback"
      type={policy.type}
      confidence={policy.confidence}
      rationale={policy.rationale}
    >
      <dl className="space-y-1 text-xs">
        {policy.condition ? (
          <Row label="Condition" value={policy.condition} />
        ) : null}
        {policy.annual_amount_if_condition_met !== undefined ? (
          <Row
            label="Annual (if active)"
            value={`${(policy.annual_amount_if_condition_met / 1_000_000).toFixed(1)}M`}
          />
        ) : null}
      </dl>
    </PolicyShell>
  );
}

function DebtPolicyCard({ policy }: { policy: DebtPolicy }) {
  return (
    <PolicyShell
      title="Debt"
      type={policy.type}
      confidence={policy.confidence}
      rationale={policy.rationale}
    >
      <dl className="space-y-1 text-xs">
        {policy.current_debt !== undefined ? (
          <Row
            label="Current debt"
            value={
              policy.current_debt === 0
                ? "Zero"
                : `${(policy.current_debt / 1_000_000).toFixed(1)}M`
            }
          />
        ) : null}
        {policy.target_leverage !== undefined ? (
          <Row
            label="Target leverage"
            value={`${policy.target_leverage.toFixed(2)}×`}
          />
        ) : null}
      </dl>
    </PolicyShell>
  );
}

function MAPolicyCard({ policy }: { policy: MAPolicy }) {
  return (
    <PolicyShell
      title="M&A"
      type={policy.type}
      confidence={policy.confidence}
      rationale={policy.rationale}
    >
      <dl className="space-y-1 text-xs">
        {policy.annual_deployment_target !== undefined ? (
          <Row
            label="Annual target"
            value={`${(policy.annual_deployment_target / 1_000_000).toFixed(1)}M`}
          />
        ) : null}
        {policy.timing_uncertainty ? (
          <Row label="Timing" value={policy.timing_uncertainty} />
        ) : null}
        {policy.funding_source ? (
          <Row label="Funding" value={policy.funding_source} />
        ) : null}
        {policy.geography_focus && policy.geography_focus.length > 0 ? (
          <Row label="Geography" value={policy.geography_focus.join(", ")} />
        ) : null}
      </dl>
    </PolicyShell>
  );
}

function ShareIssuancePolicyCard({
  policy,
}: {
  policy: ShareIssuancePolicy;
}) {
  return (
    <PolicyShell
      title="Share issuance"
      type={policy.type}
      confidence={policy.confidence}
      rationale={policy.rationale}
    >
      <dl className="space-y-1 text-xs">
        {policy.annual_dilution_rate !== undefined ? (
          <Row
            label="Dilution / year"
            value={`${(policy.annual_dilution_rate * 100).toFixed(2)}%`}
          />
        ) : null}
      </dl>
    </PolicyShell>
  );
}

function ConfidenceBadge({ level }: { level: ConfidenceLevel }) {
  const styles: Record<ConfidenceLevel, string> = {
    HIGH: "bg-positive/10 text-positive border-positive/30",
    MEDIUM: "bg-amber-500/10 text-amber-600 border-amber-500/30",
    LOW: "bg-destructive/10 text-destructive border-destructive/30",
  };

  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-xs ${styles[level]}`}
    >
      {level}
    </span>
  );
}

// === Historical context ===

function HistoricalContextView({ context }: { context: HistoricalContext }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <DividendHistory items={context.recent_dividends_paid} />
      <BuybackHistory items={context.recent_buybacks_executed} />

      {context.cash_evolution.length > 0 ? (
        <div className="md:col-span-2">
          <CashEvolutionTable items={context.cash_evolution} />
        </div>
      ) : null}

      {context.debt_history ? (
        <ContextNote title="Debt history" body={context.debt_history} />
      ) : null}

      {context.ma_history ? (
        <ContextNote title="M&A history" body={context.ma_history} />
      ) : null}

      {context.capital_structure_notes ? (
        <ContextNote
          title="Capital structure notes"
          body={context.capital_structure_notes}
        />
      ) : null}

      {context.net_financial_position_notes ? (
        <ContextNote
          title="Net financial position notes"
          body={context.net_financial_position_notes}
        />
      ) : null}
    </div>
  );
}

function ContextNote({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-md border border-border p-3 text-xs md:col-span-2">
      <h4 className="mb-1 font-mono font-semibold uppercase text-muted-foreground">
        {title}
      </h4>
      <p className="text-muted-foreground">{body}</p>
    </div>
  );
}

function DividendHistory({ items }: { items: DividendHistoryItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
        No recent dividends recorded.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        Recent dividends
      </h4>
      <table className="w-full text-xs">
        <thead className="text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="py-1">Year</th>
            <th className="py-1">Type</th>
            <th className="py-1 text-right">Per share</th>
            <th className="py-1 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={idx} className="border-t border-border">
              <td className="py-1 font-mono">{item.year}</td>
              <td className="py-1">{item.type}</td>
              <td className="py-1 text-right font-mono tabular-nums">
                {item.amount_per_share.toFixed(4)}
              </td>
              <td className="py-1 text-right font-mono tabular-nums">
                {(item.total / 1_000_000).toFixed(2)}M
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BuybackHistory({ items }: { items: BuybackHistoryItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
        No recent buybacks recorded.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        Recent buybacks
      </h4>
      <div className="space-y-2 text-xs">
        {items.map((item, idx) => (
          <div
            key={idx}
            className="border-t border-border pt-2 first:border-t-0 first:pt-0"
          >
            <div className="font-mono font-semibold">{item.program}</div>
            <dl className="mt-1 grid grid-cols-2 gap-1">
              <Row
                label="Shares"
                value={`${(item.shares_bought / 1_000_000).toFixed(2)}M`}
              />
              <Row label="Avg price" value={item.avg_price.toFixed(2)} />
              <Row
                label="Total"
                value={`${(item.total / 1_000_000).toFixed(2)}M`}
              />
              {item.cancelled !== undefined ? (
                <Row label="Cancelled" value={item.cancelled ? "Yes" : "No"} />
              ) : null}
            </dl>
            {item.price_range ? (
              <div className="mt-1 text-xs text-muted-foreground">
                Range: {item.price_range}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function CashEvolutionTable({ items }: { items: CashEvolutionItem[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
        Cash evolution
      </h4>
      <table className="w-full text-xs">
        <thead className="text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="py-1">Period</th>
            <th className="py-1 text-right">Cash</th>
            <th className="py-1 text-right">Net cash</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={idx} className="border-t border-border">
              <td className="py-1 font-mono">{item.period}</td>
              <td className="py-1 text-right font-mono tabular-nums">
                {(item.cash / 1_000_000).toFixed(1)}M
              </td>
              <td className="py-1 text-right font-mono tabular-nums">
                {(item.net_cash / 1_000_000).toFixed(1)}M
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// === Deployment chart (table-based) ===

function DeploymentChart({
  forecast,
  currency,
}: {
  forecast: ForecastResult;
  currency: string;
}) {
  const baseProj =
    forecast.projections.find((p) => p.scenario_name === "base") ??
    forecast.projections[0];

  if (!baseProj) return null;

  const cf = baseProj.cash_flow;
  if (cf.length === 0) return null;

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Deployment</th>
            {cf.map((y) => (
              <th key={y.year} className="px-3 py-2 text-right font-mono">
                Y{y.year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <DeploymentRow
            label="Capex"
            values={cf.map((y) => y.capex)}
            currency={currency}
          />
          <DeploymentRow
            label="M&A"
            values={cf.map((y) => y.ma_deployment)}
            currency={currency}
          />
          <DeploymentRow
            label="Dividends"
            values={cf.map((y) => y.dividends_paid)}
            currency={currency}
          />
          <DeploymentRow
            label="Buybacks"
            values={cf.map((y) => y.buybacks_executed)}
            currency={currency}
          />
          <DeploymentRow
            label="Debt issued"
            values={cf.map((y) => y.debt_issued)}
            currency={currency}
          />
          <DeploymentRow
            label="Debt repaid"
            values={cf.map((y) => y.debt_repaid)}
            currency={currency}
          />
        </tbody>
      </table>
    </div>
  );
}

function DeploymentRow({
  label,
  values,
  currency,
}: {
  label: string;
  values: (string | number)[];
  currency: string;
}) {
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-2">{label}</td>
      {values.map((v, idx) => (
        <td
          key={idx}
          className="px-3 py-2 text-right font-mono tabular-nums"
        >
          {formatCurrency(v, { currency, compact: true })}
        </td>
      ))}
    </tr>
  );
}

// === Evidence trail ===

function EvidenceTrail({
  evidenceSources,
}: {
  evidenceSources: EvidenceSource[];
}) {
  const [filter, setFilter] = useState<EvidenceCategory | "ALL">("ALL");

  const categories = Array.from(
    new Set(evidenceSources.map((e) => e.category)),
  ) as EvidenceCategory[];

  const filtered =
    filter === "ALL"
      ? evidenceSources
      : evidenceSources.filter((e) => e.category === filter);

  return (
    <details className="rounded-md border border-border">
      <summary className="cursor-pointer px-4 py-3 hover:bg-muted/30">
        <span className="font-mono text-xs font-semibold uppercase text-muted-foreground">
          Evidence trail — {evidenceSources.length} disclosures
        </span>
      </summary>
      <div className="border-t border-border p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          <FilterButton
            active={filter === "ALL"}
            onClick={() => setFilter("ALL")}
          >
            All ({evidenceSources.length})
          </FilterButton>
          {categories.map((cat) => {
            const count = evidenceSources.filter(
              (e) => e.category === cat,
            ).length;
            return (
              <FilterButton
                key={cat}
                active={filter === cat}
                onClick={() => setFilter(cat)}
              >
                {cat} ({count})
              </FilterButton>
            );
          })}
        </div>

        <div className="space-y-2">
          {filtered.map((e, idx) => (
            <div
              key={idx}
              className="rounded border border-border bg-background p-3 text-sm"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                  {e.category}
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {e.date}
                </span>
              </div>
              <p className="mt-2 font-medium">{e.disclosure}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {e.document} · {e.location}
              </p>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

function FilterButton({
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
      className={`rounded-md border px-3 py-1 text-xs ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-input bg-background text-muted-foreground hover:bg-accent"
      }`}
    >
      {children}
    </button>
  );
}

// === Helpers ===

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}
