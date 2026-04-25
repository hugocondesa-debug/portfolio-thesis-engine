import type { CanonicalState, InvestedCapital } from "@/lib/types/canonical";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

export function EconomicBalanceSheet({ canonical }: Props) {
  const series = canonical.analysis.invested_capital_by_period;
  const currency = canonical.identity.reporting_currency;

  // Latest period — invested_capital_by_period is ordered newest-first.
  const latest: InvestedCapital | undefined = series[0];

  return (
    <SectionShell
      title="Economic Balance Sheet"
      subtitle="Operating vs financing — invested-capital view"
    >
      {latest ? (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <SidePanel
              title="Operating side"
              currency={currency}
              rows={[
                { label: "Operating assets", value: latest.operating_assets },
                {
                  label: "Operating liabilities",
                  value: latest.operating_liabilities,
                  negative: true,
                },
              ]}
              total={{
                label: "Invested capital",
                value: latest.invested_capital,
              }}
            />

            <SidePanel
              title="Financing side"
              currency={currency}
              rows={[
                {
                  label: "Financial assets (incl. cash)",
                  value: latest.financial_assets,
                },
                {
                  label: "Financial liabilities (debt + leases)",
                  value: latest.financial_liabilities,
                  negative: true,
                },
              ]}
              total={{
                label: "Equity claims",
                value: latest.equity_claims,
                tone:
                  parseDecimal(latest.financial_assets)
                    > parseDecimal(latest.financial_liabilities)
                    ? "positive"
                    : "negative",
              }}
            />
          </div>

          <p className="mt-6 text-xs text-muted-foreground">
            Period {latest.period.label}. Cross-check residual:{" "}
            <span className="font-mono">
              {formatCurrency(latest.cross_check_residual, {
                currency,
                compact: true,
              })}
            </span>
            .
            {parseDecimal(latest.cross_check_residual) === 0
              ? " Identity holds exactly."
              : " Residual exposed for diagnostic review."}
          </p>
        </>
      ) : (
        <EmptySectionNote message="No invested-capital periods available in the canonical state." />
      )}
    </SectionShell>
  );
}

interface PanelRow {
  label: string;
  value: string;
  negative?: boolean;
}

function SidePanel({
  title,
  currency,
  rows,
  total,
}: {
  title: string;
  currency: string;
  rows: PanelRow[];
  total: { label: string; value: string; tone?: "positive" | "negative" };
}) {
  return (
    <div className="rounded-md border border-border p-4">
      <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-2 text-sm">
        {rows.map((row) => (
          <Row
            key={row.label}
            label={row.label}
            value={formatCurrency(row.value, { currency, compact: true })}
            negative={row.negative}
          />
        ))}
        <div className="my-2 border-t border-border" />
        <Row
          label={total.label}
          value={formatCurrency(total.value, { currency, compact: true })}
          emphasize
          tone={total.tone}
        />
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  emphasize = false,
  negative = false,
  tone = "neutral",
}: {
  label: string;
  value: string;
  emphasize?: boolean;
  negative?: boolean;
  tone?: "positive" | "negative" | "neutral";
}) {
  const toneClass = {
    positive: "text-positive",
    negative: "text-negative",
    neutral: "",
  }[tone];

  return (
    <div
      className={`flex items-baseline justify-between ${emphasize ? "font-semibold" : ""}`}
    >
      <span className="text-muted-foreground">{label}</span>
      <span
        className={`font-mono tabular-nums ${negative ? "text-muted-foreground" : ""} ${toneClass}`}
      >
        {value}
      </span>
    </div>
  );
}
