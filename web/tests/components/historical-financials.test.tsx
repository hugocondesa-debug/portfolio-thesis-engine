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
});
