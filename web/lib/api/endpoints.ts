/**
 * Typed wrappers for every PTE API endpoint consumed by the frontend.
 * Server Components and Server Actions call these directly; client code
 * goes through the proxy routes under ``app/api/`` instead.
 */

import { serverFetch } from "./server";
import type {
  TickerDetail,
  TickerSummary,
  YamlListItem,
  YamlVersion,
} from "@/lib/types/api";
import type { CanonicalState } from "@/lib/types/canonical";
import type { Ficha } from "@/lib/types/ficha";
import type { ForecastResult } from "@/lib/types/forecast";
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

export const getPeers = (ticker: string): Promise<unknown> =>
  serverFetch<unknown>(`/api/tickers/${enc(ticker)}/peers`);

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
