import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EconomicBalanceSheet } from "@/components/sections/economic-balance-sheet";
import { canonicalFixture } from "@/tests/fixtures";

describe("EconomicBalanceSheet", () => {
  it("renders both operating and financing panels", () => {
    render(<EconomicBalanceSheet canonical={canonicalFixture} />);
    expect(screen.getByText("Operating side")).toBeInTheDocument();
    expect(screen.getByText("Financing side")).toBeInTheDocument();
  });

  it("renders the invested-capital total", () => {
    render(<EconomicBalanceSheet canonical={canonicalFixture} />);
    expect(screen.getByText("Invested capital")).toBeInTheDocument();
  });

  it("renders the period footer", () => {
    render(<EconomicBalanceSheet canonical={canonicalFixture} />);
    expect(screen.getByText(/Period FY2024/)).toBeInTheDocument();
  });
});
