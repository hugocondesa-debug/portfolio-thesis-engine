import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CostStructure } from "@/components/sections/cost-structure";
import { canonicalFixture } from "@/tests/fixtures";

describe("CostStructure", () => {
  it("renders the margin trajectory headers", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    expect(
      screen.getByText("Operating margin (reported)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Operating margin (sustainable)"),
    ).toBeInTheDocument();
    expect(screen.getByText("EBITDA margin")).toBeInTheDocument();
  });

  it("renders the period column for the trajectory", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    // FY2024 may appear in multiple places (column header, IS heading).
    expect(screen.getAllByText("FY2024").length).toBeGreaterThanOrEqual(1);
  });

  it("renders margin values from canonical ratios as percent-direct", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    // ratios_by_period[0].operating_margin = "16.18" → "16.18%"
    expect(screen.getByText(/16\.18%/)).toBeInTheDocument();
    // ratios_by_period[0].ebitda_margin = "31.86" → "31.86%"
    expect(screen.getByText(/31\.86%/)).toBeInTheDocument();
  });

  it("renders the IS composition table with line item labels", () => {
    render(<CostStructure canonical={canonicalFixture} />);
    expect(
      screen.getByText("Income statement composition — FY2024"),
    ).toBeInTheDocument();
    // IS items present in the fixture's FY2024 statement.
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Operating profit")).toBeInTheDocument();
  });
});
