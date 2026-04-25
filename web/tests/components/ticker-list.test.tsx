import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TickerList } from "@/components/tickers/ticker-list";
import { tickerSummaryFixture } from "@/tests/fixtures";

const others = [
  {
    ...tickerSummaryFixture,
    ticker: "AAPL",
    name: "Apple Inc.",
    profile: "P5",
    currency: "USD",
    exchange: "NASDAQ",
    has_valuation: false,
  },
];

describe("TickerList", () => {
  it("renders all tickers", () => {
    render(<TickerList tickers={[tickerSummaryFixture, ...others]} />);
    expect(screen.getByText("1846.HK")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("filters by search", () => {
    render(<TickerList tickers={[tickerSummaryFixture, ...others]} />);
    const search = screen.getByPlaceholderText(/Search ticker or name/);
    fireEvent.change(search, { target: { value: "Apple" } });
    expect(screen.queryByText("1846.HK")).not.toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("filters by profile", () => {
    render(<TickerList tickers={[tickerSummaryFixture, ...others]} />);
    const profileSelect = screen.getByDisplayValue("All profiles");
    fireEvent.change(profileSelect, { target: { value: "P1" } });
    expect(screen.getByText("1846.HK")).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });

  it("filters by has_valuation", () => {
    render(<TickerList tickers={[tickerSummaryFixture, ...others]} />);
    const checkbox = screen.getByLabelText(/Only with valuation/);
    fireEvent.click(checkbox);
    expect(screen.getByText("1846.HK")).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });
});
