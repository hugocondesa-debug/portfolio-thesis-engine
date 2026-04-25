import Link from "next/link";
import {
  getCanonical,
  getFicha,
  getTicker,
  getValuation,
} from "@/lib/api/endpoints";
import { Header } from "@/components/layout/header";
import { IdentityHeader } from "@/components/sections/identity-header";
import { ValuationSummary } from "@/components/sections/valuation-summary";
import { ReverseDCF } from "@/components/sections/reverse-dcf";
import { HistoricalFinancials } from "@/components/sections/historical-financials";
import { EconomicBalanceSheet } from "@/components/sections/economic-balance-sheet";
import { AnalyticalLayer } from "@/components/sections/analytical-layer";
import { WaccBuildup } from "@/components/sections/wacc-buildup";
import { CostStructure } from "@/components/sections/cost-structure";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function TickerPage({ params }: PageProps) {
  const { ticker: tickerParam } = await params;
  const ticker = decodeURIComponent(tickerParam);

  // Required data — failures here propagate to error.tsx.
  const [detail, canonical] = await Promise.all([
    getTicker(ticker),
    getCanonical(ticker),
  ]);

  // Optional artefacts — sections render placeholders when absent.
  const [valuation, ficha] = await Promise.all([
    getValuation(ticker).catch(() => null),
    getFicha(ticker).catch(() => null),
  ]);

  return (
    <>
      <Header />

      <main className="mx-auto max-w-screen-2xl space-y-6 px-6 py-6">
        <div className="flex items-center justify-between">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Back to tickers
          </Link>
          <Link
            href={`/tickers/${encodeURIComponent(ticker)}/yamls`}
            className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent"
          >
            Manage yamls
          </Link>
        </div>

        {/* 1 — Identity */}
        <IdentityHeader
          detail={detail}
          canonical={canonical}
          ficha={ficha}
          valuation={valuation}
        />

        {/* 2 — Valuation Summary */}
        {valuation ? (
          <ValuationSummary valuation={valuation} canonical={canonical} />
        ) : (
          <EmptySection
            title="Valuation Summary"
            message="No valuation snapshot yet. Run `pte valuation`."
          />
        )}

        {/* 3 — Reverse DCF */}
        {valuation ? <ReverseDCF valuation={valuation} /> : null}

        {/* 4 — Historical Financials */}
        <HistoricalFinancials canonical={canonical} />

        {/* 5 — Economic Balance Sheet */}
        <EconomicBalanceSheet canonical={canonical} />

        {/* 6 — Analytical Layer (DuPont + ratio trends) */}
        <AnalyticalLayer canonical={canonical} />

        {/* 7 — WACC Build-up */}
        {valuation ? (
          <WaccBuildup valuation={valuation} canonical={canonical} />
        ) : (
          <EmptySection
            title="WACC Build-up"
            message="WACC components require a valuation snapshot."
          />
        )}

        {/* 8 — Cost Structure */}
        <CostStructure canonical={canonical} />
      </main>
    </>
  );
}

function EmptySection({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <section className="rounded-md border border-dashed border-border bg-card p-6">
      <h2 className="font-mono text-sm font-semibold uppercase text-muted-foreground">
        {title}
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
    </section>
  );
}
