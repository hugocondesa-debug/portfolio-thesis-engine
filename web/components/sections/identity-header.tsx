import type { TickerDetail } from "@/lib/types/api";
import type { CanonicalState } from "@/lib/types/canonical";
import type { Ficha } from "@/lib/types/ficha";
import { formatCurrency, formatNumber } from "@/lib/utils/format";

interface Props {
  detail: TickerDetail;
  canonical: CanonicalState;
  ficha: Ficha | null;
}

export function IdentityHeader({ detail, canonical, ficha }: Props) {
  const identity = canonical.identity;
  const marketContext = ficha?.market_contexts?.[0] ?? null;

  return (
    <section className="rounded-md border border-border bg-card p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="font-mono text-2xl font-semibold tracking-tight">
            {detail.ticker}
          </h1>
          <p className="mt-1 text-base text-muted-foreground">
            {identity.name}
          </p>
          {identity.legal_name && identity.legal_name !== identity.name ? (
            <p className="text-xs text-muted-foreground">
              {identity.legal_name}
            </p>
          ) : null}
        </div>

        {marketContext?.share_price ? (
          <div className="text-right">
            <div className="font-mono text-2xl font-semibold tabular-nums">
              {formatCurrency(marketContext.share_price, {
                currency: marketContext.currency || identity.reporting_currency,
                decimals: 2,
              })}
            </div>
            <div className="text-xs text-muted-foreground">
              Market price · {marketContext.as_of_date ?? "—"}
              {marketContext.source ? ` · ${marketContext.source}` : ""}
            </div>
          </div>
        ) : null}
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
        <DataRow label="Profile" value={identity.profile} mono />
        <DataRow label="Currency" value={identity.reporting_currency} mono />
        <DataRow label="Exchange" value={identity.exchange} />
        <DataRow label="Domicile" value={identity.country_domicile} />
        <DataRow label="ISIN" value={identity.isin ?? "—"} mono />
        <DataRow
          label="Shares outstanding"
          value={formatNumber(identity.shares_outstanding, { compact: true })}
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
