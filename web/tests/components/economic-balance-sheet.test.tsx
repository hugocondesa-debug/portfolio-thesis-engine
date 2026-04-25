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

  it("surfaces the cross-check residual identity message", () => {
    render(<EconomicBalanceSheet canonical={canonicalFixture} />);
    expect(
      screen.getByText(/Identity holds when residual ≈ 0/),
    ).toBeInTheDocument();
  });

  it("renders net debt with negative-cash framing", () => {
    render(<EconomicBalanceSheet canonical={canonicalFixture} />);
    expect(screen.getByText(/Net debt/)).toBeInTheDocument();
  });

  // Sprint 1B.1 — NOPAT bridge with non-recurring items detail.
  describe("Sprint 1B.1 NOPAT bridge", () => {
    it("renders the NOPAT bridge header for the latest period", () => {
      render(<EconomicBalanceSheet canonical={canonicalFixture} />);
      expect(
        screen.getByText(/NOPAT bridge — FY2024/),
      ).toBeInTheDocument();
    });

    it("renders the EBITDA → EBITA → OI → OI sustainable bridge metrics", () => {
      render(<EconomicBalanceSheet canonical={canonicalFixture} />);
      expect(screen.getByText("EBITDA")).toBeInTheDocument();
      expect(screen.getByText("EBITA")).toBeInTheDocument();
      expect(screen.getByText("Operating income")).toBeInTheDocument();
      expect(screen.getByText("OI sustainable")).toBeInTheDocument();
    });

    it("renders the non-recurring items collapsible summary", () => {
      render(<EconomicBalanceSheet canonical={canonicalFixture} />);
      expect(
        screen.getByText(/Non-recurring items adjusted out/),
      ).toBeInTheDocument();
    });
  });
});
