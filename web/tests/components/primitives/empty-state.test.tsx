import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/primitives/empty-state";

describe("EmptyState (Sprint QA)", () => {
  it("renders title + message", () => {
    render(<EmptyState title="No Data" message="Run pipeline first." />);
    expect(screen.getByText("No Data")).toBeInTheDocument();
    expect(screen.getByText("Run pipeline first.")).toBeInTheDocument();
  });

  it("renders the optional action slot when provided", () => {
    render(
      <EmptyState
        title="No Data"
        message="Run pipeline."
        action={<code data-testid="cmd">pte process X</code>}
      />,
    );
    expect(screen.getByTestId("cmd")).toBeInTheDocument();
  });

  it("uses dashed border styling", () => {
    const { container } = render(
      <EmptyState title="Empty" message="Nothing yet." />,
    );
    expect(container.querySelector(".border-dashed")).toBeTruthy();
  });
});
