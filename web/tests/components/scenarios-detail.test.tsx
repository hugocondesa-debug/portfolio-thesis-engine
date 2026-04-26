import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ScenariosDetail } from "@/components/sections/scenarios-detail";
import { canonicalFixture, valuationFixture } from "@/tests/fixtures";

describe("ScenariosDetail (Sprint 1B.2)", () => {
  it("renders empty state when valuation is null", () => {
    render(
      <ScenariosDetail valuation={null} canonical={canonicalFixture} />,
    );
    expect(
      screen.getByText(/No scenarios in valuation snapshot/),
    ).toBeInTheDocument();
  });

  it("renders all 3 scenario cards", () => {
    render(
      <ScenariosDetail
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText("base")).toBeInTheDocument();
    expect(screen.getByText("bear")).toBeInTheDocument();
    expect(screen.getByText("bull")).toBeInTheDocument();
  });

  it("expands a scenario card on click and shows drivers + IRR breakdown", () => {
    render(
      <ScenariosDetail
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    fireEvent.click(screen.getByText("base"));
    expect(screen.getByText("Drivers")).toBeInTheDocument();
    expect(screen.getByText("Targets")).toBeInTheDocument();
    expect(screen.getByText(/IRR \(3y\) decomposition/)).toBeInTheDocument();
    // Decomposition components rendered
    expect(screen.getByText("Fundamental")).toBeInTheDocument();
    expect(screen.getByText("Re-rating")).toBeInTheDocument();
    expect(screen.getByText("Dividend")).toBeInTheDocument();
  });

  it("renders survival/kill signals when populated (none in fixture → not rendered)", () => {
    render(
      <ScenariosDetail
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    fireEvent.click(screen.getByText("base"));
    // Fixture scenarios have empty survival/kill arrays — these headings stay
    // hidden.
    expect(
      screen.queryByText(/Survival conditions/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Kill signals/i)).not.toBeInTheDocument();
  });

  it("includes the methodology in the subtitle", () => {
    render(
      <ScenariosDetail
        valuation={valuationFixture}
        canonical={canonicalFixture}
      />,
    );
    expect(screen.getByText(/methodology DCF_FCFF/)).toBeInTheDocument();
  });
});
