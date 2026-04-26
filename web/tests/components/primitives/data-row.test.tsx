import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataRow } from "@/components/primitives/data-row";

describe("DataRow (Sprint QA)", () => {
  it("renders label + children", () => {
    render(<DataRow label="Revenue">715.68M</DataRow>);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("715.68M")).toBeInTheDocument();
  });

  it("applies emphasize (font-semibold)", () => {
    const { container } = render(
      <DataRow label="Total" emphasize>
        100M
      </DataRow>,
    );
    expect(container.querySelector(".font-semibold")).toBeTruthy();
  });

  it("applies indent class", () => {
    const { container } = render(
      <DataRow label="Sub-item" indent>
        50M
      </DataRow>,
    );
    expect(container.querySelector(".pl-4")).toBeTruthy();
  });

  it("applies note styling (text-xs)", () => {
    const { container } = render(
      <DataRow label="Note" note>
        10M
      </DataRow>,
    );
    expect(container.querySelector(".text-xs")).toBeTruthy();
  });
});
