import type { TickerDetail } from "@/lib/types/api";
import {
  resolveAuditStatus,
  resolveLatestPeriodLabel,
  type AuditStatus,
  type CanonicalState,
} from "@/lib/types/canonical";
import type { Ficha } from "@/lib/types/ficha";
import type { ValuationSnapshot } from "@/lib/types/valuation";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils/format";

interface Props {
  detail: TickerDetail;
  canonical: CanonicalState;
  ficha: Ficha | null;
  valuation: ValuationSnapshot | null;
}

export function IdentityHeader({ detail, canonical, ficha, valuation }: Props) {
  const identity = canonical.identity;

  // Sprint 1A.1 — prefer valuation.market for live price/shares; canonical
  // identity is a backstop because canonical.identity.market_contexts is
  // typically empty in PTE today.
  const marketPrice = valuation?.market.price ?? null;
  const marketPriceDate = valuation?.market.price_date ?? null;
  const sharesOutstanding =
    valuation?.market.shares_outstanding ?? identity.shares_outstanding;
  const currency =
    valuation?.market.currency ?? identity.reporting_currency;

  const auditStatus = resolveAuditStatus(canonical);
  const currentPeriod = resolveLatestPeriodLabel(canonical);

  return (
    <section className="rounded-md border border-border bg-card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-mono text-2xl font-semibold tracking-tight">
              {detail.ticker}
            </h1>
            <AuditBadge status={auditStatus} />
            <PeriodBadge period={currentPeriod} />
          </div>
          <p className="mt-1 text-base text-muted-foreground">
            {identity.name}
          </p>
          {identity.legal_name && identity.legal_name !== identity.name ? (
            <p className="text-xs text-muted-foreground">
              {identity.legal_name}
            </p>
          ) : null}
        </div>

        {marketPrice ? (
          <div className="text-right">
            <div className="font-mono text-2xl font-semibold tabular-nums">
              {formatCurrency(marketPrice, { currency, decimals: 2 })}
            </div>
            <div className="text-xs text-muted-foreground">
              Market price · {formatDate(marketPriceDate)}
            </div>
          </div>
        ) : null}
      </div>

      {auditStatus !== "audited" ? (
        <div className="mt-4 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
          <p className="font-medium text-amber-700 dark:text-amber-400">
            Caution: this snapshot is based on{" "}
            <strong>{auditStatus}</strong> data ({currentPeriod}). External
            cross-checks may have been skipped — re-run with{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
              --base-period LATEST-AUDITED
            </code>{" "}
            for an audited basis.
          </p>
        </div>
      ) : null}

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
        <DataRow label="Profile" value={identity.profile} mono />
        <DataRow label="Currency" value={currency} mono />
        <DataRow label="Exchange" value={identity.exchange} />
        <DataRow label="Domicile" value={identity.country_domicile} />
        <DataRow label="ISIN" value={identity.isin ?? "—"} mono />
        <DataRow
          label="Shares outstanding"
          value={formatNumber(sharesOutstanding, { compact: true })}
          mono
        />
        <DataRow label="Sector" value={identity.sector_gics ?? "—"} />
        <DataRow
          label="FY end"
          value={`Month ${identity.fiscal_year_end_month}`}
        />
      </dl>

      {ficha?.thesis ? (
        <div className="mt-6 rounded-md bg-muted/40 p-4 text-sm">
          <h3 className="mb-1 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Thesis
          </h3>
          <p className="text-foreground">{ficha.thesis}</p>
        </div>
      ) : null}
    </section>
  );
}

function AuditBadge({ status }: { status: AuditStatus }) {
  const styles: Record<AuditStatus, string> = {
    audited: "bg-positive/10 text-positive border-positive/30",
    reviewed: "bg-amber-500/10 text-amber-600 border-amber-500/30",
    preliminary: "bg-destructive/10 text-destructive border-destructive/30",
    unaudited: "bg-destructive/10 text-destructive border-destructive/30",
  };
  return (
    <span
      className={`rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wide ${styles[status]}`}
    >
      {status}
    </span>
  );
}

function PeriodBadge({ period }: { period: string }) {
  return (
    <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
      {period}
    </span>
  );
}

function DataRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className={mono ? "font-mono text-sm" : "text-sm"}>{value}</dd>
    </div>
  );
}
