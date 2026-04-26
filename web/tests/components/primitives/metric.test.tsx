import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Metric } from "@/components/primitives/metric";

describe("Metric (Sprint QA)", () => {
  it("renders label + value + subtitle", () => {
    render(<Metric label="Headline" value="HK$7.80" subtitle="per share" />);
    expect(screen.getByText("Headline")).toBeInTheDocument();
    expect(screen.getByText("HK$7.80")).toBeInTheDocument();
    expect(screen.getByText("per share")).toBeInTheDocument();
  });

  it("applies highlight class for primary metric", () => {
    const { container } = render(
      <Metric label="E[V]" value="HK$7.80" highlight />,
    );
    const valueDiv = container.querySelector(".text-2xl");
    expect(valueDiv).toBeTruthy();
  });

  it("uses positive tone class", () => {
    const { container } = render(
      <Metric label="Upside" value="194%" tone="positive" />,
    );
    expect(container.querySelector(".text-positive")).toBeTruthy();
  });

  it("uses negative tone class", () => {
    const { container } = render(
      <Metric label="Drawdown" value="-50%" tone="negative" />,
    );
    expect(container.querySelector(".text-negative")).toBeTruthy();
  });

  it("accepts ReactNode value (for traceable wrapping)", () => {
    render(
      <Metric
        label="ROIC"
        value={<span data-testid="traceable">8.20%</span>}
      />,
    );
    expect(screen.getByTestId("traceable")).toBeInTheDocument();
  });
});
