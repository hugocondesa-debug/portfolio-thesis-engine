import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WaccBuildup } from "@/components/sections/wacc-buildup";
import { canonicalFixture, valuationFixture } from "@/tests/fixtures";

describe("WaccBuildup", () => {
  it("renders cost of equity and WACC headlines from market block", () => {
    render(
      <WaccBuildup valuation={valuationFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText("Cost of equity")).toBeInTheDocument();
    expect(screen.getByText("WACC")).toBeInTheDocument();
    // valuation.market.{cost_of_equity, wacc} = "8.12" → divided by 100 → 8.12%
    expect(screen.getAllByText(/8\.12%/).length).toBeGreaterThanOrEqual(2);
  });

  it("renders the reporting currency", () => {
    render(
      <WaccBuildup valuation={valuationFixture} canonical={canonicalFixture} />,
    );
    // valuation.market.currency = "HKD" — appears as the third metric.
    expect(screen.getAllByText("HKD").length).toBeGreaterThan(0);
  });

  it("explains that geographic mix is deferred to Sprint 4B.1", () => {
    render(
      <WaccBuildup valuation={valuationFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText(/Sprint 4B\.1/)).toBeInTheDocument();
    expect(
      screen.getByText(/Geographic mix when company operates/i),
    ).toBeInTheDocument();
  });
});
