import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataField } from "@/components/primitives/data-field";

describe("DataField (Sprint QA)", () => {
  it("renders label + value", () => {
    render(<DataField label="Currency" value="HKD" />);
    expect(screen.getByText("Currency")).toBeInTheDocument();
    expect(screen.getByText("HKD")).toBeInTheDocument();
  });

  it("uses mono font when mono=true", () => {
    const { container } = render(
      <DataField label="Snapshot" value="abc-123" mono />,
    );
    expect(container.querySelector(".font-mono")).toBeTruthy();
  });

  it("does not use mono font when mono=false (default)", () => {
    const { container } = render(<DataField label="Status" value="OK" />);
    expect(container.querySelector(".font-mono")).toBeNull();
  });
});
