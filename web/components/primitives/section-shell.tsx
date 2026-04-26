import type { ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

interface Props {
  /** Section title */
  title: string;
  /** Optional subtitle */
  subtitle?: string;
  /** Right-aligned header actions (filter toggle, etc.) */
  actions?: ReactNode;
  /** Whether section is in empty state — renders dashed border */
  emptyState?: boolean;
  /** Additional class names appended to the wrapper */
  className?: string;
  /** Section body */
  children: ReactNode;
}

/**
 * Standard section wrapper — used by every Section 1–16 component so they
 * share the same border, padding, and header treatment.
 *
 * Sprint QA — moved here from ``components/sections/section-shell.tsx``;
 * the old path now re-exports from this module for back-compat with
 * existing imports.
 */
export function SectionShell({
  title,
  subtitle,
  actions,
  emptyState = false,
  className,
  children,
}: Props) {
  const borderClass = emptyState ? "border-dashed" : "";
  return (
    <section
      className={cn(
        // Sprint QA — tighter padding on mobile (≤768px) so 360px viewports
        // don't lose ~80px of horizontal space to ``p-6``.
        "rounded-md border border-border bg-card p-4 md:p-6",
        borderClass,
        className,
      )}
    >
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <SectionHeader title={title} subtitle={subtitle} />
        {actions}
      </div>
      {children}
    </section>
  );
}

/**
 * Reusable section header — title + optional subtitle. Useful when a
 * section needs to render its own outer wrapper but still wants the
 * shared header treatment.
 */
export function SectionHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div>
      <h2 className="font-mono text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {subtitle ? (
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      ) : null}
    </div>
  );
}

/**
 * Plain note paragraph used inside a SectionShell when the section has no
 * data — kept for back-compat. New code should prefer
 * :func:`EmptyState` from ``primitives/empty-state``.
 */
export function EmptySectionNote({ message }: { message: string }) {
  return <p className="text-sm text-muted-foreground">{message}</p>;
}
