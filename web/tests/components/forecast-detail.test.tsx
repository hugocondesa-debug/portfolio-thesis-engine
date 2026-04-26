import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ForecastDetail } from "@/components/sections/forecast-detail";
import {
  canonicalFixture,
  forecastFixture,
  valuationFixture,
} from "@/tests/fixtures";

describe("ForecastDetail (Sprint 1B.2)", () => {
  it("renders empty state when forecast is null", () => {
    render(
      <ForecastDetail
        forecast={null}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/No forecast snapshot/)).toBeInTheDocument();
  });

  it("renders the section header with scenario count", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    expect(
      screen.getByText("Three-Statement Forecast Detail"),
    ).toBeInTheDocument();
    // 1 scenario in fixture · 5-year horizon · base year FY2024
    expect(screen.getByText(/1 scenarios.*FY2024/)).toBeInTheDocument();
  });

  it("renders scenario tab and IS table by default", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    // base label appears in mobile dropdown <option> AND desktop tab button.
    expect(screen.getAllByText(/^base/).length).toBeGreaterThanOrEqual(1);
    // IS table groups
    expect(screen.getByText("Revenue & Profitability")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
  });

  it("converts revenue_growth_rate fraction (0.10) to percent display (10.00%)", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("10.00%")).toBeInTheDocument();
  });

  it("converts operating_margin fraction (0.1756) to percent display (17.56%)", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("17.56%")).toBeInTheDocument();
  });

  it("renders the solver convergence badge", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/Converged/)).toBeInTheDocument();
  });

  it("switches to Balance Sheet sub-tab", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    fireEvent.click(screen.getByText("Balance Sheet"));
    expect(screen.getByText("Total assets")).toBeInTheDocument();
    expect(screen.getByText("Capital structure")).toBeInTheDocument();
  });

  it("switches to Cash Flow sub-tab and shows capital deployment fields", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    fireEvent.click(screen.getByText("Cash Flow"));
    expect(screen.getByText("Capex")).toBeInTheDocument();
    expect(screen.getByText("M&A deployment")).toBeInTheDocument();
    expect(screen.getByText("Dividends paid")).toBeInTheDocument();
    expect(screen.getByText("Buybacks executed")).toBeInTheDocument();
  });

  it("switches to Forward Ratios sub-tab and shows ROIC as percent", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={null}
        canonical={canonicalFixture}
      />,
    );
    fireEvent.click(screen.getByText("Forward Ratios"));
    expect(screen.getByText("ROIC")).toBeInTheDocument();
    // 0.1224 → 12.24%
    expect(screen.getByText("12.24%")).toBeInTheDocument();
  });

  it("renders probability-weighted forward metrics section", () => {
    render(
      <ForecastDetail
        forecast={forecastFixture}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(
      screen.getByText("Probability-weighted forward metrics"),
    ).toBeInTheDocument();
    expect(screen.getByText("Forward EPS Y1")).toBeInTheDocument();
    expect(screen.getByText("Forward PER Y1")).toBeInTheDocument();
  });
});
