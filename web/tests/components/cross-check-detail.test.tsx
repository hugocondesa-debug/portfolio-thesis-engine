import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CrossCheckDetail } from "@/components/sections/cross-check-detail";
import {
  canonicalFixture,
  crossCheckFixture,
  valuationFixture,
} from "@/tests/fixtures";

describe("CrossCheckDetail (Sprint 1C)", () => {
  it("renders empty state when crossCheck is null", () => {
    render(
      <CrossCheckDetail
        crossCheck={null}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(
      screen.getByText(/No cross-check log available/),
    ).toBeInTheDocument();
  });

  it("renders metrics table with PASS/WARN status pills", () => {
    render(
      <CrossCheckDetail
        crossCheck={crossCheckFixture}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("revenue")).toBeInTheDocument();
    expect(screen.getByText("operating_income")).toBeInTheDocument();
    expect(screen.getAllByText("PASS").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("WARN").length).toBeGreaterThanOrEqual(1);
  });

  it("shows correct count of PASS / WARN in summary", () => {
    render(
      <CrossCheckDetail
        crossCheck={crossCheckFixture}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // Fixture has 2 PASS + 1 WARN
    expect(screen.getByText(/PASS: 2/)).toBeInTheDocument();
    expect(screen.getByText(/WARN: 1/)).toBeInTheDocument();
  });

  it("formats max_delta_pct as percentage (fraction → percent)", () => {
    render(
      <CrossCheckDetail
        crossCheck={crossCheckFixture}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    // 0.1033... → 10.34%
    expect(screen.getByText(/10\.34%/)).toBeInTheDocument();
  });

  it("displays Phase 1 stub guardrails note", () => {
    render(
      <CrossCheckDetail
        crossCheck={crossCheckFixture}
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/Phase 1 stub/)).toBeInTheDocument();
  });
});
