import type { CanonicalState, KeyRatios } from "@/lib/types/canonical";
import { formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell, EmptySectionNote } from "./section-shell";

interface Props {
  canonical: CanonicalState;
}

/**
 * Section 6 — analytical layer.
 *
 * The PTE canonical state ships :class:`KeyRatios` rows for each period
 * already; we render them as a wide ratio matrix and overlay a quick
 * DuPont 3-way decomposition where the underlying components exist.
 */
export function AnalyticalLayer({ canonical }: Props) {
  const ratios = orderRatios(canonical.analysis.ratios_by_period);
  const periods = ratios.map((r) => r.period.label);

  return (
    <SectionShell
      title="Analytical Layer"
      subtitle="DuPont decomposition + ratio trends"
    >
      {ratios.length === 0 ? (
        <EmptySectionNote message="No KeyRatios entries available." />
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="sticky left-0 bg-muted/30 px-3 py-2">Ratio</th>
                  {periods.map((p) => (
                    <th
                      key={p}
                      className="px-3 py-2 text-right font-mono"
                    >
                      {p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <RatioRow
                  label="Operating margin"
                  values={ratios.map((r) => r.operating_margin)}
                />
                <RatioRow
                  label="Sustainable OI margin"
                  values={ratios.map((r) => r.sustainable_operating_margin)}
                />
                <RatioRow
                  label="EBITDA margin"
                  values={ratios.map((r) => r.ebitda_margin)}
                />
                <RatioRow
                  label="Capex / revenue"
                  values={ratios.map((r) => r.capex_revenue)}
                />
                <RatioRow
                  label="ROIC (sustainable)"
                  values={ratios.map((r) => r.roic)}
                  emphasize
                />
                <RatioRow
                  label="ROIC (reported)"
                  values={ratios.map((r) => r.roic_reported)}
                />
                <RatioRow
                  label="ROE"
                  values={ratios.map((r) => r.roe)}
                  emphasize
                />
                <RatioRow
                  label="Return on sales (ROS)"
                  values={ratios.map((r) => r.ros)}
                />
              </tbody>
            </table>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            Ratios pre-computed by the PTE analytical layer. Sustainable
            metrics strip non-recurring items; reported metrics match the
            audited filing.
          </p>
        </>
      )}
    </SectionShell>
  );
}

function orderRatios(ratios: KeyRatios[]): KeyRatios[] {
  return [...ratios].sort((a, b) => {
    if (a.period.year !== b.period.year) return a.period.year - b.period.year;
    return (a.period.quarter ?? 0) - (b.period.quarter ?? 0);
  });
}

function RatioRow({
  label,
  values,
  emphasize = false,
}: {
  label: string;
  values: (string | null)[];
  emphasize?: boolean;
}) {
  return (
    <tr
      className={`border-t border-border ${emphasize ? "bg-muted/20 font-semibold" : ""}`}
    >
      <td className="sticky left-0 bg-card px-3 py-2">{label}</td>
      {values.map((v, i) => (
        <td
          key={i}
          className="px-3 py-2 text-right font-mono tabular-nums"
        >
          {v === null || v === undefined || Number.isNaN(parseDecimal(v))
            ? "—"
            : formatPercent(v, 2)}
        </td>
      ))}
    </tr>
  );
}
