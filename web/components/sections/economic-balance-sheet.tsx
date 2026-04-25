import type {
  CanonicalState,
  NonRecurringItem,
  NopatBridge,
} from "@/lib/types/canonical";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";
import { EmptySectionNote, SectionShell } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

/**
 * Sprint 1A.1 — reads from ``canonical.analysis.invested_capital_by_period[0]``
 * (newest period). Surfaces the cross-check residual so the analyst can see
 * whether the operating-vs-financing identity holds (zero = exact match).
 *
 * Sprint 1B.1 — adds the NOPAT bridge from ``analysis.nopat_bridge_by_period``
 * (EBITDA → EBITA → operating income → sustainable OI) and a collapsible
 * non-recurring items table showing Module D's classification, action, and
 * confidence per excluded line.
 */
export function EconomicBalanceSheet({ canonical }: Props) {
  const periods = canonical.analysis?.invested_capital_by_period ?? [];
  const nopatBridges = canonical.analysis?.nopat_bridge_by_period ?? [];
  const latest = periods[0];
  const latestNopat = nopatBridges[0] ?? null;
  const currency = canonical.identity.reporting_currency;

  return (
    <SectionShell
      title="Economic Balance Sheet"
      subtitle={
        latest
          ? `Operating vs financing — ${latest.period.label}`
          : "Operating vs financing — invested-capital view"
      }
    >
      {!latest ? (
        <EmptySectionNote message="No invested-capital periods available in the canonical state." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div className="rounded-md border border-border p-4">
              <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
                Operating side
              </h3>
              <div className="space-y-2 text-sm">
                <Row
                  label="Operating assets"
                  value={formatCurrency(latest.operating_assets, {
                    currency,
                    compact: true,
                  })}
                />
                <Row
                  label="Operating liabilities (non-financial)"
                  value={`(${formatCurrency(latest.operating_liabilities, { currency, compact: true })})`}
                  negative
                />
                <Divider />
                <Row
                  label="Invested capital"
                  value={formatCurrency(latest.invested_capital, {
                    currency,
                    compact: true,
                  })}
                  emphasize
                />
                {latest.operating_working_capital !== undefined ? (
                  <Row
                    label="Operating working capital"
                    value={formatCurrency(latest.operating_working_capital, {
                      currency,
                      compact: true,
                    })}
                    note
                  />
                ) : null}
              </div>
            </div>

            <div className="rounded-md border border-border p-4">
              <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
                Financing side
              </h3>
              <div className="space-y-2 text-sm">
                <Row
                  label="Financial assets (cash + investments)"
                  value={formatCurrency(latest.financial_assets, {
                    currency,
                    compact: true,
                  })}
                />
                <Row
                  label="Financial liabilities"
                  value={`(${formatCurrency(latest.financial_liabilities, { currency, compact: true })})`}
                  negative
                />
                {latest.bank_debt !== undefined ? (
                  <Row
                    label="    Bank debt"
                    value={formatCurrency(latest.bank_debt, {
                      currency,
                      compact: true,
                    })}
                    note
                  />
                ) : null}
                {latest.lease_liabilities !== undefined ? (
                  <Row
                    label="    Lease liabilities"
                    value={formatCurrency(latest.lease_liabilities, {
                      currency,
                      compact: true,
                    })}
                    note
                  />
                ) : null}
                <Divider />
                <NetDebtRow
                  financialLiabilities={latest.financial_liabilities}
                  financialAssets={latest.financial_assets}
                  currency={currency}
                />
                <Row
                  label="Equity claims (parent)"
                  value={formatCurrency(latest.equity_claims, {
                    currency,
                    compact: true,
                  })}
                />
                <Row
                  label="NCI claims"
                  value={formatCurrency(latest.nci_claims, {
                    currency,
                    compact: true,
                  })}
                />
              </div>
            </div>
          </div>

          {latestNopat ? (
            <div className="mt-6">
              <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
                NOPAT bridge — {latestNopat.period.label}
              </h3>
              <NopatBridgeView bridge={latestNopat} currency={currency} />
            </div>
          ) : null}

          <p className="mt-6 text-xs text-muted-foreground">
            Period {latest.period.label}. Cross-check residual:{" "}
            <span className="font-mono">
              {formatCurrency(latest.cross_check_residual, {
                currency,
                compact: true,
              })}
            </span>
            . Identity holds when residual ≈ 0.
          </p>
        </>
      )}
    </SectionShell>
  );
}

