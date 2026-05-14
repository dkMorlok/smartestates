// Czech-locale formatting helpers. See docs/UI.md — all numbers/dates render
// in cs-CZ.
import type { Decimalish } from "./types";

const EM_DASH = "—";

function toNumber(value: Decimalish): number | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatPriceCZK(value: Decimalish): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return new Intl.NumberFormat("cs-CZ", {
    style: "currency",
    currency: "CZK",
    maximumFractionDigits: 0,
  }).format(n);
}

export function formatArea(value: Decimalish): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(n)} m²`;
}

export function formatPricePerM2(price: Decimalish, size: Decimalish): string {
  const p = toNumber(price);
  const s = toNumber(size);
  if (p === null || s === null || s === 0) return EM_DASH;
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(
    Math.round(p / s),
  )} Kč/m²`;
}

/** Title-case-ish label for an enum-ish value, e.g. "po_rekonstrukci". */
export function humanize(value: string | null): string {
  if (!value) return EM_DASH;
  return value.replace(/_/g, " ");
}
