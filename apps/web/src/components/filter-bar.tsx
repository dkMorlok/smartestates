"use client";

import {
  type ReadonlyURLSearchParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { useEffect, useState } from "react";

import { DISPOSITIONS, OWNERSHIP_TYPES } from "@/lib/types";

// Filter fields kept in the URL so a search is shareable/bookmarkable.
const FIELDS = [
  "city_district",
  "disposition",
  "ownership_type",
  "min_price",
  "max_price",
  "min_size",
  "max_size",
] as const;

type FieldName = (typeof FIELDS)[number];
type FormState = Record<FieldName, string>;

function stateFromParams(params: ReadonlyURLSearchParams): FormState {
  return Object.fromEntries(
    FIELDS.map((f) => [f, params.get(f) ?? ""]),
  ) as FormState;
}

const inputClass =
  "h-9 rounded-md border border-neutral-300 bg-white px-2 text-sm " +
  "focus:border-neutral-500 focus:outline-none";

export function FilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [form, setForm] = useState<FormState>(() => stateFromParams(params));

  // Keep the form in sync when the URL changes (back/forward, reset).
  useEffect(() => {
    setForm(stateFromParams(params));
  }, [params]);

  function update(name: FieldName, value: string) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function apply(event: React.FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const field of FIELDS) {
      if (form[field].trim()) next.set(field, form[field].trim());
    }
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }

  function reset() {
    router.replace(pathname);
  }

  return (
    <form
      onSubmit={apply}
      className="flex flex-wrap items-end gap-3 border-b border-neutral-200 pb-4"
    >
      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Městská část
        <input
          className={inputClass}
          placeholder="Praha 5"
          value={form.city_district}
          onChange={(e) => update("city_district", e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Dispozice
        <select
          className={inputClass}
          value={form.disposition}
          onChange={(e) => update("disposition", e.target.value)}
        >
          <option value="">Vše</option>
          {DISPOSITIONS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Vlastnictví
        <select
          className={inputClass}
          value={form.ownership_type}
          onChange={(e) => update("ownership_type", e.target.value)}
        >
          <option value="">Vše</option>
          {OWNERSHIP_TYPES.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Cena od (Kč)
        <input
          className={`${inputClass} w-32`}
          type="number"
          min={0}
          value={form.min_price}
          onChange={(e) => update("min_price", e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Cena do (Kč)
        <input
          className={`${inputClass} w-32`}
          type="number"
          min={0}
          value={form.max_price}
          onChange={(e) => update("max_price", e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Plocha od (m²)
        <input
          className={`${inputClass} w-24`}
          type="number"
          min={0}
          value={form.min_size}
          onChange={(e) => update("min_size", e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-neutral-600">
        Plocha do (m²)
        <input
          className={`${inputClass} w-24`}
          type="number"
          min={0}
          value={form.max_size}
          onChange={(e) => update("max_size", e.target.value)}
        />
      </label>

      <button
        type="submit"
        className="h-9 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white hover:bg-neutral-700"
      >
        Hledat
      </button>
      <button
        type="button"
        onClick={reset}
        className="h-9 rounded-md border border-neutral-300 px-4 text-sm hover:bg-neutral-100"
      >
        Zrušit filtry
      </button>
    </form>
  );
}
