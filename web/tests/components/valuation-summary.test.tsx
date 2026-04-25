import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ValuationSummary } from "@/components/sections/valuation-summary";
import { canonicalFixture, valuationFixture } from "@/tests/fixtures";

describe("ValuationSummary", () => {
  it("renders the headline expected value from weighted block", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("E[V] per share")).toBeInTheDocument();
    // HK$7.80 appears twice: headline E[V] metric AND base scenario row.
    expect(screen.getAllByText(/HK\$7\.80/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the P25-P75 range from weighted", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // fair_value_range_low/high formatted on the same metric cell.
    expect(screen.getByText(/HK\$4\.76 — HK\$11\.31/)).toBeInTheDocument();
  });

  it("renders all 3 scenario rows by label", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("bear")).toBeInTheDocument();
    expect(screen.getByText("base")).toBeInTheDocument();
    expect(screen.getByText("bull")).toBeInTheDocument();
  });

  it("renders the probability-weighted upside in percent units", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // weighted.upside_pct = "194.15" → 194.15%
    expect(screen.getByText(/194\.15%/)).toBeInTheDocument();
  });

  it("renders per-scenario fair values from targets.dcf_fcff_per_share", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // bear 4.76 appears in the range cell AND the scenario row → 2x.
    // bull 11.31 same. base 7.80 also duplicates.
    expect(screen.getAllByText(/HK\$4\.76/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/HK\$11\.31/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders per-scenario IRR (3y) in percent units", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // bear 17.68%, base 27.22%, bull 62.45%
    expect(screen.getByText(/17\.68%/)).toBeInTheDocument();
    expect(screen.getByText(/27\.22%/)).toBeInTheDocument();
    expect(screen.getByText(/62\.45%/)).toBeInTheDocument();
  });

  it("includes the methodology in the subtitle", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/method DCF_FCFF/)).toBeInTheDocument();
  });
});
