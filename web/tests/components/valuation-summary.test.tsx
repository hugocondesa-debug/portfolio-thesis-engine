import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ValuationSummary } from "@/components/sections/valuation-summary";
import { canonicalFixture, valuationFixture } from "@/tests/fixtures";

describe("ValuationSummary", () => {
  it("renders the headline expected value", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("E[V] per share")).toBeInTheDocument();
    expect(screen.getByText(/8\.63/)).toBeInTheDocument();
  });

  it("renders the P25-P75 range", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/5\.50/)).toBeInTheDocument();
    expect(screen.getByText(/10\.20/)).toBeInTheDocument();
  });

  it("renders all scenario rows", () => {
    render(
      <ValuationSummary
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("base")).toBeInTheDocument();
    expect(screen.getByText("bull_operational")).toBeInTheDocument();
  });
});
