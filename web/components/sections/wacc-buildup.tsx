import type { CanonicalState } from "@/lib/types/canonical";
import type {
  GuardrailsResult,
  ValuationSnapshot,
} from "@/lib/types/valuation";
import { formatPercent, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  valuation: ValuationSnapshot;
  canonical: CanonicalState;
}

interface WaccCheckResult {
  status: "PASS" | "WARN" | "FAIL";
  message: string;
}

/**
 * Sprint 1A.1 — reads ``valuation.market.{wacc, cost_of_equity}`` (the
 * authoritative path). Geographic-mix breakdown lives in WACC inputs and is
 * not yet persisted in the snapshot — surfaced as a follow-up.
 *
 * Sprint 1B.1 — surfaces the V.2.WACC_CONSISTENCY guardrail check (PASS /
 * WARN / FAIL) when present. The guardrails schema is not strictly typed yet
 * so the lookup is best-effort; if the structure differs, the panel hides
 * gracefully.
 */
export function WaccBuildup({ valuation, canonical }: Props) {
  const wacc = parseDecimal(valuation.market.wacc) / 100;
  const coe = parseDecimal(valuation.market.cost_of_equity) / 100;
  const currency =
    valuation.market.currency ?? canonical.identity.reporting_currency;

  const waccCheck = findWaccConsistencyCheck(valuation.guardrails);

  return (
    <SectionShell
      title="WACC Build-up"
      subtitle="Cost of capital used in scenario discounting"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Metric label="Cost of equity" value={formatPercent(coe, 2)} />
        <Metric label="WACC" value={formatPercent(wacc, 2)} highlight />
        <Metric label="Currency" value={currency} />
      </div>

      {waccCheck ? (
        <div
          className={`mt-6 rounded-md border p-3 text-sm ${
            waccCheck.status === "PASS"
              ? "border-positive/30 bg-positive/5"
              : waccCheck.status === "WARN"
                ? "border-amber-500/30 bg-amber-50 dark:bg-amber-950/20"
                : "border-destructive/30 bg-destructive/5"
          }`}
        >
          <h4 className="font-mono text-xs font-semibold uppercase">
            WACC consistency check ({waccCheck.status})
          </h4>
          {waccCheck.message ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {waccCheck.message}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-6 rounded-md border border-dashed border-border p-4">
        <h4 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Pending backend exposure (Sprint 4B.1)
        </h4>
        <ul className="space-y-1 text-xs text-muted-foreground">
          <li>• Cost of equity derivation: Rf + β × ERP + CRP</li>
          <li>• Beta source (Damodaran / regression / sector default)</li>
          <li>
            • Geographic mix when company operates across multiple risk regions
          </li>
          <li>• Cost of debt + tax rate breakdown</li>
          <li>• Equity / debt weights (D / (D + E))</li>
        </ul>
      </div>
    </SectionShell>
  );
}

/**
 * Best-effort lookup of ``V.2.WACC_CONSISTENCY`` inside the snapshot's
 * guardrails block. The backend hasn't pinned the guardrails schema, so we
 * walk the categories defensively and tolerate unexpected shapes.
 */
function findWaccConsistencyCheck(
  guardrails: ValuationSnapshot["guardrails"] | undefined,
): WaccCheckResult | null {
  if (!guardrails || Array.isArray(guardrails)) return null;
  const cats = (guardrails as GuardrailsResult).categories;
  if (!cats || typeof cats !== "object") return null;

  for (const cat of Object.values(cats as Record<string, unknown>)) {
    if (typeof cat !== "object" || cat === null) continue;
    const checks = (cat as Record<string, unknown>).checks;
    if (!Array.isArray(checks)) continue;
    for (const check of checks) {
      if (typeof check !== "object" || check === null) continue;
      const c = check as Record<string, unknown>;
      if (c.id === "V.2.WACC_CONSISTENCY") {
        const rawStatus = c.status;
        const status: WaccCheckResult["status"] =
          rawStatus === "PASS" || rawStatus === "WARN" || rawStatus === "FAIL"
            ? rawStatus
            : "WARN";
        const message = typeof c.message === "string" ? c.message : "";
        return { status, message };
      }
    }
  }
  return null;
}

function Metric({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-md border border-border p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tabular-nums ${highlight ? "text-2xl font-semibold" : "text-xl"}`}
      >
        {value}
      </div>
    </div>
  );
}
