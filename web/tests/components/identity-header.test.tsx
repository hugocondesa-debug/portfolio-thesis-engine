import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IdentityHeader } from "@/components/sections/identity-header";
import {
  canonicalFixture,
  fichaFixture,
  tickerDetailFixture,
} from "@/tests/fixtures";

describe("IdentityHeader", () => {
  it("renders ticker and name", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
      />,
    );
    expect(screen.getByText("1846.HK")).toBeInTheDocument();
    expect(
      screen.getByText(/EuroEyes International Eye Clinic Limited/),
    ).toBeInTheDocument();
  });

  it("renders profile / currency / exchange chips", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={null}
      />,
    );
    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByText("HKD")).toBeInTheDocument();
    expect(screen.getByText("HKEX")).toBeInTheDocument();
  });

  it("renders thesis when ficha provides one", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={fichaFixture}
      />,
    );
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText(/compounding M&A platform/)).toBeInTheDocument();
  });

  it("renders market price from ficha when available", () => {
    render(
      <IdentityHeader
        detail={tickerDetailFixture}
        canonical={canonicalFixture}
        ficha={fichaFixture}
      />,
    );
    expect(screen.getByText(/2\.92/)).toBeInTheDocument();
    expect(screen.getByText(/Market price/)).toBeInTheDocument();
  });
});
