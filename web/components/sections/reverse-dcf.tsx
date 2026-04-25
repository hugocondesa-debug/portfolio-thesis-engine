import type { ValuationSnapshot } from "@/lib/types/valuation";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot;
}

/**
 * Sprint 1A.1 — guards against ``valuation.reverse === null`` (current
 * production state) instead of treating an empty object as data.
 *
 * Sprint 1B.1 — sharpens the empty-state copy to point at Sprint 1B.2 for
 * the structured market-implied vs base-scenario comparison; pretty-prints
 * the payload as a fallback when the backend does start surfacing data.
 */
export function ReverseDCF({ valuation }: Props) {
  const reverse = valuation.reverse;
  const populated = reverse !== null && Object.keys(reverse).length > 0;

  return (
    <SectionShell
      title="Reverse DCF"
      subtitle="Market-implied assumptions vs base scenario"
      className={populated ? undefined : "border-dashed"}
    >
      {!populated ? (
        <p className="text-sm text-muted-foreground">
          No reverse-DCF block in the latest valuation snapshot. Run{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            pte reverse {valuation.ticker}
          </code>{" "}
          to populate. Once available, Sprint 1B.2 will render the structured
          comparison: market-implied revenue growth, margin, and terminal
          multiple side-by-side with the base scenario assumptions.
        </p>
      ) : (
        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(reverse, null, 2)}
        </pre>
      )}
    </SectionShell>
  );
}
