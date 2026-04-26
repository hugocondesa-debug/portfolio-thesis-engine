import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CapitalAllocationSection } from "@/components/sections/capital-allocation";
import {
  canonicalFixture,
  capitalAllocationFixture,
  forecastFixture,
} from "@/tests/fixtures";

describe("CapitalAllocationSection (Sprint 1B.2)", () => {
  it("renders empty state when capitalAllocation is null", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={null}
        forecast={null}
        canonical={canonicalFixture}
      />,
    );
    expect(
      screen.getByText(/No capital_allocation\.yaml available/),
    ).toBeInTheDocument();
  });

  it("renders all 5 policy cards", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("Dividend")).toBeInTheDocument();
    expect(screen.getByText("Buyback")).toBeInTheDocument();
    expect(screen.getByText("Debt")).toBeInTheDocument();
    // "M&A" appears as both the policy card title and the deployment chart row.
    expect(screen.getAllByText("M&A").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Share issuance")).toBeInTheDocument();
  });

  it("renders confidence badges (HIGH/MEDIUM)", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    // 3 MEDIUM badges (Dividend, Buyback, M&A) and 2 HIGH (Debt, Share issuance)
    expect(
      screen.getAllByText("MEDIUM").length,
    ).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("HIGH").length).toBeGreaterThanOrEqual(2);
  });

  it("renders policy types", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("PAYOUT_RATIO")).toBeInTheDocument();
    expect(screen.getByText("CONDITIONAL")).toBeInTheDocument();
    expect(screen.getByText("MAINTAIN_ZERO")).toBeInTheDocument();
    expect(screen.getByText("OPPORTUNISTIC")).toBeInTheDocument();
    // Share issuance type is "ZERO" — ensure text exists
    expect(screen.getByText("ZERO")).toBeInTheDocument();
  });

  it("renders historical context (dividends, buybacks, cash evolution)", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("Recent dividends")).toBeInTheDocument();
    expect(screen.getByText("Recent buybacks")).toBeInTheDocument();
    expect(screen.getByText("Cash evolution")).toBeInTheDocument();
    // Buyback program name from fixture
    expect(
      screen.getByText("January 2025 Mandate Execution"),
    ).toBeInTheDocument();
  });

  it("renders 5-year deployment forecast section when forecast supplied", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(
      screen.getByText("5-year deployment forecast (base scenario)"),
    ).toBeInTheDocument();
  });

  it("renders evidence trail summary with disclosure count", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    // Fixture has 2 evidence sources
    expect(
      screen.getByText(/Evidence trail — 2 disclosures/),
    ).toBeInTheDocument();
  });

  it("renders evidence trail content (always present in DOM regardless of <details> open state)", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    // <details> children are present in the DOM even when collapsed; jsdom
    // doesn't enforce the visibility toggle.
    expect(
      screen.getByText(/FY2024 final dividend/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/5\.21M shares repurchased/),
    ).toBeInTheDocument();
  });

  it("filters evidence by category", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    // Click DIVIDEND filter button — only DIVIDEND disclosures should remain.
    fireEvent.click(screen.getByText(/^DIVIDEND \(1\)/));
    expect(screen.getByText(/FY2024 final dividend/)).toBeInTheDocument();
    expect(
      screen.queryByText(/5\.21M shares repurchased/),
    ).not.toBeInTheDocument();
  });

  it("renders source documents list", () => {
    render(
      <CapitalAllocationSection
        capitalAllocation={capitalAllocationFixture}
        forecast={forecastFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("Source documents")).toBeInTheDocument();
    expect(screen.getByText("AR 2024 audited")).toBeInTheDocument();
  });
});
