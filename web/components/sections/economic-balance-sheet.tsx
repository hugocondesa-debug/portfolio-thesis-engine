import type { CanonicalState } from "@/lib/types/canonical";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";
import { EmptySectionNote, SectionShell } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

/**
 * Sprint 1A.1 — reads from ``canonical.analysis.invested_capital_by_period[0]``
 * (newest period). Surfaces the cross-check residual so the analyst can see
 * whether the operating-vs-financing identity holds (zero = exact match).
 */
export function EconomicBalanceSheet({ canonical }: Props) {
  const periods = canonical.analysis?.invested_capital_by_period ?? [];
  const latest = periods[0];
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
                <Row
                  label="Operating working capital"
                  value={formatCurrency(latest.operating_working_capital, {
                    currency,
                    compact: true,
                  })}
                  note
                />
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
                <Row
                  label="    Bank debt"
                  value={formatCurrency(latest.bank_debt, {
                    currency,
                    compact: true,
                  })}
                  note
                />
                <Row
                  label="    Lease liabilities"
                  value={formatCurrency(latest.lease_liabilities, {
                    currency,
                    compact: true,
                  })}
                  note
                />
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
