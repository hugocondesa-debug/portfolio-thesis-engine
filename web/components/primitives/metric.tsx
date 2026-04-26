import type { ReactNode } from "react";

interface Props {
  /** Label */
  label: string;
  /** Formatted value */
  value: ReactNode;
  /** Optional subtitle */
  subtitle?: string;
  /** Highlight as primary metric (larger font) */
  highlight?: boolean;
  /** Tone for value color */
  tone?: "positive" | "negative" | "neutral";
  /** Use mono font for the value (default ``true``) */
  mono?: boolean;
}

/**
 * Boxed metric card — label + value with optional subtitle.
 * Used for KPIs in valuation summary, WACC, forecast detail, etc.
 *
 * Sprint QA — extracted from inline definitions across multiple sections.
 */
export function Metric({
  label,
  value,
  subtitle,
  highlight = false,
  tone = "neutral",
  mono = true,
}: Props) {
  const toneClass = {
    positive: "text-positive",
    negative: "text-negative",
    neutral: "",
  }[tone];

  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={`mt-1 ${mono ? "font-mono" : ""} tabular-nums ${
          highlight ? "text-2xl font-semibold" : "text-lg"
        } ${toneClass}`}
      >
        {value}
      </div>
      {subtitle ? (
        <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div>
      ) : null}
    </div>
  );
}
