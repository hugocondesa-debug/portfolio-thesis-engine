import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  EmptySectionNote,
  SectionHeader,
  SectionShell,
} from "@/components/primitives/section-shell";

describe("SectionShell (Sprint QA)", () => {
  it("renders title + subtitle + body", () => {
    render(
      <SectionShell title="Test Section" subtitle="subtitle text">
        <div>body content</div>
      </SectionShell>,
    );
    expect(screen.getByText("Test Section")).toBeInTheDocument();
    expect(screen.getByText("subtitle text")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
  });

  it("uses dashed border in empty state", () => {
    const { container } = render(
      <SectionShell title="Empty" emptyState>
        <div>empty</div>
      </SectionShell>,
    );
    expect(container.querySelector(".border-dashed")).toBeTruthy();
  });

  it("does not use dashed border by default", () => {
    const { container } = render(
      <SectionShell title="Normal">
        <div>body</div>
      </SectionShell>,
    );
    expect(container.querySelector(".border-dashed")).toBeNull();
  });

  it("uses responsive padding (p-4 md:p-6)", () => {
    const { container } = render(
      <SectionShell title="Padded">
        <div>body</div>
      </SectionShell>,
    );
    const section = container.querySelector("section");
    expect(section?.className).toMatch(/\bp-4\b/);
    expect(section?.className).toMatch(/md:p-6/);
  });

  it("renders header-area actions slot", () => {
    render(
      <SectionShell title="With Actions" actions={<button>Action</button>}>
        <div>body</div>
      </SectionShell>,
    );
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });
});

describe("SectionHeader (Sprint QA)", () => {
  it("renders title without subtitle", () => {
    render(<SectionHeader title="Just Title" />);
    expect(screen.getByText("Just Title")).toBeInTheDocument();
  });
});

describe("EmptySectionNote (Sprint QA)", () => {
  it("renders the message", () => {
    render(<EmptySectionNote message="Nothing to see here." />);
    expect(screen.getByText("Nothing to see here.")).toBeInTheDocument();
  });
});
