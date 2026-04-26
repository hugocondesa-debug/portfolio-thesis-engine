import { describe, expect, it, vi, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { TraceabilityProvider } from "@/lib/traceability/context";
import { SourcePanel } from "@/components/traceability/source-panel";
import { TraceableValue } from "@/components/traceability/traceable-value";
import type { CanonicalState } from "@/lib/types/canonical";
import { adjustmentsFixture, canonicalFixture } from "@/tests/fixtures";

// Sprint QA — verifies the browser back-button integration introduced in
// Part D of TraceabilityProvider. jsdom's history.back() does NOT fire a
// popstate synchronously, so most assertions inspect spy calls instead.

describe("TraceabilityProvider browser navigation (Sprint QA)", () => {
  const canonical = {
    ...canonicalFixture,
    adjustments: adjustmentsFixture as unknown as CanonicalState["adjustments"],
  };

  afterEach(() => {
    vi.restoreAllMocks();
    // Reset any traceabilityPanel state pushed during the test.
    if (window.history.state?.traceabilityPanel) {
      window.history.replaceState(null, "");
    }
  });

  it("pushes a history state when the panel opens", () => {
    const pushSpy = vi.spyOn(window.history, "pushState");

    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Op income",
            value: "100",
            format: "currency",
          }}
        >
          100
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("100"));

    expect(pushSpy).toHaveBeenCalledWith(
      expect.objectContaining({ traceabilityPanel: true }),
      "",
    );
  });

  it("does not double-push when re-opening with another value", () => {
    const pushSpy = vi.spyOn(window.history, "pushState");

    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Op income",
            value: "100",
            format: "currency",
          }}
        >
          100
        </TraceableValue>
        <TraceableValue
          source={{
            root: "canonical",
            field: "roic",
            period: "FY2024",
            label: "ROIC",
            value: "8.20",
            format: "percent_direct",
          }}
        >
          200
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("100"));
    fireEvent.click(screen.getByText("200"));

    // Only one pushState call should land for the panel; the second open
    // re-uses the existing history entry.
    const panelPushes = pushSpy.mock.calls.filter(
      (args) =>
        typeof args[0] === "object" &&
        args[0] !== null &&
        (args[0] as Record<string, unknown>).traceabilityPanel === true,
    );
    expect(panelPushes).toHaveLength(1);
  });

  it("closes the panel when popstate fires (browser back button)", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Op income",
            value: "100",
            format: "currency",
          }}
        >
          100
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("100"));
    expect(screen.getByText("Op income")).toBeInTheDocument();

    // Simulate the browser back button. Wrapping in act() lets React
    // flush the state update before we assert on the rendered class.
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    // Panel state flips to closed; the slide-out animation keeps the
    // selectedSource for 300ms but the dialog has translate-x-full now.
    const dialog = screen.queryByRole("dialog");
    expect(dialog?.className).toMatch(/translate-x-full/);
  });
});
