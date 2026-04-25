"use client";

import { useMemo } from "react";
import type { TickerSummary } from "@/lib/types/api";

export interface FiltersState {
  search: string;
  profile: string;
  currency: string;
  exchange: string;
  hasValuation: boolean;
}

interface Props {
  tickers: TickerSummary[];
  value: FiltersState;
  onChange: (next: FiltersState) => void;
}

export function TickerFilters({ tickers, value, onChange }: Props) {
  const profiles = useMemo(
    () => Array.from(new Set(tickers.map((t) => t.profile))).sort(),
    [tickers],
  );
  const currencies = useMemo(
    () => Array.from(new Set(tickers.map((t) => t.currency))).sort(),
    [tickers],
  );
  const exchanges = useMemo(
    () => Array.from(new Set(tickers.map((t) => t.exchange))).sort(),
    [tickers],
  );

  return (
    <div className="grid grid-cols-1 gap-3 rounded-md border border-border bg-card p-4 md:grid-cols-5">
      <input
        type="search"
        placeholder="Search ticker or name…"
        value={value.search}
        onChange={(e) => onChange({ ...value, search: e.target.value })}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm md:col-span-2"
      />

      <select
        value={value.profile}
        onChange={(e) => onChange({ ...value, profile: e.target.value })}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm"
      >
        <option value="">All profiles</option>
        {profiles.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>

      <select
        value={value.currency}
        onChange={(e) => onChange({ ...value, currency: e.target.value })}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm"
      >
        <option value="">All currencies</option>
        {currencies.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <select
        value={value.exchange}
        onChange={(e) => onChange({ ...value, exchange: e.target.value })}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm"
      >
        <option value="">All exchanges</option>
        {exchanges.map((x) => (
          <option key={x} value={x}>
            {x}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-2 text-sm md:col-span-5">
        <input
          type="checkbox"
          checked={value.hasValuation}
          onChange={(e) => onChange({ ...value, hasValuation: e.target.checked })}
          className="h-4 w-4 rounded border-input"
        />
        <span>Only with valuation</span>
      </label>
    </div>
  );
}
