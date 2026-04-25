import type { ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

/**
 * Standard section wrapper — used by every Section 1–8 component so they
 * share the same border, padding, and header treatment.
 */
export function SectionShell({
  title,
  subtitle,
  actions,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-md border border-border bg-card p-6", className)}>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="font-mono text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </h2>
          {subtitle ? (
            <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function EmptySectionNote({ message }: { message: string }) {
  return (
    <p className="text-sm text-muted-foreground">{message}</p>
  );
}
