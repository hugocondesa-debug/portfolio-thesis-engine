import Link from "next/link";
import {
  getCanonical,
  getCapitalAllocation,
  getCrossCheckLog,
  getFicha,
  getForecast,
  getPeers,
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
import { ForecastDetail } from "@/components/sections/forecast-detail";
import { ScenariosDetail } from "@/components/sections/scenarios-detail";
import { CapitalAllocationSection } from "@/components/sections/capital-allocation";
import { PeersComparison } from "@/components/sections/peers-comparison";
import { LeadingIndicators } from "@/components/sections/leading-indicators";
import { CrossCheckDetail } from "@/components/sections/cross-check-detail";
import { AuditProvenance } from "@/components/sections/audit-provenance";
import { TraceabilityProvider } from "@/lib/traceability/context";
import { SourcePanel } from "@/components/traceability/source-panel";

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
  const [valuation, forecast, ficha, capitalAllocation, peers, crossCheck] =
    await Promise.all([
      getValuation(ticker).catch(() => null),
      getForecast(ticker).catch(() => null),
      getFicha(ticker).catch(() => null),
      getCapitalAllocation(ticker).catch(() => null),
      getPeers(ticker).catch(() => null),
      getCrossCheckLog(ticker).catch(() => null),
    ]);

  return (
    <TraceabilityProvider canonical={canonical}>
      <Header />

      <main className="mx-auto max-w-screen-2xl space-y-6 px-3 py-4 md:px-6 md:py-6">
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
        <div id="section-identity">
          <IdentityHeader
            detail={detail}
            canonical={canonical}
            ficha={ficha}
            valuation={valuation}
          />
        </div>

        {/* 2 — Valuation Summary */}
        <div id="section-valuation-summary">
          {valuation ? (
            <ValuationSummary valuation={valuation} canonical={canonical} />
          ) : (
            <EmptySection
              title="Valuation Summary"
              message="No valuation snapshot yet. Run `pte valuation`."
            />
          )}
        </div>

        {/* 3 — Reverse DCF */}
        {valuation ? (
          <div id="section-reverse-dcf">
            <ReverseDCF valuation={valuation} />
          </div>
        ) : null}

        {/* 4 — Historical Financials */}
        <div id="section-historical-financials">
          <HistoricalFinancials canonical={canonical} />
        </div>

        {/* 5 — Economic Balance Sheet */}
        <div id="section-economic-bs">
          <EconomicBalanceSheet canonical={canonical} />
        </div>

        {/* 6 — Analytical Layer */}
        <div id="section-analytical-layer">
          <AnalyticalLayer canonical={canonical} />
        </div>

        {/* 7 — WACC Build-up */}
        {valuation ? (
          <div id="section-wacc">
            <WaccBuildup valuation={valuation} canonical={canonical} />
          </div>
        ) : (
          <EmptySection
            title="WACC Build-up"
            message="WACC components require a valuation snapshot."
          />
        )}

        {/* 8 — Cost Structure */}
        <div id="section-cost-structure">
          <CostStructure canonical={canonical} />
        </div>

        {/* 9 — Forecast Detail */}
        <div id="section-forecast">
          <ForecastDetail
            forecast={forecast}
            valuation={valuation}
            canonical={canonical}
          />
        </div>

        {/* 10 — Scenarios Detail */}
        <div id="section-scenarios">
          <ScenariosDetail valuation={valuation} canonical={canonical} />
        </div>

        {/* 11 — Capital Allocation */}
        <div id="section-capital-allocation">
          <CapitalAllocationSection
            capitalAllocation={capitalAllocation}
            forecast={forecast}
            canonical={canonical}
          />
        </div>

        {/* 13 — Peers Comparison (Sprint 1C) */}
        <div id="section-peers">
          <PeersComparison peers={peers} canonical={canonical} />
        </div>

        {/* 14 — Leading Indicators (Sprint 1C) */}
        <div id="section-leading-indicators">
          <LeadingIndicators valuation={valuation} canonical={canonical} />
        </div>

        {/* 15 — Cross-check & Guardrails (Sprint 1C) */}
        <div id="section-cross-check">
          <CrossCheckDetail
            crossCheck={crossCheck}
            valuation={valuation}
            canonical={canonical}
          />
        </div>

        {/* 16 — Audit / Provenance (Sprint 1C) */}
        <div id="section-audit">
          <AuditProvenance canonical={canonical} valuation={valuation} />
        </div>
      </main>

      {/* Global drilldown drawer (Sprint 1C). */}
      <SourcePanel />
    </TraceabilityProvider>
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
