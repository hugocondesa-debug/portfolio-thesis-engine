import type { TickerDetail } from "@/lib/types/api";
import {
  resolveAuditStatus,
  resolveLatestPeriodLabel,
  type AuditStatus,
  type CanonicalState,
} from "@/lib/types/canonical";
import type { Ficha } from "@/lib/types/ficha";
import type {
  ConvictionLevel,
  GuardrailsResult,
  ValuationSnapshot,
} from "@/lib/types/valuation";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils/format";

interface Props {
  detail: TickerDetail;
  canonical: CanonicalState;
  ficha: Ficha | null;
  valuation: ValuationSnapshot | null;
}

interface ConvictionDisplay {
  forecast: ConvictionLevel;
  valuation: ConvictionLevel;
  asymmetry: ConvictionLevel;
  timing_risk: ConvictionLevel;
  liquidity_risk: ConvictionLevel;
  governance_risk: ConvictionLevel;
}

export function IdentityHeader({ detail, canonical, ficha, valuation }: Props) {
  const identity = canonical.identity;

  // Sprint 1A.1 — prefer valuation.market for live price/shares; canonical
  // identity is a backstop because canonical.identity.market_contexts is
  // typically empty in PTE today.
  const marketPrice = valuation?.market.price ?? null;
  const marketPriceDate = valuation?.market.price_date ?? null;
  const sharesOutstanding =
    valuation?.market.shares_outstanding ?? identity.shares_outstanding;
  const currency =
    valuation?.market.currency ?? identity.reporting_currency;

  const auditStatus = resolveAuditStatus(canonical);
  const currentPeriod = resolveLatestPeriodLabel(canonical);

  const guardrails = resolveGuardrails(valuation?.guardrails);
  const conviction = resolveConviction(ficha, valuation);

  return (
    <section className="rounded-md border border-border bg-card p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-2xl font-semibold tracking-tight">
              {detail.ticker}
            </h1>
            <AuditBadge status={auditStatus} />
            <PeriodBadge period={currentPeriod} />
            {guardrails ? <GuardrailBadge overall={guardrails.overall} /> : null}
          </div>
          <p className="mt-1 text-base text-muted-foreground">
            {identity.name}
          </p>
          {identity.legal_name && identity.legal_name !== identity.name ? (
            <p className="text-xs text-muted-foreground">
              {identity.legal_name}
            </p>
          ) : null}
        </div>

        {marketPrice ? (
          <div className="text-right">
            <div className="font-mono text-2xl font-semibold tabular-nums">
              {formatCurrency(marketPrice, { currency, decimals: 2 })}
            </div>
            <div className="text-xs text-muted-foreground">
              Market price · {formatDate(marketPriceDate)}
            </div>
          </div>
        ) : null}
      </div>

      {auditStatus !== "audited" ? (
        <div className="mt-4 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
          <p className="font-medium text-amber-700 dark:text-amber-400">
            Caution: this snapshot is based on{" "}
            <strong>{auditStatus}</strong> data ({currentPeriod}). External
            cross-checks may have been skipped — re-run with{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
              --base-period LATEST-AUDITED
            </code>{" "}
            for an audited basis.
          </p>
        </div>
      ) : null}

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
        <DataRow label="Profile" value={identity.profile} mono />
        <DataRow label="Currency" value={currency} mono />
        <DataRow label="Exchange" value={identity.exchange} />
        <DataRow label="Domicile" value={identity.country_domicile} />
        <DataRow label="ISIN" value={identity.isin ?? "—"} mono />
        <DataRow
          label="Shares outstanding"
          value={formatNumber(sharesOutstanding, { compact: true })}
          mono
        />
        <DataRow label="Sector" value={identity.sector_gics ?? "—"} />
        <DataRow
          label="FY end"
          value={`Month ${identity.fiscal_year_end_month}`}
        />
      </dl>

      {conviction ? (
        <div className="mt-6">
          <h3 className="mb-3 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Conviction scores
          </h3>
          <ConvictionGrid conviction={conviction} />
        </div>
      ) : null}

      {ficha?.thesis ? (
        <div className="mt-6 rounded-md bg-muted/40 p-4 text-sm">
          <h3 className="mb-1 font-mono text-xs font-semibold uppercase text-muted-foreground">
            Thesis
          </h3>
          <p className="text-foreground">{ficha.thesis}</p>
        </div>
      ) : null}
    </section>
  );
}

function ConvictionGrid({ conviction }: { conviction: ConvictionDisplay }) {
  const dimensions: Array<[string, ConvictionLevel, string]> = [
    ["Forecast", conviction.forecast, "Confidence in projection assumptions"],
    ["Valuation", conviction.valuation, "Confidence in valuation methodology"],
    ["Asymmetry", conviction.asymmetry, "Reward/risk balance"],
    ["Timing", conviction.timing_risk, "Catalyst timing risk"],
    ["Liquidity", conviction.liquidity_risk, "Trading liquidity risk"],
    ["Governance", conviction.governance_risk, "Management quality risk"],
  ];

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
      {dimensions.map(([label, level, hint]) => (
        <ConvictionPill key={label} label={label} level={level} hint={hint} />
      ))}
    </div>
  );
}

