import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TraceabilityProvider } from "@/lib/traceability/context";
import { SourcePanel } from "@/components/traceability/source-panel";
import { TraceableValue } from "@/components/traceability/traceable-value";
import type { CanonicalState } from "@/lib/types/canonical";
import { adjustmentsFixture, canonicalFixture } from "@/tests/fixtures";

describe("SourcePanel + TraceableValue (Sprint 1C)", () => {
  // Cast through unknown — ``AdjustmentsByModule.module_d_note_decompositions``
  // is intentionally widened to ``Record<string, unknown>`` (the on-the-wire
  // dict shape), whereas ``CanonicalState`` keeps the stricter
  // ``Record<string, LineDecomposition>`` from the Sprint 1A type. The
  // fixture's empty object ``{}`` is value-compatible with both.
  const canonical = {
    ...canonicalFixture,
    adjustments: adjustmentsFixture as unknown as CanonicalState["adjustments"],
  };

  it("opens the panel when a TraceableValue is clicked", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Test Value",
            value: "1000",
            format: "currency",
          }}
        >
          1,000
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("1,000"));
    expect(screen.getByText("Test Value")).toBeInTheDocument();
  });

  it("renders the adjustment chain with module entries", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Operating income",
            value: "115779000",
            format: "currency",
          }}
        >
          115.78M
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("115.78M"));
    expect(screen.getByText(/Adjustment chain/)).toBeInTheDocument();
    expect(screen.getByText("A.1")).toBeInTheDocument();
  });

  it("shows formula when known", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
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
          8.20%
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("8.20%"));
    expect(screen.getByText("Formula")).toBeInTheDocument();
    expect(screen.getByText(/ROIC = NOPAT/)).toBeInTheDocument();
  });

  it("shows DERIVED confidence when adjustments are all REPORTED", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Operating income",
            value: "115779000",
            format: "currency",
          }}
        >
          115.78M
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("115.78M"));
    expect(screen.getByText("DERIVED")).toBeInTheDocument();
  });

  it("renders cross-statement navigation links for operating_income", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "operating_income",
            period: "FY2024",
            label: "Operating income",
            value: "115779000",
            format: "currency",
          }}
        >
          115.78M
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("115.78M"));
    expect(screen.getByText(/Navigate to/)).toBeInTheDocument();
    expect(screen.getByText("Operating profit")).toBeInTheDocument();
  });

  it("renders an empty state for the chain when no adjustments map", () => {
    render(
      <TraceabilityProvider canonical={canonical}>
        <TraceableValue
          source={{
            root: "canonical",
            field: "revenue",
            period: "FY2024",
            label: "Revenue",
            value: "715682000",
            format: "currency",
          }}
        >
          715.68M
        </TraceableValue>
        <SourcePanel />
      </TraceabilityProvider>,
    );

    fireEvent.click(screen.getByText("715.68M"));
    expect(
      screen.getByText(/No Module D adjustments touched/),
    ).toBeInTheDocument();
  });
});
