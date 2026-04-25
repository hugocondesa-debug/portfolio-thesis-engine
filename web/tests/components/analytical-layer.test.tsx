import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalyticalLayer } from "@/components/sections/analytical-layer";
import { canonicalFixture } from "@/tests/fixtures";

describe("AnalyticalLayer", () => {
  it("renders the ratio matrix headers", () => {
    render(<AnalyticalLayer canonical={canonicalFixture} />);
    expect(screen.getByText("Operating margin")).toBeInTheDocument();
    expect(screen.getByText("ROIC (sustainable)")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
  });

  it("renders period column", () => {
    render(<AnalyticalLayer canonical={canonicalFixture} />);
    expect(screen.getByText("FY2024")).toBeInTheDocument();
  });
});
