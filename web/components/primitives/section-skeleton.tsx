interface Props {
  /** Title shown above the loading bars (currently unused — reserved for
   *  future Suspense fallbacks where the section title is known up front). */
  title?: string;
  /** Number of body lines to render. Default 4. */
  lines?: number;
}

const SKELETON_LINE_WIDTHS = ["75%", "82%", "68%", "89%", "73%", "85%", "70%"];

/**
 * Animated loading placeholder for a section.
 *
 * Sprint QA — provided as future-proofing for streaming Suspense fallbacks.
 * The current page orchestrator awaits all data server-side via
 * ``Promise.all`` so this placeholder is not yet rendered in production.
 *
 * Uses a deterministic width pattern (rather than ``Math.random()``) so SSR
 * and CSR markup match — Sprint QA discovered the random version caused
 * hydration warnings.
 */
export function SectionSkeleton({ lines = 4 }: Props) {
  return (
    <div className="rounded-md border border-border bg-card p-6">
      <div className="mb-4">
        <div className="h-4 w-32 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-3 w-48 animate-pulse rounded bg-muted/60" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, idx) => (
          <div
            key={idx}
            className="h-3 animate-pulse rounded bg-muted/40"
            style={{
              width: SKELETON_LINE_WIDTHS[idx % SKELETON_LINE_WIDTHS.length],
            }}
          />
        ))}
      </div>
    </div>
  );
}
