import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LeadingIndicators } from "@/components/sections/leading-indicators";
import {
  canonicalFixture,
  sensitivitiesFixture,
  valuationFixture,
} from "@/tests/fixtures";

describe("LeadingIndicators (Sprint 1C)", () => {
  it("renders empty state when sensitivities are absent", () => {
    render(
      <LeadingIndicators
        valuation={{ ...valuationFixture, sensitivities: [] }}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/No sensitivity grids/)).toBeInTheDocument();
  });

  it("renders heatmap with axis labels (snake_case → Title Case)", () => {
    const valuation = {
      ...valuationFixture,
      sensitivities: sensitivitiesFixture,
    };
    render(
      <LeadingIndicators valuation={valuation} canonical={canonicalFixture} />,
    );
    // axis_x = "wacc" → "Wacc"; axis_y = "terminal_growth" → "Terminal Growth"
    expect(screen.getAllByText(/Wacc/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Terminal Growth/).length).toBeGreaterThanOrEqual(
      1,
    );
  });

  it("formats wacc x-axis ticks as percentages", () => {
    const valuation = {
      ...valuationFixture,
      sensitivities: sensitivitiesFixture,
    };
    render(
      <LeadingIndicators valuation={valuation} canonical={canonicalFixture} />,
    );
    expect(screen.getAllByText(/7\.62%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/8\.12%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/8\.62%/).length).toBeGreaterThanOrEqual(1);
  });

  it("formats terminal_growth y-axis ticks as percentages", () => {
    const valuation = {
      ...valuationFixture,
      sensitivities: sensitivitiesFixture,
    };
    render(
      <LeadingIndicators valuation={valuation} canonical={canonicalFixture} />,
    );
    expect(screen.getAllByText(/2\.25%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/2\.75%/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders scenario tabs (one per grid)", () => {
    const valuation = {
      ...valuationFixture,
      sensitivities: sensitivitiesFixture,
    };
    render(
      <LeadingIndicators valuation={valuation} canonical={canonicalFixture} />,
    );
    // Mobile dropdown has both labels as <option>; desktop tabs render
    // them as <button>. Either way both labels appear in the DOM.
    expect(screen.getAllByText(/^base/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^bull/).length).toBeGreaterThanOrEqual(1);
  });
});
