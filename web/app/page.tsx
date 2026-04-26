import { listTickers } from "@/lib/api/endpoints";
import { Header } from "@/components/layout/header";
import { TickerList } from "@/components/tickers/ticker-list";

export default async function HomePage() {
  const tickers = await listTickers();

  return (
    <>
      <Header />
      <main className="mx-auto max-w-screen-2xl px-3 py-4 md:px-6 md:py-8">
        <div className="mb-6 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="font-mono text-2xl font-semibold tracking-tight">
            Tickers
          </h1>
          <p className="text-sm text-muted-foreground">
            {tickers.length} {tickers.length === 1 ? "ticker" : "tickers"}
          </p>
        </div>

        <TickerList tickers={tickers} />
      </main>
    </>
  );
}
