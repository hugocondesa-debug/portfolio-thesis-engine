/**
 * Typed wrappers for every PTE API endpoint consumed by the frontend.
 * Server Components and Server Actions call these directly; client code
 * goes through the proxy routes under ``app/api/`` instead.
 */

import yaml from "js-yaml";

import { serverFetch } from "./server";
import type {
  TickerDetail,
  TickerSummary,
  YamlListItem,
  YamlVersion,
} from "@/lib/types/api";
import type { CanonicalState } from "@/lib/types/canonical";
import type { CapitalAllocation } from "@/lib/types/capital-allocation";
import type { CrossCheckResponse } from "@/lib/types/cross-check";
import type { Ficha } from "@/lib/types/ficha";
import type { ForecastResult } from "@/lib/types/forecast";
import type { PeersResponse } from "@/lib/types/peers";
import type { ValuationSnapshot } from "@/lib/types/valuation";

const enc = encodeURIComponent;

// --- Ticker discovery -------------------------------------------------
export const listTickers = (): Promise<TickerSummary[]> =>
  serverFetch<TickerSummary[]>("/api/tickers");

export const getTicker = (ticker: string): Promise<TickerDetail> =>
  serverFetch<TickerDetail>(`/api/tickers/${enc(ticker)}`);

// --- Per-ticker artefacts --------------------------------------------
export const getCanonical = (ticker: string): Promise<CanonicalState> =>
  serverFetch<CanonicalState>(`/api/tickers/${enc(ticker)}/canonical`);

export const getValuation = (ticker: string): Promise<ValuationSnapshot> =>
  serverFetch<ValuationSnapshot>(`/api/tickers/${enc(ticker)}/valuation`);

export const getForecast = (ticker: string): Promise<ForecastResult> =>
  serverFetch<ForecastResult>(`/api/tickers/${enc(ticker)}/forecast`);

export const getFicha = (ticker: string): Promise<Ficha> =>
  serverFetch<Ficha>(`/api/tickers/${enc(ticker)}/ficha`);

export const getCrossCheck = (ticker: string): Promise<unknown> =>
  serverFetch<unknown>(`/api/tickers/${enc(ticker)}/cross-check`);

/**
 * Sprint 1C — typed alternative to ``getCrossCheck`` (which kept its
 * ``Promise<unknown>`` signature for backwards compatibility). Returns
 * ``null`` on any error so callers can render the empty state.
 */
export async function getCrossCheckLog(
  ticker: string,
): Promise<CrossCheckResponse | null> {
  try {
    return await serverFetch<CrossCheckResponse>(
      `/api/tickers/${enc(ticker)}/cross-check`,
    );
  } catch {
    return null;
  }
}

/**
 * Sprint 1C — fully-typed peers fetcher. Returns ``null`` when the YAML
 * is missing or the endpoint errors so the section can render the empty
 * configuration prompt.
 */
export async function getPeers(
  ticker: string,
): Promise<PeersResponse | null> {
  try {
    return await serverFetch<PeersResponse>(
      `/api/tickers/${enc(ticker)}/peers`,
    );
  } catch {
    return null;
  }
}

// --- Yamls -----------------------------------------------------------
export const listYamls = (ticker: string): Promise<YamlListItem[]> =>
  serverFetch<YamlListItem[]>(`/api/tickers/${enc(ticker)}/yamls`);

export const downloadYaml = (
  ticker: string,
  name: string,
): Promise<string> =>
  serverFetch<string>(`/api/tickers/${enc(ticker)}/yamls/${enc(name)}`);

export const listYamlVersions = (
  ticker: string,
  name: string,
): Promise<YamlVersion[]> =>
  serverFetch<YamlVersion[]>(
    `/api/tickers/${enc(ticker)}/yamls/${enc(name)}/versions`,
  );

/**
 * Fetches and parses ``capital_allocation.yaml`` for a ticker.
 *
 * Sprint 1B.2 — backend is frozen so we re-use the generic yaml proxy
 * endpoint and parse the YAML in the frontend with ``js-yaml``. We pass
 * ``JSON_SCHEMA`` so ISO date strings stay strings (the default schema
 * would convert them to ``Date`` objects, which downstream components
 * don't expect).
 *
 * Returns ``null`` on any error (404 when the YAML doesn't exist, parse
 * errors, etc.) so callers can fall back to the empty-state UI.
 */
export async function getCapitalAllocation(
  ticker: string,
): Promise<CapitalAllocation | null> {
  try {
    const yamlText = await serverFetch<string>(
      `/api/tickers/${enc(ticker)}/yamls/capital_allocation`,
    );
    if (!yamlText || typeof yamlText !== "string") return null;
    const parsed = yaml.load(yamlText, { schema: yaml.JSON_SCHEMA });
    if (!parsed || typeof parsed !== "object") return null;
    return parsed as CapitalAllocation;
  } catch {
    return null;
  }
}
