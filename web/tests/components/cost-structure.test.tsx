import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CostStructure } from "@/components/sections/cost-structure";
import { canonicalFixture } from "@/tests/fixtures";

describe("CostStructure", () => {
  it("renders the latest gross / operating / net margin headlines", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    // Headline metric labels include the period; row labels are bare.
    expect(screen.getByText(/Gross margin \(FY2024\)/)).toBeInTheDocument();
    expect(screen.getByText(/Operating margin \(FY2024\)/)).toBeInTheDocument();
    expect(screen.getByText(/Net margin \(FY2024\)/)).toBeInTheDocument();
  });

  it("renders both periods in the trajectory table", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    expect(screen.getByText("FY2023")).toBeInTheDocument();
    expect(screen.getByText("FY2024")).toBeInTheDocument();
  });
});
