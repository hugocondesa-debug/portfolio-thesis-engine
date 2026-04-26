import type { ReactNode } from "react";

interface Props {
  /** Section title */
  title: string;
  /** Empty-state explanation */
  message: ReactNode;
  /** Optional action hint (e.g. shell command to run) */
  action?: ReactNode;
}

/**
 * Consistent empty state shown when a section has no data.
 *
 * Sprint QA — extracted to keep the empty-state vocabulary uniform across
 * the 16 sections. Prefer this over ad-hoc dashed-border ``<section>``
 * blocks for new code.
 */
export function EmptyState({ title, message, action }: Props) {
  return (
    <div className="rounded-md border border-dashed border-border bg-card p-6">
      <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      {action ? (
        <div className="mt-3 text-xs text-muted-foreground">{action}</div>
      ) : null}
    </div>
  );
}
