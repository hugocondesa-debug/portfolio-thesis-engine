import Link from "next/link";
import { listYamls } from "@/lib/api/endpoints";
import { Header } from "@/components/layout/header";
import { YamlList } from "@/components/yamls/yaml-list";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function YamlsPage({ params }: PageProps) {
  const { ticker: tickerParam } = await params;
  const ticker = decodeURIComponent(tickerParam);
  const yamls = await listYamls(ticker);

  return (
    <>
      <Header />
      <main className="mx-auto max-w-screen-2xl space-y-6 px-6 py-6">
        <div className="flex items-center justify-between">
          <Link
            href={`/tickers/${encodeURIComponent(ticker)}`}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Back to {ticker}
          </Link>
        </div>

        <div>
          <h1 className="font-mono text-2xl font-semibold tracking-tight">
            Yamls — {ticker}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Download to edit; upload to validate, version, and persist.
          </p>
        </div>

        <YamlList ticker={ticker} yamls={yamls} />
      </main>
    </>
  );
}