function NopatBridgeView({
  bridge,
  currency,
}: {
  bridge: NopatBridge;
  currency: string;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border p-3">
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <BridgeMetric
            label="EBITDA"
            value={formatCurrency(bridge.ebitda, { currency, compact: true })}
          />
          <BridgeMetric
            label="EBITA"
            value={
              bridge.ebita
                ? formatCurrency(bridge.ebita, { currency, compact: true })
                : "—"
            }
          />
          <BridgeMetric
            label="Operating income"
            value={
              bridge.operating_income
                ? formatCurrency(bridge.operating_income, {
                    currency,
                    compact: true,
                  })
                : "—"
            }
          />
          <BridgeMetric
            label="OI sustainable"
            value={
              bridge.operating_income_sustainable
                ? formatCurrency(bridge.operating_income_sustainable, {
                    currency,
                    compact: true,
                  })
                : "—"
            }
            highlight
          />
        </div>
      </div>

      {bridge.non_recurring_items_detail.length > 0 ? (
        <details className="rounded-md border border-border">
          <summary className="cursor-pointer px-3 py-2 text-xs text-muted-foreground hover:bg-muted/30">
            Non-recurring items adjusted out —{" "}
            {bridge.non_recurring_items_detail.length} entries · total{" "}
            {formatCurrency(bridge.non_recurring_operating_items, {
              currency,
              compact: true,
            })}
          </summary>
          <div className="border-t border-border p-3">
            <table className="w-full text-xs">
              <thead className="text-left uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-1">Label</th>
                  <th className="py-1 text-right">Value</th>
                  <th className="py-1">Classification</th>
                  <th className="py-1">Action</th>
                  <th className="py-1">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {bridge.non_recurring_items_detail.map((item, idx) => (
                  <NonRecurringRow
                    key={`${item.label}-${idx}`}
                    item={item}
                    currency={currency}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

function NonRecurringRow({
  item,
  currency,
}: {
  item: NonRecurringItem;
  currency: string;
}) {
  return (
    <tr className="border-t border-border">
      <td className="py-1 pr-2" title={item.rationale}>
        {item.label}
      </td>
      <td className="py-1 text-right font-mono tabular-nums">
        {formatCurrency(item.value, { currency, compact: true })}
      </td>
      <td className="py-1 font-mono">
        {item.operational_classification}/{item.recurrence_classification}
      </td>
      <td className="py-1 font-mono">
        <span
          className={
            item.action === "exclude"
              ? "text-destructive"
              : item.action === "include"
                ? "text-positive"
                : "text-amber-600"
          }
        >
          {item.action}
        </span>
      </td>
      <td className="py-1 font-mono">{item.confidence}</td>
    </tr>
  );
}

function BridgeMetric({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={`font-mono tabular-nums ${highlight ? "text-base font-semibold" : "text-sm"}`}
      >
        {value}
      </div>
    </div>
  );
}

function NetDebtRow({
  financialLiabilities,
  financialAssets,
  currency,
}: {
  financialLiabilities: string;
  financialAssets: string;
  currency: string;
}) {
  const netDebt =
    parseDecimal(financialLiabilities) - parseDecimal(financialAssets);
  return (
    <Row
      label="Net debt (negative = net cash)"
      value={formatCurrency(netDebt, { currency, compact: true })}
      emphasize
      tone={netDebt > 0 ? "negative" : "positive"}
    />
  );
}

function Row({
  label,
  value,
  emphasize = false,
  negative = false,
  note = false,
  tone = "neutral",
}: {
  label: string;
  value: string;
  emphasize?: boolean;
  negative?: boolean;
  note?: boolean;
  tone?: "positive" | "negative" | "neutral";
}) {
  const toneClass = {
    positive: "text-positive",
    negative: "text-negative",
    neutral: "",
  }[tone];
  const labelClass = note
    ? "text-xs text-muted-foreground"
    : "text-muted-foreground";

  return (
    <div
      className={`flex items-baseline justify-between ${emphasize ? "font-semibold" : ""}`}
    >
      <span className={labelClass}>{label}</span>
      <span
        className={`font-mono tabular-nums ${negative ? "text-muted-foreground" : ""} ${toneClass} ${note ? "text-xs" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}

function Divider() {
  return <div className="my-2 border-t border-border" />;
}