function ConvictionPill({
  label,
  level,
  hint,
}: {
  label: string;
  level: ConvictionLevel;
  hint: string;
}) {
  const styles: Record<ConvictionLevel, string> = {
    high: "bg-positive/10 text-positive border-positive/30",
    medium: "bg-amber-500/10 text-amber-600 border-amber-500/30",
    low: "bg-destructive/10 text-destructive border-destructive/30",
  };
  return (
    <div
      className={`rounded-md border px-3 py-2 text-sm ${styles[level]}`}
      title={hint}
    >
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold">{level}</div>
    </div>
  );
}

function AuditBadge({ status }: { status: AuditStatus }) {
  const styles: Record<AuditStatus, string> = {
    audited: "bg-positive/10 text-positive border-positive/30",
    reviewed: "bg-amber-500/10 text-amber-600 border-amber-500/30",
    preliminary: "bg-destructive/10 text-destructive border-destructive/30",
    unaudited: "bg-destructive/10 text-destructive border-destructive/30",
  };
  return (
    <span
      className={`rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wide ${styles[status]}`}
    >
      {status}
    </span>
  );
}

function PeriodBadge({ period }: { period: string }) {
  return (
    <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
      {period}
    </span>
  );
}

function GuardrailBadge({
  overall,
}: {
  overall: GuardrailsResult["overall"];
}) {
  const styles: Record<GuardrailsResult["overall"], string> = {
    PASS: "bg-positive/10 text-positive border-positive/30",
    WARN: "bg-amber-500/10 text-amber-600 border-amber-500/30",
    FAIL: "bg-destructive/10 text-destructive border-destructive/30",
  };
  return (
    <span
      className={`rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wide ${styles[overall]}`}
      title="Pipeline guardrails overall status"
    >
      Guardrails: {overall}
    </span>
  );
}

function DataRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className={mono ? "font-mono text-sm" : "text-sm"}>{value}</dd>
    </div>
  );
}

/**
 * The valuation snapshot's ``guardrails`` field is typed as
 * ``GuardrailsResult | unknown[]`` because legacy snapshots stored it as an
 * empty list. Narrow to the structured form when possible; otherwise return
 * null so the badge is hidden gracefully.
 */
function resolveGuardrails(
  guardrails: ValuationSnapshot["guardrails"] | undefined,
): GuardrailsResult | null {
  if (!guardrails || Array.isArray(guardrails)) return null;
  if (typeof guardrails !== "object") return null;
  const overall = (guardrails as { overall?: unknown }).overall;
  if (overall !== "PASS" && overall !== "WARN" && overall !== "FAIL") {
    return null;
  }
  return guardrails as GuardrailsResult;
}

/**
 * Conviction may live on ficha (string fields) or valuation (literal levels).
 * Normalise both to the strict ``ConvictionLevel`` triplet expected by the
 * grid; unrecognised values fall back to ``"medium"``.
 */
function resolveConviction(
  ficha: Ficha | null,
  valuation: ValuationSnapshot | null,
): ConvictionDisplay | null {
  const source = ficha?.conviction ?? valuation?.conviction ?? null;
  if (!source) return null;
  return {
    forecast: normaliseLevel(source.forecast),
    valuation: normaliseLevel(source.valuation),
    asymmetry: normaliseLevel(source.asymmetry),
    timing_risk: normaliseLevel(source.timing_risk),
    liquidity_risk: normaliseLevel(source.liquidity_risk),
    governance_risk: normaliseLevel(source.governance_risk),
  };
}

function normaliseLevel(value: unknown): ConvictionLevel {
  if (value === "high" || value === "medium" || value === "low") return value;
  if (typeof value === "string") {
    const lower = value.toLowerCase();
    if (lower === "high" || lower === "medium" || lower === "low") {
      return lower;
    }
  }
  return "medium";
}
