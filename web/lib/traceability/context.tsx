"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
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
 *
 * Sprint QA — browser back-button integration:
 *
 * - Opening the panel pushes a history state ``{ traceabilityPanel: true }``
 *   (only when not already on top, so re-clicking different values inside
 *   the panel doesn't stack history).
 * - Closing the panel via the X button or a cross-link calls
 *   ``history.back()`` so the address bar stays clean.
 * - Pressing the browser back button while the panel is open triggers
 *   ``popstate``; the handler closes the panel without re-popping (the
 *   ``closingViaPopstateRef`` flag prevents the double-pop loop with
 *   ``closePanel``).
 * - If the user navigates via an in-app link to another page, the history
 *   state is replaced naturally — popstate doesn't fire on app
 *   navigation, so no cleanup is needed.
 */
export function TraceabilityProvider({ canonical, children }: ProviderProps) {
  const [selectedSource, setSelectedSource] = useState<SourcePath | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const closingViaPopstateRef = useRef(false);

  const resolution = selectedSource
    ? resolveTraceability(selectedSource, canonical)
    : null;

  const openPanel = useCallback((source: SourcePath) => {
    setSelectedSource(source);
    setPanelOpen(true);
    if (typeof window === "undefined") return;
    const state = window.history.state as { traceabilityPanel?: boolean } | null;
    if (!state?.traceabilityPanel) {
      window.history.pushState({ traceabilityPanel: true }, "");
    }
  }, []);

  const closePanel = useCallback(() => {
    setPanelOpen(false);
    // Keep selectedSource for the slide-out animation, then clear.
    setTimeout(() => setSelectedSource(null), 300);
    if (typeof window === "undefined") return;
    const state = window.history.state as { traceabilityPanel?: boolean } | null;
    if (state?.traceabilityPanel) {
      // Pop the panel state so the address bar is clean; tell the popstate
      // handler to skip its own close work.
      closingViaPopstateRef.current = true;
      window.history.back();
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = () => {
      if (closingViaPopstateRef.current) {
        closingViaPopstateRef.current = false;
        return;
      }
      // If panel is open and the user pressed the browser back button,
      // close it gracefully without page navigation.
      setPanelOpen(false);
      setTimeout(() => setSelectedSource(null), 300);
    };
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
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
