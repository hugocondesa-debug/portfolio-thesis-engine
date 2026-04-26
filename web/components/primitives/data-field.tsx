import type { ReactNode } from "react";

interface Props {
  /** Label */
  label: string;
  /** Value */
  value: ReactNode;
  /** Mono font for the value */
  mono?: boolean;
}

/**
 * Compact ``label`` over ``value`` display — used in dl grids inside
 * pipeline-trace summaries and small badge clusters.
 */
export function DataField({ label, value, mono = false }: Props) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={
          mono ? "mt-0.5 font-mono text-sm tabular-nums" : "mt-0.5 text-sm"
        }
      >
        {value}
      </div>
    </div>
  );
}
