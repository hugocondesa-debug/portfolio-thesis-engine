import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IdentityHeader } from "@/components/sections/identity-header";
import {
  canonicalFixture,
  canonicalPreliminaryFixture,
  fichaFixture,
  tickerDetailFixture,
  valuationFixture,
} from "@/tests/fixtures";

describe("IdentityHeader", () => {
  it("renders ticker, name and audit badge for an audited snapshot", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText("1846.HK")).toBeInTheDocument();
    expect(
      screen.getByText(/EuroEyes International Eye Clinic Limited/),
    ).toBeInTheDocument();
    // Audit badge — the literal text "audited" rendered uppercase via CSS.
    expect(screen.getByText("audited")).toBeInTheDocument();
    // Period badge — read from canonical.reclassified_statements[0].
    expect(screen.getByText("FY2024")).toBeInTheDocument();
  });

  it("renders profile / currency / exchange data rows", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByText("HKD")).toBeInTheDocument();
    expect(screen.getByText("HKEX")).toBeInTheDocument();
  });

  it("populates shares_outstanding from valuation.market", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
        valuation={valuationFixture}
      />,
    );
    // 331,885,000 → "331.9M" via formatNumber({compact: true})
    expect(screen.getByText(/331\.9M|331,885,000/)).toBeInTheDocument();
  });

  it("renders the market price from valuation.market when present", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
        valuation={valuationFixture}
      />,
    );
    // valuation.market.price = "2.65" with currency HKD
    expect(screen.getByText(/HK\$2\.65|2\.65/)).toBeInTheDocument();
    expect(screen.getByText(/Market price/)).toBeInTheDocument();
  });

  it("renders thesis when ficha provides one", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={fichaFixture}
        valuation={valuationFixture}
      />,
    );
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText(/compounding M&A platform/)).toBeInTheDocument();
  });

  it("renders an audit warning banner when status is preliminary", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalPreliminaryFixture}
        ficha={null}
        valuation={valuationFixture}
      />,
    );
    // "preliminary" appears twice (badge + banner body) — assert both exist.
    expect(screen.getAllByText("preliminary").length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByText(/this snapshot is based on/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/--base-period LATEST-AUDITED/)).toBeInTheDocument();
  });

  it("falls back to canonical identity values when valuation is null", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
        valuation={null}
      />,
    );
    // Shares from canonical.identity.shares_outstanding (same value).
    expect(screen.getByText(/331\.9M|331,885,000/)).toBeInTheDocument();
    // No market-price block because valuation is null.
    expect(screen.queryByText(/Market price/)).not.toBeInTheDocument();
  });

  // Sprint 1B.1 — conviction grid and guardrails badge.
  describe("Sprint 1B.1 conviction grid + guardrails", () => {
    it("renders the conviction grid with 6 dimensions when ficha is present", () => {
      render(
        <IdentityHeader
          detail={tickerDetailFixture}
          canonical={canonicalFixture}
          ficha={fichaFixture}
          valuation={valuationFixture}
        />,
      );
      expect(screen.getByText("Conviction scores")).toBeInTheDocument();
      expect(screen.getByText("Forecast")).toBeInTheDocument();
      expect(screen.getByText("Valuation")).toBeInTheDocument();
      expect(screen.getByText("Asymmetry")).toBeInTheDocument();
      expect(screen.getByText("Timing")).toBeInTheDocument();
      expect(screen.getByText("Liquidity")).toBeInTheDocument();
      expect(screen.getByText("Governance")).toBeInTheDocument();
    });

    it("renders the conviction grid using valuation.conviction when ficha is null", () => {
      render(
        <IdentityHeader
          detail={tickerDetailFixture}
          canonical={canonicalFixture}
          ficha={null}
          valuation={valuationFixture}
        />,
      );
      expect(screen.getByText("Conviction scores")).toBeInTheDocument();
    });

    it("renders the guardrails badge when valuation guardrails carry an overall status", () => {
      render(
        <IdentityHeader
          detail={tickerDetailFixture}
          canonical={canonicalFixture}
          ficha={null}
          valuation={valuationFixture}
        />,
      );
      // valuationFixture.guardrails.overall = "PASS"
      expect(screen.getByText(/Guardrails: PASS/)).toBeInTheDocument();
    });
  });
});
