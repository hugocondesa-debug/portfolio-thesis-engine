"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import type { CanonicalState } from "@/lib/types/canonical";
import type {
  SourcePath,
  TraceabilityResolution,
} from "@/lib/types/traceability";
import { resolveTraceability } from "@/lib/traceability/registry";

interface NavigateTarget {
  sectionId: string;
  rowLabel?: string;
}

interface TraceabilityContextValue {
  selectedSource: SourcePath | null;
  resolution: TraceabilityResolution | null;
  panelOpen: boolean;
  openPanel: (source: SourcePath) => void;
  closePanel: () => void;
  navigateTo: (target: NavigateTarget) => void;
}

const TraceabilityContext = createContext<TraceabilityContextValue | null>(
  null,
);

interface ProviderProps {
  canonical: CanonicalState;
  children: ReactNode;
}

/**
 * Wraps a sub-tree with traceability state. Holds the currently selected
 * source path + open panel state, computes resolution lazily, and exposes
 * cross-statement navigation hooks.
 */
export function TraceabilityProvider({ canonical, children }: ProviderProps) {
  const [selectedSource, setSelectedSource] = useState<SourcePath | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const resolution = selectedSource
    ? resolveTraceability(selectedSource, canonical)
    : null;

  const openPanel = useCallback((source: SourcePath) => {
    setSelectedSource(source);
    setPanelOpen(true);
  }, []);

  const closePanel = useCallback(() => {
    setPanelOpen(false);
    // Keep selectedSource for the slide-out animation, then clear.
    setTimeout(() => setSelectedSource(null), 300);
  }, []);

  const navigateTo = useCallback(
    ({ sectionId, rowLabel }: NavigateTarget) => {
      if (typeof document === "undefined") return;
      const element = document.getElementById(sectionId);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });

        if (rowLabel) {
          setTimeout(() => {
            const row = element.querySelector(
              `[data-row-label="${CSS.escape(rowLabel)}"]`,
            );
            if (row) {
              row.scrollIntoView({ behavior: "smooth", block: "center" });
              row.classList.add("highlight-row");
              setTimeout(() => row.classList.remove("highlight-row"), 2000);
            }
          }, 400);
        }
      }
      closePanel();
    },
    [closePanel],
  );

  return (
    <TraceabilityContext.Provider
      value={{
        selectedSource,
        resolution,
        panelOpen,
        openPanel,
        closePanel,
        navigateTo,
      }}
    >
      {children}
    </TraceabilityContext.Provider>
  );
}

export function useTraceability(): TraceabilityContextValue {
  const ctx = useContext(TraceabilityContext);
  if (!ctx) {
    throw new Error(
      "useTraceability must be used within a TraceabilityProvider",
    );
  }
  return ctx;
}

/**
 * Returns ``null`` when used outside a provider — lets components degrade
 * gracefully (rendering plain values without click-to-trace) while still
 * being safe to drop into trees that don't wire up the provider yet.
 */
export function useOptionalTraceability(): TraceabilityContextValue | null {
  return useContext(TraceabilityContext);
}
