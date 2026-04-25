import type { CanonicalState } from "@/lib/types/canonical";
import {
  formatMultiple,
  formatPercentDirect,
  parseDecimal,
} from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

/**
 * Section 6 — analytical layer.
 *
 * The PTE canonical state ships :class:`KeyRatios` rows per period already;
 * we render them as a wide ratio matrix grouped by category (profitability,
 * returns on capital, leverage, working capital cycle).
 *
 * Sprint 1B.1 — CRITICAL FIX: ``ratios_by_period`` stores ratios as
 * percentage strings (``"16.17"`` ≡ 16.17%, ``"8.20"`` ≡ 8.20%), not as
 * fractions. The Sprint 1A version pushed them through :func:`formatPercent`,
 * which assumes a fraction input and multiplies by 100 — surfacing the
 * 1,617.74% operating-margin bug. This section now uses
 * :func:`formatPercentDirect` for percent ratios and :func:`formatMultiple`
 * for ``net_debt_ebitda`` (a ratio, not a percentage).
 */
export function AnalyticalLayer({ canonical }: Props) {
  const ratios = canonical.analysis?.ratios_by_period ?? [];
  const periods = ratios.map((r) => r.period.label);

  return (
    <SectionShell
      title="Analytical Layer"
      subtitle="Ratios from canonical analysis · stored as percentages"
    >
      {ratios.length === 0 ? (
        <EmptySectionNote message="No KeyRatios entries available — run the canonical analysis pipeline." />
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="sticky left-0 bg-muted/30 px-3 py-2">Ratio</th>
                  {periods.map((p) => (
                    <th key={p} className="px-3 py-2 text-right font-mono">
                      {p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <CategoryRow label="Profitability" cols={periods.length + 1} />
                <RatioRow
                  label="Operating margin (reported)"
                  values={ratios.map((r) => r.operating_margin)}
                  format="percent_direct"
                />
                <RatioRow
                  label="Operating margin (sustainable)"
                  values={ratios.map((r) => r.sustainable_operating_margin)}
                  format="percent_direct"
                  indent
                />
                <RatioRow
                  label="EBITDA margin"
                  values={ratios.map((r) => r.ebitda_margin)}
                  format="percent_direct"
                />
                <RatioRow
                  label="Return on sales (ROS)"
                  values={ratios.map((r) => r.ros)}
                  format="percent_direct"
                />

                <CategoryRow
                  label="Returns on capital"
                  cols={periods.length + 1}
                />
                <RatioRow
                  label="ROIC (sustainable)"
                  values={ratios.map((r) => r.roic)}
                  format="percent_direct"
                  emphasize
                />
                <RatioRow
                  label="ROIC (reported)"
                  values={ratios.map((r) => r.roic_reported)}
                  format="percent_direct"
                  indent
                />
                <RatioRow
                  label="ROIC (lease-adjusted)"
                  values={ratios.map((r) => r.roic_adj_leases)}
                  format="percent_direct"
                  indent
                />
                <RatioRow
                  label="ROE"
                  values={ratios.map((r) => r.roe)}
                  format="percent_direct"
                  emphasize
                />

                <CategoryRow label="Leverage" cols={periods.length + 1} />
                <RatioRow
                  label="Net debt / EBITDA"
                  values={ratios.map((r) => r.net_debt_ebitda)}
                  format="multiple"
                />
                <RatioRow
                  label="Capex / Revenue"
                  values={ratios.map((r) => r.capex_revenue)}
                  format="percent_direct"
                />

                <CategoryRow
                  label="Working capital cycle"
                  cols={periods.length + 1}
                />
                <RatioRow
                  label="DSO (days sales outstanding)"
                  values={ratios.map((r) => r.dso)}
                  format="days"
                />
                <RatioRow
                  label="DPO (days payable outstanding)"
                  values={ratios.map((r) => r.dpo)}
                  format="days"
                />
                <RatioRow
                  label="DIO (days inventory outstanding)"
                  values={ratios.map((r) => r.dio)}
                  format="days"
                />
              </tbody>
            </table>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            Ratios stored as percentages in canonical analysis (e.g. ROIC{" "}
            <code className="font-mono">&quot;8.20&quot;</code> = 8.20%). Net debt /
            EBITDA shown as a multiple. Sustainable metrics exclude
            non-recurring items per Module D classifications.
          </p>

          {ratios.length < 2 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Single period only — multi-period trend analysis available when
              the canonical state contains 2+ periods of ratios.
            </p>
          ) : null}
        </>
      )}
    </SectionShell>
  );
}

function CategoryRow({ label, cols }: { label: string; cols: number }) {
  return (
    <tr className="bg-muted/40">
      <td
        colSpan={cols}
        className="sticky left-0 bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase text-muted-foreground"
      >
        {label}
      </td>
    </tr>
  );
}

function RatioRow({
  label,
  values,
  format,
  emphasize = false,
  indent = false,
}: {
  label: string;
  values: (string | null)[];
  format: "percent_direct" | "multiple" | "days";
  emphasize?: boolean;
  indent?: boolean;
}) {
  return (
    <tr
      className={`border-t border-border ${emphasize ? "bg-muted/20 font-semibold" : ""}`}
    >
      <td
        className={`sticky left-0 bg-card px-3 py-2 ${indent ? "pl-8" : ""}`}
      >
        {label}
      </td>
      {values.map((v, i) => (
        <td key={i} className="px-3 py-2 text-right font-mono tabular-nums">
          {renderRatio(v, format)}
        </td>
      ))}
    </tr>
  );
}

function renderRatio(
  value: string | null,
  format: "percent_direct" | "multiple" | "days",
): string {
  if (value === null || value === undefined) return "—";
  if (format === "percent_direct") return formatPercentDirect(value, 2);
  if (format === "multiple") return formatMultiple(value, 2);
  const num = parseDecimal(value);
  if (Number.isNaN(num)) return "—";
  return `${num.toFixed(0)}d`;
}

