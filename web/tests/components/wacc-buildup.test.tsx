import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WaccBuildup } from "@/components/sections/wacc-buildup";
import { canonicalFixture, valuationFixture } from "@/tests/fixtures";

describe("WaccBuildup", () => {
  it("renders cost of equity and WACC", () => {
    render(
      <WaccBuildup valuation={valuationFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText("Cost of equity")).toBeInTheDocument();
    expect(screen.getByText("WACC")).toBeInTheDocument();
    // Both values come from market.cost_of_equity / wacc → 8.12%
    expect(screen.getAllByText(/8\.12%/).length).toBeGreaterThan(0);
  });

  it("links the analyst to pte analyze for the geographic mix", () => {
    render(
      <WaccBuildup valuation={valuationFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText(/pte analyze/)).toBeInTheDocument();
  });
});
