import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PeersComparison } from "@/components/sections/peers-comparison";
import { canonicalFixture, peersFixture } from "@/tests/fixtures";

describe("PeersComparison (Sprint 1C)", () => {
  it("renders empty state when no peers configured", () => {
    render(<PeersComparison peers={null} canonical={canonicalFixture} />);
    expect(screen.getByText(/No peers configuration/)).toBeInTheDocument();
  });

  it("renders peer cards with country and currency", () => {
    render(
      <PeersComparison peers={peersFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText("EYE")).toBeInTheDocument();
    expect(screen.getByText("National Vision Holdings")).toBeInTheDocument();
    // Country/currency badges may collide with other elements — assert at
    // least one occurrence.
    expect(screen.getAllByText("US").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("USD").length).toBeGreaterThanOrEqual(1);
  });

  it("shows excluded badge for opted-out peers", () => {
    render(
      <PeersComparison peers={peersFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText("Excluded")).toBeInTheDocument();
    // Two included peers in the fixture
    expect(screen.getAllByText("Included").length).toBeGreaterThanOrEqual(2);
  });

  it("shows multiples empty-state when sqlite_peers is empty", () => {
    render(
      <PeersComparison peers={peersFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText(/Multiples cache empty/)).toBeInTheDocument();
  });

  it("renders sector and industry context badges", () => {
    render(
      <PeersComparison peers={peersFixture} canonical={canonicalFixture} />,
    );
    expect(screen.getByText(/Sector: Healthcare/)).toBeInTheDocument();
    expect(
      screen.getByText(/Industry: Medical Care Facilities/),
    ).toBeInTheDocument();
  });

  it("converts USER_OVERRIDE source to compact USER badge", () => {
    render(
      <PeersComparison peers={peersFixture} canonical={canonicalFixture} />,
    );
    // 3 peers all with USER_OVERRIDE source → 3+ USER badges
    expect(screen.getAllByText("USER").length).toBeGreaterThanOrEqual(3);
  });
});
