"use client";

import type { ReactNode } from "react";

interface Props {
  /** Logical source path shown via the native ``title`` tooltip. */
  source: string;
  children: ReactNode;
  className?: string;
}

/**
 * Light traceability hint — hover tooltip only, no panel drilldown.
 *
 * Sprint 1C — used in sections 13-16 where deep traceability isn't
 * applicable (peer multiples, sensitivity grids, audit logs already
 * surface their own provenance).
 */
export function SourceTooltip({ source, children, className = "" }: Props) {
  return (
    <span className={`cursor-help ${className}`} title={source}>
      {children}
    </span>
  );
}
