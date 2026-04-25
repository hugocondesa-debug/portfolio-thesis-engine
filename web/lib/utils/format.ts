/**
 * Number / currency / percentage / date formatters.
 *
 * The PTE API serialises every Decimal as a **string** to preserve precision.
 * Use ``parseDecimal`` only when you need a JS number for *display* (Intl
 * formatters, progress bars). Never run arithmetic that should be exact in
 * the browser — that lives on the Python side.
 */

export function parseDecimal(value: string | null | undefined): number {
  if (value === null || value === undefined) return Number.NaN;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export interface CurrencyOptions {
  currency?: string;
  compact?: boolean;
  decimals?: number;
}

export function formatCurrency(
  value: string | number | null | undefined,
  options: CurrencyOptions = {},
): string {
  if (value === null || value === undefined) return "—";
  const { currency = "USD", compact = false, decimals } = options;
  const num = typeof value === "string" ? parseDecimal(value) : value;
  if (Number.isNaN(num)) return "—";

  const fractionDigits = decimals ?? (compact ? 1 : 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: compact ? "compact" : "standard",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(num);
}

export interface NumberOptions {
  compact?: boolean;
  decimals?: number;
}

export function formatNumber(
  value: string | number | null | undefined,
  options: NumberOptions = {},
): string {
  if (value === null || value === undefined) return "—";
  const { compact = false, decimals } = options;
  const num = typeof value === "string" ? parseDecimal(value) : value;
  if (Number.isNaN(num)) return "—";

  return new Intl.NumberFormat("en-US", {
    notation: compact ? "compact" : "standard",
    minimumFractionDigits: decimals ?? 0,
    maximumFractionDigits: decimals ?? (compact ? 1 : 0),
  }).format(num);
}

/**
 * Format a fraction as a percentage. Always treats the input as a fraction
 * (``0.105`` → ``"10.50%"``, ``1.9415`` → ``"194.15%"``). For PTE percent-
 * coded API strings (``"25"`` ≡ 25%), divide by 100 in the caller before
 * passing the value here. Sprint 1A.1 dropped the earlier value-magnitude
 * heuristic because it second-guessed legitimate 100%+ upsides.
 */
export function formatPercent(
  value: string | number | null | undefined,
  decimals: number = 2,
): string {
  if (value === null || value === undefined) return "—";
  const num = typeof value === "string" ? parseDecimal(value) : value;
  if (Number.isNaN(num)) return "—";

  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
}

export function formatMultiple(
  value: string | number | null | undefined,
  decimals: number = 2,
): string {
  if (value === null || value === undefined) return "—";
  const num = typeof value === "string" ? parseDecimal(value) : value;
  if (Number.isNaN(num)) return "—";
  return `${num.toFixed(decimals)}×`;
}

export function formatDate(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...options,
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  return formatDate(value, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function changeColorClass(
  value: string | number | null | undefined,
): string {
  if (value === null || value === undefined) return "text-neutral";
  const num = typeof value === "string" ? parseDecimal(value) : value;
  if (Number.isNaN(num) || num === 0) return "text-neutral";
  return num > 0 ? "text-positive" : "text-negative";
}
