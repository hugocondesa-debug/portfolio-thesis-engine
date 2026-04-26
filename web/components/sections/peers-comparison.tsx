import type { CanonicalState } from "@/lib/types/canonical";
import type { PeerEntry, PeersResponse, SqlitePeer } from "@/lib/types/peers";
import { SectionShell } from "./section-shell";

interface Props {
  peers: PeersResponse | null;
  canonical: CanonicalState;
}

/**
 * Section 13 — Peers Comparison.
 *
 * Sprint 1C — combines the curated peer YAML with the (currently empty)
 * sqlite multiples cache. When the cache is populated by Sprint 4B.1
 * backend work, the multiples table replaces the empty state. For now
 * the section surfaces the peer list with country / currency / source /
 * inclusion badges so the analyst can vouch for the comparable set.
 */
export function PeersComparison({ peers, canonical }: Props) {
  if (!peers) {
    return (
      <SectionShell
        title="Peers Comparison"
        subtitle="Cross-currency multiples and sector benchmark"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No peers configuration. Create{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            data/yamls/companies/{canonical.identity.ticker}/peers.yaml
          </code>{" "}
          and re-run the pipeline.
        </p>
      </SectionShell>
    );
  }

  const yaml = peers.yaml;
  const includedCount = yaml.peers.filter((p) => p.included).length;
  const discoveryLabel = yaml.discovery_method.toLowerCase().replace(/_/g, " ");

  return (
    <SectionShell
      title="Peers Comparison"
      subtitle={`${includedCount} of ${yaml.peers.length} peers included · ${discoveryLabel}`}
    >
      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        {yaml.fmp_sector ? (
          <span className="rounded bg-muted px-2 py-0.5 font-mono">
            Sector: {yaml.fmp_sector}
          </span>
        ) : null}
        {yaml.fmp_industry ? (
          <span className="rounded bg-muted px-2 py-0.5 font-mono">
            Industry: {yaml.fmp_industry}
          </span>
        ) : null}
      </div>

      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Peer set
        </h3>
        <div className="space-y-2">
          {yaml.peers.map((peer) => (
            <PeerCard key={peer.ticker} peer={peer} />
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Multiples comparison
        </h3>
        <MultiplesComparison
          targetTicker={canonical.identity.ticker}
          targetCurrency={canonical.identity.reporting_currency}
          sqlitePeers={peers.sqlite_peers}
          yamlPeers={yaml.peers.filter((p) => p.included)}
        />
      </div>
    </SectionShell>
  );
}

function PeerCard({ peer }: { peer: PeerEntry }) {
  const opacity = peer.included ? "" : "opacity-50";

  return (
    <div className={`rounded-md border border-border bg-card p-3 ${opacity}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">
            {peer.ticker}
          </span>
          <span className="text-sm text-muted-foreground">{peer.name}</span>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <CountryBadge country={peer.country} />
          <CurrencyBadge currency={peer.listing_currency} />
          <SourceBadge source={peer.source} />
          <IncludedBadge included={peer.included} />
        </div>
      </div>

      <p className="mt-2 text-xs text-muted-foreground">{peer.rationale}</p>
    </div>
  );
}

function CountryBadge({ country }: { country: string }) {
  return (
    <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{country}</span>
  );
}

function CurrencyBadge({ currency }: { currency: string }) {
  return (
    <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{currency}</span>
  );
}

function SourceBadge({ source }: { source: string }) {
  const display = source === "USER_OVERRIDE" ? "USER" : source;
  return (
    <span
      className="rounded bg-muted px-1.5 py-0.5 font-mono text-muted-foreground"
      title={`Discovery: ${source}`}
    >
      {display}
    </span>
  );
}

function IncludedBadge({ included }: { included: boolean }) {
  if (included) {
    return (
      <span className="rounded border border-positive/30 bg-positive/10 px-1.5 py-0.5 font-mono text-xs text-positive">
        Included
      </span>
    );
  }
  return (
    <span className="rounded border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 font-mono text-xs text-destructive">
      Excluded
    </span>
  );
}

function MultiplesComparison({
  targetTicker,
  targetCurrency,
  sqlitePeers,
  yamlPeers,
}: {
  targetTicker: string;
  targetCurrency: string;
  sqlitePeers: SqlitePeer[];
  yamlPeers: PeerEntry[];
}) {
  if (sqlitePeers.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        <p>
          Multiples cache empty for{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            {targetTicker}
          </code>
          . Run peer multiples enrichment to populate (Sprint 4B.1 backend
          enhancement).
        </p>
        <p className="mt-2 text-xs">
          Currently configured peers:{" "}
          {yamlPeers.map((p) => p.ticker).join(", ")}. Multiples (PER, P/B,
          EV/EBITDA, EV/Sales) will display once the sqlite peers cache is
          populated.
        </p>
      </div>
    );
  }

  return (
    <MultiplesTable peers={sqlitePeers} targetCurrency={targetCurrency} />
  );
}

interface MultiplesField {
  key: keyof SqlitePeer;
  label: string;
  format: "multiple" | "currency_compact" | "string";
}

function MultiplesTable({
  peers,
  targetCurrency: _targetCurrency,
}: {
  peers: SqlitePeer[];
  targetCurrency: string;
}) {
  const fields: MultiplesField[] = [
    { key: "ticker", label: "Ticker", format: "string" },
    { key: "name", label: "Name", format: "string" },
    {
      key: "market_cap_usd",
      label: "Market cap (USD)",
      format: "currency_compact",
    },
    { key: "per", label: "P/E", format: "multiple" },
    { key: "pb", label: "P/B", format: "multiple" },
    { key: "ev_ebitda", label: "EV/EBITDA", format: "multiple" },
    { key: "ev_sales", label: "EV/Sales", format: "multiple" },
  ];

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            {fields.map((f) => (
              <th
                key={String(f.key)}
                className={`px-3 py-2 ${f.format !== "string" ? "text-right" : ""}`}
              >
                {f.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {peers.map((peer) => (
            <tr key={peer.ticker} className="border-t border-border">
              {fields.map((f) => (
                <td
                  key={String(f.key)}
                  className={`px-3 py-2 font-mono tabular-nums ${
                    f.format !== "string" ? "text-right" : ""
                  }`}
                >
                  {formatPeerValue(peer[f.key], f.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatPeerValue(
  value: unknown,
  format: "multiple" | "currency_compact" | "string",
): string {
  if (value === null || value === undefined) return "—";
  if (format === "string") return String(value);
  if (typeof value !== "string" && typeof value !== "number") return "—";

  const num = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(num)) return "—";

  if (format === "multiple") return `${num.toFixed(2)}×`;
  if (format === "currency_compact") {
    if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`;
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(0)}M`;
    return num.toFixed(0);
  }
  return String(value);
}
