import { describe, expect, it } from "vitest";
import {
  changeColorClass,
  formatCurrency,
  formatDate,
  formatMultiple,
  formatNumber,
  formatPercent,
  parseDecimal,
} from "@/lib/utils/format";

describe("parseDecimal", () => {
  it("converts string to number", () => {
    expect(parseDecimal("1.234")).toBe(1.234);
  });
  it("returns NaN for null/undefined", () => {
    expect(parseDecimal(null)).toBeNaN();
    expect(parseDecimal(undefined)).toBeNaN();
  });
  it("returns NaN for non-numeric strings", () => {
    expect(parseDecimal("abc")).toBeNaN();
  });
});

describe("formatCurrency", () => {
  it("formats compact HKD", () => {
    expect(formatCurrency("787250200", { currency: "HKD", compact: true })).toMatch(/787\.3?M/);
  });
  it("returns em-dash for null", () => {
    expect(formatCurrency(null)).toBe("—");
  });
  it("respects decimals option", () => {
    const result = formatCurrency("2.92", { currency: "HKD", decimals: 2 });
    expect(result).toContain("2.92");
  });
});

describe("formatPercent", () => {
  it("treats decimal ratios as fractions", () => {
    expect(formatPercent("0.105")).toBe("10.50%");
  });
  it("treats >1 fractions as fractions, not implicit percent", () => {
    // Sprint 1A.1 — caller is responsible for dividing API percent strings
    // by 100. A fraction of 1.9415 means 194.15% (not 1.94%).
    expect(formatPercent("1.9415")).toBe("194.15%");
  });
  it("returns em-dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatMultiple", () => {
  it("formats with × symbol", () => {
    expect(formatMultiple("12.5")).toBe("12.50×");
  });
});

describe("formatNumber", () => {
  it("compact mode", () => {
    expect(formatNumber("331885000", { compact: true })).toMatch(/331\.9?M/);
  });
});

describe("formatDate", () => {
  it("formats ISO timestamp", () => {
    const out = formatDate("2026-04-24T21:16:44Z");
    expect(out).toContain("2026");
  });
  it("returns em-dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("changeColorClass", () => {
  it("positive returns text-positive", () => {
    expect(changeColorClass("0.05")).toBe("text-positive");
  });
  it("negative returns text-negative", () => {
    expect(changeColorClass("-0.05")).toBe("text-negative");
  });
  it("zero returns text-neutral", () => {
    expect(changeColorClass("0")).toBe("text-neutral");
  });
});
