"use client";

import { useEffect } from "react";
import type { Adjustment } from "@/lib/types/adjustments";
import type {
  CrossStatementLink,
  SourcePath,
  TraceabilityConfidence,
} from "@/lib/types/traceability";
import { useTraceability } from "@/lib/traceability/context";
import {
  formatCurrency,
  formatMultiple,
  formatPercent,
  formatPercentDirect,
} from "@/lib/utils/format";

const SECTION_TO_ID: Record<string, string> = {
  identity: "section-identity",
  "valuation-summary": "section-valuation-summary",
  "reverse-dcf": "section-reverse-dcf",
  "historical-financials": "section-historical-financials",
  "economic-balance-sheet": "section-economic-bs",
  "analytical-layer": "section-analytical-layer",
  wacc: "section-wacc",
  "cost-structure": "section-cost-structure",
  forecast: "section-forecast",
  scenarios: "section-scenarios",
  "capital-allocation": "section-capital-allocation",
  peers: "section-peers",
  "leading-indicators": "section-leading-indicators",
  "cross-check": "section-cross-check",
  audit: "section-audit",
};

/**
 * Right-hand drawer that shows the full traceability resolution for the
 * value the user clicked. Closes on backdrop click, on the X button or
 * on the Escape key. Mobile-friendly (full-width below 768px).
 */
