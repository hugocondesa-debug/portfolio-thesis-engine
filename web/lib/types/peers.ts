/**
 * Peers comparison shape returned by ``/api/tickers/{ticker}/peers``.
 *
 * The endpoint combines two sources:
 *
 * - ``yaml``: the curated peer set from
 *   ``data/yamls/companies/<ticker>/peers.yaml`` (analyst-maintained list)
 * - ``sqlite_peers``: cached multiples from the peers registry; currently
 *   empty for EuroEyes — Sprint 4B.1 will populate it.
 */

import type { DecimalString } from "./api";

export interface PeersResponse {
  ticker: string;
  yaml: PeersYaml;
  sqlite_peers: SqlitePeer[];
}

export interface PeersYaml {
  target_ticker: string;
  discovery_method: "USER_MANUAL" | "FMP_AUTO" | string;
  fmp_sector: string | null;
  fmp_industry: string | null;
  peers: PeerEntry[];
  min_peers_regression: number;
  max_peers_display: number;
}

export interface PeerEntry {
  ticker: string;
  name: string;
  country: string;
  listing_currency: string;
  source: "USER_OVERRIDE" | "FMP" | string;
  rationale: string;
  included: boolean;
}

/**
 * Peer multiples cached from the registry. Schema is open-ended pending the
 * Sprint 4B.1 enrichment pass; the named fields below are the expected
 * canonical columns once the cache is populated.
 */
export interface SqlitePeer {
  ticker: string;
  name: string;
  per?: DecimalString | null;
  pb?: DecimalString | null;
  ev_ebitda?: DecimalString | null;
  ev_sales?: DecimalString | null;
  market_cap_usd?: DecimalString | null;
  [key: string]: unknown;
}
