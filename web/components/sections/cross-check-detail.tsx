import type { CanonicalState } from "@/lib/types/canonical";
import type {
  CheckStatus,
  CrossCheckMetric,
  CrossCheckResponse,
} from "@/lib/types/cross-check";
import type {
  GuardrailsResult,
  ValuationSnapshot,
} from "@/lib/types/valuation";
import { formatCurrency, parseDecimal } from "@/lib/utils/format";
import { SectionShell } from "./section-shell";

interface Props {
  crossCheck: CrossCheckResponse | null;
  valuation: ValuationSnapshot | null;
  canonical: CanonicalState;
}

/**
 * Section 15 — Cross-check & Guardrails detail.
 *
 * Sprint 1C — surfaces the per-metric provider validation log
 * (canonical extraction vs FMP / yfinance) plus the Phase 1 stub
 * guardrails block from the valuation snapshot. ``max_delta_pct`` is
 * stored as a fraction on the wire (``"0.1033"`` ≡ 10.33%).
 */
export function CrossCheckDetail({
  crossCheck,
  valuation,
  canonical,
}: Props) {
  if (!crossCheck) {
    return (
      <SectionShell
        title="Cross-check & Guardrails"
        subtitle="Provider validation and pipeline guardrails"
        className="border-dashed"
      >
        <p className="text-sm text-muted-foreground">
          No cross-check log available. Run the pipeline with audited data to
          validate against external providers.
        </p>
      </SectionShell>
    );
  }

  const currency = canonical.identity.reporting_currency;

  const passCount = crossCheck.metrics.filter((m) => m.status === "PASS").length;
  const warnCount = crossCheck.metrics.filter((m) => m.status === "WARN").length;
  const failCount = crossCheck.metrics.filter((m) => m.status === "FAIL").length;

  const guardrails = valuation?.guardrails;

  return (
    <SectionShell
      title="Cross-check & Guardrails"
      subtitle={`${crossCheck.metrics.length} metrics validated for ${crossCheck.period} · overall ${crossCheck.overall_status}`}
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <StatusBadge status="PASS" count={passCount} />
        <StatusBadge status="WARN" count={warnCount} />
        {failCount > 0 ? <StatusBadge status="FAIL" count={failCount} /> : null}
        {crossCheck.blocking ? (
          <span className="rounded border border-destructive/30 bg-destructive/10 px-2 py-0.5 font-mono text-xs text-destructive">
            BLOCKING
          </span>
        ) : null}
      </div>

      <div className="mb-6">
        <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
          Cross-check metrics ({crossCheck.period})
        </h3>
        <CrossCheckTable metrics={crossCheck.metrics} currency={currency} />
      </div>

      {crossCheck.provider_errors ? (
        <div className="mb-6">
          <h3 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Provider errors
          </h3>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(crossCheck.provider_errors, null, 2)}
          </pre>
        </div>
      ) : null}

      {guardrails ? (
        <div>
          <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Pipeline guardrails
          </h3>
          <GuardrailsView guardrails={guardrails} />
        </div>
      ) : null}

      <p className="mt-4 text-xs text-muted-foreground">
        Cross-check generated at{" "}
        {new Date(crossCheck.generated_at).toLocaleString()} · Log path:{" "}
        <code className="rounded bg-muted px-1 py-0.5">
          {crossCheck.log_path}
        </code>
      </p>
    </SectionShell>
  );
}

function StatusBadge({
  status,
  count,
}: {
  status: CheckStatus;
  count: number;
}) {
  const styles: Record<CheckStatus, string> = {
    PASS: "border-positive/30 bg-positive/10 text-positive",
    WARN: "border-amber-500/30 bg-amber-500/10 text-amber-600",
    FAIL: "border-destructive/30 bg-destructive/10 text-destructive",
  };
  return (
    <span
      className={`rounded border px-2 py-0.5 font-mono text-xs ${styles[status]}`}
    >
      {status}: {count}
    </span>
  );
}

function CrossCheckTable({
  metrics,
  currency,
}: {
  metrics: CrossCheckMetric[];
  currency: string;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Metric</th>
            <th className="px-3 py-2 text-right">Extracted</th>
            <th className="px-3 py-2 text-right">FMP</th>
            <th className="px-3 py-2 text-right">yfinance</th>
            <th className="px-3 py-2 text-right">Max Δ</th>
            <th className="px-3 py-2 text-center">Status</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <CrossCheckRow
              key={metric.metric}
              metric={metric}
              currency={currency}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CrossCheckRow({
  metric,
  currency,
}: {
  metric: CrossCheckMetric;
  currency: string;
}) {
  return (
    <tr className="border-t border-border" title={metric.notes}>
      <td className="px-3 py-2 font-mono text-xs">{metric.metric}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">
        {metric.extracted_value
          ? formatCurrency(metric.extracted_value, { currency, compact: true })
          : "—"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {metric.fmp_value
          ? formatCurrency(metric.fmp_value, { currency, compact: true })
          : "—"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {metric.yfinance_value
          ? formatCurrency(metric.yfinance_value, { currency, compact: true })
          : "—"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">
        {metric.max_delta_pct ? formatDeltaPct(metric.max_delta_pct) : "—"}
      </td>
      <td className="px-3 py-2 text-center">
        <StatusPill status={metric.status} />
      </td>
    </tr>
  );
}

function formatDeltaPct(value: string): string {
  const num = parseDecimal(value);
  if (Number.isNaN(num)) return "—";
  return `${(num * 100).toFixed(2)}%`;
}

function StatusPill({ status }: { status: CheckStatus }) {
  const styles: Record<CheckStatus, string> = {
    PASS: "bg-positive/10 text-positive",
    WARN: "bg-amber-500/10 text-amber-600",
    FAIL: "bg-destructive/10 text-destructive",
  };
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-xs ${styles[status]}`}
    >
      {status}
    </span>
  );
}

function GuardrailsView({
  guardrails,
}: {
  guardrails: GuardrailsResult | unknown[];
}) {
  // Phase 1 stub heuristic — categories list with all-zero counts and a notes string
  const isPhase1Stub = isStubGuardrails(guardrails);

  if (isPhase1Stub) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        <p>
          Pipeline guardrails are a Phase 1 stub. Currently logged on canonical
          state only with no detailed checks.
        </p>
        <p className="mt-2 text-xs">
          Sprint 4B.1 backend enhancement will populate richer guardrails (8
          explicit checks: IS/BS/CF checksum, IC consistency, cross-check
          pass-through, WACC consistency, etc.). Until then, the cross-check
          metrics above are the primary validation signal.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border p-3">
      <pre className="text-xs">{JSON.stringify(guardrails, null, 2)}</pre>
    </div>
  );
}

function isStubGuardrails(guardrails: GuardrailsResult | unknown[]): boolean {
  if (Array.isArray(guardrails)) return true;
  const cats = guardrails.categories as unknown;

  // Empty / missing categories → stub (object form before backend wires
  // detailed checks).
  if (!cats) return true;
  if (Array.isArray(cats)) {
    if (cats.length === 0) return true;
    const first = cats[0] as Record<string, unknown> | undefined;
    return !first || first.total === 0;
  }
  if (typeof cats === "object") {
    return Object.keys(cats).length === 0;
  }
  return false;
}