export function SourcePanel() {
  const {
    panelOpen,
    selectedSource,
    resolution,
    closePanel,
    navigateTo,
  } = useTraceability();

  useEffect(() => {
    if (!panelOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePanel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [panelOpen, closePanel]);

  if (!selectedSource || !resolution) return null;

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-black/30 transition-opacity ${
          panelOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={closePanel}
      />

      <aside
        className={`fixed bottom-0 right-0 top-0 z-50 w-full max-w-md overflow-y-auto bg-card shadow-2xl transition-transform md:max-w-lg ${
          panelOpen ? "translate-x-0" : "translate-x-full"
        }`}
        role="dialog"
        aria-label="Source panel"
      >
        <div className="border-b border-border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1">
              <Breadcrumb source={selectedSource} />
              <h2 className="mt-1 font-mono text-base font-semibold">
                {selectedSource.label}
              </h2>
              <ValueDisplay source={selectedSource} />
            </div>
            <button
              type="button"
              onClick={closePanel}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Close panel"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="space-y-6 p-4">
          <Section title="Source path">
            <SourcePathDisplay logical={selectedSource.logical} />
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                root: {selectedSource.root}
              </span>
              {selectedSource.period ? (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                  period: {selectedSource.period}
                </span>
              ) : null}
              <ConfidenceBadge level={resolution.confidence} />
            </div>
          </Section>

          {resolution.formula ? (
            <Section title="Formula">
              <code className="block break-words rounded bg-muted p-2 font-mono text-xs">
                {resolution.formula}
              </code>
            </Section>
          ) : null}

          {resolution.adjustments.adjustments.length > 0 ? (
            <Section
              title={`Adjustment chain (${resolution.adjustments.adjustments.length})`}
            >
              <AdjustmentChainView
                adjustments={resolution.adjustments.adjustments}
              />
            </Section>
          ) : (
            <Section title="Adjustment chain">
              <p className="text-xs text-muted-foreground">
                No Module D adjustments touched this value — raw extracted
                figure or pure derivation from reported inputs.
              </p>
            </Section>
          )}

          {resolution.cross_links.length > 0 ? (
            <Section title="Navigate to">
              <div className="space-y-2">
                {resolution.cross_links.map((link, idx) => (
                  <CrossLinkButton
                    key={idx}
                    link={link}
                    onClick={() => {
                      const sectionId = SECTION_TO_ID[link.target_section];
                      if (sectionId) {
                        navigateTo({
                          sectionId,
                          rowLabel: link.target_row_label,
                        });
                      }
                    }}
                  />
                ))}
              </div>
            </Section>
          ) : null}

          {resolution.documents.length > 0 ? (
            <Section title="Source documents">
              <ul className="list-disc space-y-1 pl-5 text-xs">
                {resolution.documents.map((doc, idx) => (
                  <li key={idx} className="font-mono">
                    {doc}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      </aside>
    </>
  );
}

function Breadcrumb({ source }: { source: SourcePath }) {
  const parts = source.logical.split(/[.[\]]/).filter(Boolean);
  return (
    <nav className="flex flex-wrap gap-1 text-xs text-muted-foreground">
      {parts.map((part, idx) => (
        <span key={idx} className="font-mono">
          {idx > 0 ? "/" : ""}
          {part}
        </span>
      ))}
    </nav>
  );
}

function ValueDisplay({ source }: { source: SourcePath }) {
  if (source.value === null) {
    return <p className="mt-1 text-sm text-muted-foreground">—</p>;
  }

  let display: string;
  switch (source.format) {
    case "currency":
      display = formatCurrency(source.value, { compact: true });
      break;
    case "percent_fraction":
      display = formatPercent(source.value, 2);
      break;
    case "percent_direct":
      display = formatPercentDirect(source.value, 2);
      break;
    case "multiple":
      display = formatMultiple(source.value, 2);
      break;
    default:
      display = String(source.value);
  }

  return <p className="mt-1 font-mono text-2xl tabular-nums">{display}</p>;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function AdjustmentChainView({
  adjustments,
}: {
  adjustments: Adjustment[];
}) {
  return (
    <div className="space-y-2">
      {adjustments.map((adj, idx) => (
        <div
          key={idx}
          className="rounded-md border border-border bg-background p-3 text-sm"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-xs font-semibold">{adj.module}</span>
            <ConfidenceBadge level={adj.source.confidence} />
          </div>
          <p className="mt-1 text-sm">{adj.description}</p>
          <p className="mt-1 text-xs text-muted-foreground">{adj.rationale}</p>
          <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2 text-xs">
            <span className="break-words font-mono text-muted-foreground">
              {adj.source.document}
            </span>
            <span className="font-mono tabular-nums font-semibold">
              {adj.amount}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function CrossLinkButton({
  link,
  onClick,
}: {
  link: CrossStatementLink;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-baseline justify-between gap-3 rounded-md border border-border bg-background p-3 text-left text-sm hover:bg-muted/30"
    >
      <div className="flex-1">
        <div className="font-mono text-sm font-semibold">
          {link.target_row_label}
        </div>
        <div className="text-xs text-muted-foreground">{link.description}</div>
      </div>
      <span className="text-muted-foreground">→</span>
    </button>
  );
}

// Sprint QA — explanatory tooltips for the confidence vocabulary.
const CONFIDENCE_DESCRIPTIONS: Record<TraceabilityConfidence, string> = {
  REPORTED:
    "Value taken directly from the source document without modification.",
  ESTIMATED:
    "Value computed using estimation methodology where direct figures are unavailable.",
  INFERRED:
    "Value derived from indirect signals; manual review recommended.",
  DERIVED:
    "Value computed from REPORTED inputs through a documented formula.",
};

function ConfidenceBadge({ level }: { level: TraceabilityConfidence }) {
  const styles: Record<TraceabilityConfidence, string> = {
    REPORTED: "border-positive/30 bg-positive/10 text-positive",
    ESTIMATED: "border-amber-500/30 bg-amber-500/10 text-amber-600",
    INFERRED: "border-destructive/30 bg-destructive/10 text-destructive",
    DERIVED: "border-blue-500/30 bg-blue-500/10 text-blue-600",
  };
  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-xs ${styles[level]}`}
      title={CONFIDENCE_DESCRIPTIONS[level]}
    >
      {level}
    </span>
  );
}

/**
 * Source path display with copy-to-clipboard. ``navigator.clipboard``
 * requires a secure context (HTTPS or localhost); on plain HTTP through
 * Tailscale the API is undefined — we fall back to a manual select via
 * ``document.execCommand`` and silently no-op if neither works.
 */
function SourcePathDisplay({ logical }: { logical: string }) {
  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(logical).catch(() => {
        /* ignored — copy is best-effort */
      });
      return;
    }
    if (typeof document === "undefined") return;
    // Fallback for non-secure contexts.
    const textarea = document.createElement("textarea");
    textarea.value = logical;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
    } catch {
      /* swallow */
    }
    document.body.removeChild(textarea);
  };

  return (
    <div className="flex items-start gap-2">
      <code className="block flex-1 break-words rounded bg-muted p-2 font-mono text-xs">
        {logical}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        className="shrink-0 rounded border border-input bg-background px-2 py-1 text-xs hover:bg-accent"
        aria-label="Copy source path"
        title="Copy to clipboard"
      >
        Copy
      </button>
    </div>
  );
}
