"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { TickerSummary } from "@/lib/types/api";
import { formatDate } from "@/lib/utils/format";
import { TickerFilters, type FiltersState } from "./ticker-filters";

const initialFilters: FiltersState = {
  search: "",
  profile: "",
  currency: "",
  exchange: "",
  hasValuation: false,
};

export function TickerList({ tickers }: { tickers: TickerSummary[] }) {
  const [filters, setFilters] = useState<FiltersState>(initialFilters);

  const filtered = useMemo(() => {
    return tickers.filter((t) => {
      if (filters.search) {
        const q = filters.search.toLowerCase();
        const matchesTicker = t.ticker.toLowerCase().includes(q);
        const matchesName = t.name.toLowerCase().includes(q);
        if (!matchesTicker && !matchesName) return false;
      }
      if (filters.profile && t.profile !== filters.profile) return false;
      if (filters.currency && t.currency !== filters.currency) return false;
      if (filters.exchange && t.exchange !== filters.exchange) return false;
      if (filters.hasValuation && !t.has_valuation) return false;
      return true;
    });
  }, [tickers, filters]);

  return (
    <div className="space-y-4">
      <TickerFilters tickers={tickers} value={filters} onChange={setFilters} />

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted/30 text-left font-medium text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Ticker</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Profile</th>
              <th className="px-4 py-3">Currency</th>
              <th className="px-4 py-3">Exchange</th>
              <th className="px-4 py-3 text-center">Artifacts</th>
              <th className="px-4 py-3">Last extracted</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-8 text-center text-muted-foreground"
                >
                  No tickers match the current filters.
                </td>
              </tr>
            ) : (
              filtered.map((t) => (
                <tr
                  key={t.ticker}
                  className="border-b border-border last:border-b-0 hover:bg-muted/30"
                >
                  <td className="px-4 py-3 font-mono">
                    <Link
                      href={`/tickers/${encodeURIComponent(t.ticker)}`}
                      className="font-semibold text-primary hover:underline"
                    >
                      {t.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{t.name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs">
                      {t.profile}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{t.currency}</td>
                  <td className="px-4 py-3 text-xs">{t.exchange}</td>
                  <td className="px-4 py-3">
                    <ArtifactBadges t={t} />
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {formatDate(t.latest_extraction_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ArtifactBadges({ t }: { t: TickerSummary }) {
  const items: Array<{ label: string; title: string; present: boolean }> = [
    { label: "E", title: "Extraction", present: t.has_extraction },
    { label: "V", title: "Valuation", present: t.has_valuation },
    { label: "F", title: "Forecast", present: t.has_forecast },
    { label: "Φ", title: "Ficha", present: t.has_ficha },
  ];
  return (
    <div className="flex justify-center gap-1 font-mono text-xs">
      {items.map((it) => (
        <span
          key={it.label}
          title={it.title}
          className={
            it.present
              ? "rounded bg-positive/10 px-1.5 py-0.5 text-positive"
              : "rounded bg-muted px-1.5 py-0.5 text-muted-foreground"
          }
        >
          {it.label}
        </span>
      ))}
    </div>
  );
}
