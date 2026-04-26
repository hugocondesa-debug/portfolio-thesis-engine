import type { ReactNode } from "react";

interface Props {
  /** Label on the left */
  label: string;
  /** Value on the right (string or ReactNode for traceable wrapping) */
  children: ReactNode;
  /** Emphasize as primary line (semibold) */
  emphasize?: boolean;
  /** Indented secondary row */
  indent?: boolean;
  /** Note styling — smaller text */
  note?: boolean;
  /** De-emphasise visually (e.g. parenthesised negative) */
  negative?: boolean;
  /** Tone for value color */
  tone?: "positive" | "negative" | "neutral";
}

/**
 * Labeled key-value row used in financial tables and side panels.
 *
 * Sprint QA — extracted from the various per-section ``Row`` helpers.
 * Accepts ReactNode children so callers can wrap the value with a
 * :class:`TraceableValue` for click-to-trace.
 */
export function DataRow({
  label,
  children,
  emphasize = false,
  indent = false,
  note = false,
  negative = false,
  tone = "neutral",
}: Props) {
  const toneClass = {
    positive: "text-positive",
    negative: "text-negative",
    neutral: "",
  }[tone];

  const labelClass = note
    ? "text-xs text-muted-foreground"
    : "text-muted-foreground";
  const indentClass = indent ? "pl-4" : "";

  return (
    <div
      className={`flex items-baseline justify-between ${emphasize ? "font-semibold" : ""}`}
    >
      <span className={`${labelClass} ${indentClass}`}>{label}</span>
      <span
        className={`font-mono tabular-nums ${negative ? "text-muted-foreground" : ""} ${toneClass} ${note ? "text-xs" : ""}`}
      >
        {children}
      </span>
    </div>
  );
}
