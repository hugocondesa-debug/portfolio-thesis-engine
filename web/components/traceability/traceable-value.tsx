"use client";

import type { ReactNode } from "react";
import type { SourcePath } from "@/lib/types/traceability";
import { useOptionalTraceability } from "@/lib/traceability/context";

interface Props {
  /**
   * Source path metadata. ``logical`` is optional — when omitted, a default
   * is constructed from ``root`` + ``period`` + ``field``.
   */
  source: Omit<SourcePath, "logical"> & { logical?: string };
  /** Show a hover tooltip via ``title`` attribute (default ``true``). */
  withTooltip?: boolean;
  /** Children — typically the formatted value text. */
  children: ReactNode;
  /** Additional CSS classes appended to the wrapper. */
  className?: string;
}

/**
 * Wraps any displayed value to make it click-to-trace.
 *
 * Sprint 1C — clicking the wrapped span opens the
 * :func:`SourcePanel` drawer with the resolved source path, formula,
 * adjustment chain and cross-statement links. Falls back to plain text
 * when no :class:`TraceabilityProvider` is mounted in the parent tree
 * (so the component is safe to drop in anywhere).
 */
export function TraceableValue({
  source,
  withTooltip = true,
  children,
  className = "",
}: Props) {
  const traceability = useOptionalTraceability();

  if (!traceability) {
    return <span className={className}>{children}</span>;
  }

  const fullSource: SourcePath = {
    logical:
      source.logical ??
      `${source.root}${source.period ? `.[${source.period}]` : "."}${source.field}`,
    root: source.root,
    period: source.period,
    field: source.field,
    label: source.label,
    value: source.value,
    format: source.format,
  };

  return (
    <span
      className={`cursor-pointer underline decoration-dotted decoration-muted-foreground underline-offset-2 hover:decoration-primary ${className}`}
      onClick={() => traceability.openPanel(fullSource)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          traceability.openPanel(fullSource);
        }
      }}
      role="button"
      tabIndex={0}
      title={withTooltip ? `${fullSource.label} — click for source` : undefined}
    >
      {children}
    </span>
  );
}
