import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { HistoricalFinancials } from "@/components/sections/historical-financials";
import { canonicalFixture } from "@/tests/fixtures";

describe("HistoricalFinancials", () => {
  it("renders income statement by default with both periods as columns", () => {
    render(<HistoricalFinancials canonical={canonicalFixture} />);
    expect(screen.getByText("FY2023")).toBeInTheDocument();
    expect(screen.getByText("FY2024")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText(/715/)).toBeInTheDocument();
  });

  it("switches to balance sheet tab", () => {
    render(<HistoricalFinancials canonical={canonicalFixture} />);
    fireEvent.click(screen.getByRole("button", { name: /Balance Sheet/i }));
    expect(screen.getByText("Property, plant and equipment")).toBeInTheDocument();
  });

  it("switches to cash flow tab", () => {
    render(<HistoricalFinancials canonical={canonicalFixture} />);
    fireEvent.click(screen.getByRole("button", { name: /Cash Flow/i }));
    expect(
      screen.getByText("Net cash from operating activities"),
    ).toBeInTheDocument();
  });

  it("filters to adjusted-only when toggled", () => {
    render(<HistoricalFinancials canonical={canonicalFixture} />);
    const checkbox = screen.getByLabelText(/Adjusted lines only/i);
    fireEvent.click(checkbox);
    // Operating profit FY2023 is the only adjusted line in the fixture.
    expect(screen.getByText("Operating profit")).toBeInTheDocument();
    expect(screen.queryByText("Revenue")).not.toBeInTheDocument();
  });

  // Sprint 1B.1 — list-of-items refactor: checksum badges, BS/CF category
  // grouping, YoY column, adjustment markers.
  describe("Sprint 1B.1 list-of-items refactor", () => {
    it("renders per-period checksum status badges", () => {
      render(<HistoricalFinancials canonical={canonicalFixture} />);
      // Both periods pass IS checksum in the fixture.
      const passBadges = screen.getAllByText(/checksum PASS/);
      expect(passBadges.length).toBeGreaterThanOrEqual(2);
    });

    it("groups balance sheet items by category", () => {
      render(<HistoricalFinancials canonical={canonicalFixture} />);
      fireEvent.click(screen.getByRole("button", { name: /Balance Sheet/i }));
      expect(screen.getByText("non_current_assets")).toBeInTheDocument();
      expect(screen.getByText("current_assets")).toBeInTheDocument();
    });

    it("groups cash flow items by category", () => {
      render(<HistoricalFinancials canonical={canonicalFixture} />);
      fireEvent.click(screen.getByRole("button", { name: /Cash Flow/i }));
      expect(screen.getByText("operating")).toBeInTheDocument();
    });

    it("renders YoY % column when 2+ periods present", () => {
      render(<HistoricalFinancials canonical={canonicalFixture} />);
      // Column header is "YoY %"
      expect(screen.getByText("YoY %")).toBeInTheDocument();
    });

    it("flags adjusted lines with an `adj` marker", () => {
      render(<HistoricalFinancials canonical={canonicalFixture} />);
      // FY2023 Operating profit is adjusted in the fixture; the marker
      // should render alongside the row.
      expect(screen.getByText("adj")).toBeInTheDocument();
    });
  });
});
