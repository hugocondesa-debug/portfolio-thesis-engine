import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalyticalLayer } from "@/components/sections/analytical-layer";
import { canonicalFixture } from "@/tests/fixtures";

describe("AnalyticalLayer", () => {
  it("renders the ratio matrix headers", () => {
    render(<AnalyticalLayer canonical={canonicalFixture} />);
    expect(screen.getByText("Operating margin (reported)")).toBeInTheDocument();
    expect(screen.getByText("ROIC (sustainable)")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
  });

  it("renders period column", () => {
    render(<AnalyticalLayer canonical={canonicalFixture} />);
    expect(screen.getByText("FY2024")).toBeInTheDocument();
  });

  // Sprint 1B.1 — the 100x bug regression suite. Ratios in canonical analysis
  // are stored as percent strings; the prior code piped them through
  // ``formatPercent`` (a fraction formatter), inflating operating margin to
  // 1,617.74%. These tests pin the corrected output.
  describe("100x bug fix verification", () => {
    it("renders operating margin (reported) as 16.18%, NOT 1617.74%", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText(/16\.18%/)).toBeInTheDocument();
      expect(screen.queryByText(/1617/)).not.toBeInTheDocument();
    });

    it("renders ROIC (sustainable) as 8.20%", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      // "8.20%" appears in the ratio cell AND in the footer explainer
      // ("e.g. ROIC \"8.20\" = 8.20%") — accept both.
      expect(screen.getAllByText(/8\.20%/).length).toBeGreaterThanOrEqual(1);
    });

    it("renders ROE as 7.72%", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText(/7\.72%/)).toBeInTheDocument();
    });

    it("renders EBITDA margin as 31.86%", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText(/31\.86%/)).toBeInTheDocument();
    });

    it("renders net debt / EBITDA as a multiple (-1.47×), not a percent", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText(/-1\.47×/)).toBeInTheDocument();
    });

    it("renders sustainable operating margin as 12.92%", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText(/12\.92%/)).toBeInTheDocument();
    });
  });

  describe("category grouping", () => {
    it("groups ratios into Profitability, Returns, Leverage, Working capital cycle", () => {
      render(<AnalyticalLayer canonical={canonicalFixture} />);
      expect(screen.getByText("Profitability")).toBeInTheDocument();
      expect(screen.getByText("Returns on capital")).toBeInTheDocument();
      expect(screen.getByText("Leverage")).toBeInTheDocument();
      expect(screen.getByText("Working capital cycle")).toBeInTheDocument();
    });
  });
});
