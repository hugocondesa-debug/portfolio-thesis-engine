import { describe, expect, it } from "vitest";
import {
  buildSourcePath,
  inferConfidence,
  resolveAdjustmentChain,
  resolveCrossStatementLinks,
  resolveFormula,
  resolveTraceability,
} from "@/lib/traceability/registry";
import type { CanonicalState } from "@/lib/types/canonical";
import { adjustmentsFixture, canonicalFixture } from "@/tests/fixtures";

describe("traceability registry (Sprint 1C)", () => {
  it("buildSourcePath returns the supplied metadata", () => {
    const source = buildSourcePath({
      root: "canonical",
      logical: "canonical.analysis.ratios_by_period[FY2024].roic",
      field: "roic",
      label: "ROIC",
      period: "FY2024",
      value: "8.20",
      format: "percent_direct",
    });
    expect(source.field).toBe("roic");
    expect(source.format).toBe("percent_direct");
    expect(source.period).toBe("FY2024");
  });

  it("resolveAdjustmentChain finds operating_income module mappings", () => {
    const chain = resolveAdjustmentChain(
      "operating_income",
      adjustmentsFixture,
      "FY2024",
    );
    expect(chain.affected_modules).toContain("module_a_taxes");
    expect(chain.affected_modules).toContain("module_b_provisions");
    expect(chain.affected_modules).toContain("module_c_leases");
    expect(chain.adjustments.length).toBeGreaterThan(0);
  });

  it("resolveAdjustmentChain returns empty for unknown field", () => {
    const chain = resolveAdjustmentChain(
      "unknown_field_xyz",
      adjustmentsFixture,
    );
    expect(chain.affected_modules).toHaveLength(0);
    expect(chain.adjustments).toHaveLength(0);
  });

  it("resolveAdjustmentChain filters by period", () => {
    const chain = resolveAdjustmentChain(
      "operating_income",
      adjustmentsFixture,
      "FY2099",
    );
    // No fixture adjustment touches FY2099
    expect(chain.adjustments).toHaveLength(0);
  });

  it("resolveCrossStatementLinks for operating_income returns nav targets", () => {
    const links = resolveCrossStatementLinks("operating_income", "FY2024");
    expect(links.length).toBeGreaterThan(0);
    expect(
      links.some((l) => l.target_section === "historical-financials"),
    ).toBe(true);
  });

  it("resolveCrossStatementLinks returns [] when period is missing", () => {
    const links = resolveCrossStatementLinks("operating_income");
    expect(links).toHaveLength(0);
  });

  it("resolveFormula returns ROIC formula", () => {
    const formula = resolveFormula("roic");
    expect(formula).toContain("NOPAT");
    expect(formula).toContain("Invested Capital");
  });

  it("resolveFormula returns undefined for unknown field", () => {
    expect(resolveFormula("revenue")).toBeUndefined();
  });

  it("inferConfidence returns REPORTED when no adjustments", () => {
    expect(inferConfidence("revenue", [])).toBe("REPORTED");
  });

  it("inferConfidence returns DERIVED with REPORTED-only adjustments", () => {
    const adjustments = adjustmentsFixture.module_a_taxes;
    expect(inferConfidence("operating_income", adjustments)).toBe("DERIVED");
  });

  it("resolveTraceability returns full resolution for ROIC", () => {
    const canonical = {
      ...canonicalFixture,
      adjustments:
        adjustmentsFixture as unknown as CanonicalState["adjustments"],
    };
    const source = buildSourcePath({
      root: "canonical",
      logical: "canonical.analysis.ratios_by_period[FY2024].roic",
      field: "roic",
      label: "ROIC",
      period: "FY2024",
      value: "8.20",
      format: "percent_direct",
    });
    const resolution = resolveTraceability(source, canonical);
    expect(resolution.formula).toContain("NOPAT");
    expect(resolution.confidence).toBeDefined();
    expect(resolution.cross_links.length).toBeGreaterThan(0);
  });
});
