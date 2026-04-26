import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AuditProvenance } from "@/components/sections/audit-provenance";
import {
  adjustmentsFixture,
  canonicalFixture,
  valuationFixture,
} from "@/tests/fixtures";

describe("AuditProvenance (Sprint 1C)", () => {
  const canonicalWithAdjustments = {
    ...canonicalFixture,
    adjustments: adjustmentsFixture,
  };

  it("renders the pipeline trace summary with extraction id", () => {
    render(
      <AuditProvenance
        canonical={canonicalWithAdjustments}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText(/Extraction ID/)).toBeInTheDocument();
    // canonicalFixture extraction id
    expect(
      screen.getByText("1846-HK_FY2024_20260425161804"),
    ).toBeInTheDocument();
  });

  it("renders all 11 module categories", () => {
    render(
      <AuditProvenance
        canonical={canonicalWithAdjustments}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText(/Module A — Taxes/)).toBeInTheDocument();
    expect(screen.getByText(/Module B — Provisions/)).toBeInTheDocument();
    expect(screen.getByText(/Module C — Leases/)).toBeInTheDocument();
    expect(
      screen.getByText(/Module E — Stock-based compensation/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Manual patches/)).toBeInTheDocument();
    expect(screen.getByText(/Decision log/)).toBeInTheDocument();
    expect(screen.getByText(/Estimates log/)).toBeInTheDocument();
  });

  it("expands Module A on click and shows the adjustment", () => {
    render(
      <AuditProvenance
        canonical={canonicalWithAdjustments}
        valuation={valuationFixture}
      />,
    );
    fireEvent.click(screen.getByText(/Module A — Taxes/));
    expect(screen.getByText("A.1")).toBeInTheDocument();
    expect(screen.getByText("Operating tax rate")).toBeInTheDocument();
  });

  it("renders REPORTED confidence badge in expanded module", () => {
    render(
      <AuditProvenance
        canonical={canonicalWithAdjustments}
        valuation={valuationFixture}
      />,
    );
    fireEvent.click(screen.getByText(/Module A — Taxes/));
    expect(screen.getAllByText("REPORTED").length).toBeGreaterThanOrEqual(1);
  });

  it("includes Sprint 0.2 backend note for runs endpoint", () => {
    render(
      <AuditProvenance
        canonical={canonicalWithAdjustments}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText(/Sprint 0\.2 backend exposes/)).toBeInTheDocument();
  });
});
