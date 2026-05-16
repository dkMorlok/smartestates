"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  usePathname,
  useRouter,
  useSearchParams,
  type ReadonlyURLSearchParams,
} from "next/navigation";
import { useMemo } from "react";

import { FilterBar } from "@/components/filter-bar";
import { fetchBreakdown } from "@/lib/api";
import { formatPriceCZK, formatScorePct } from "@/lib/format";
import type { BreakdownQuery, BreakdownRow, GroupBy } from "@/lib/types";

import { BreakdownMap } from "./breakdown-map";
import { GeolocationHeatmap } from "./geolocation-heatmap";

// URL-param keys that the analytics endpoint understands (subset of the
// listing filter set). All optional.
const FILTER_KEYS = [
  "property_type",
  "disposition",
  "ownership_type",
  "city_district",
  "min_price",
  "max_price",
  "min_size",
  "max_size",
] as const;

function queryFromParams(
  params: ReadonlyURLSearchParams,
  groupBy: GroupBy,
): BreakdownQuery {
  const q: BreakdownQuery = { group_by: groupBy };
  for (const k of FILTER_KEYS) {
    const v = params.get(k);
    if (v === null || v === "") continue;
    if (k.startsWith("min_") || k.startsWith("max_")) {
      const n = Number(v);
      if (Number.isFinite(n)) q[k] = n as never;
    } else {
      q[k] = v as never;
    }
  }
  return q;
}

function toNum(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function formatPpm2(v: number | string | null | undefined): string {
  const n = toNum(v);
  if (n === null) return "—";
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(
    Math.round(n),
  )} Kč/m²`;
}

function changeColor(pct: number | null): string {
  if (pct === null) return "text-neutral-400";
  if (pct >= 2) return "text-rose-600";
  if (pct <= -2) return "text-emerald-600";
  return "text-neutral-600";
}

export function AnalyticsClient() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const groupBy = (params.get("group_by") as GroupBy | null) ?? "disposition";
  const query = useMemo(() => queryFromParams(params, groupBy), [params, groupBy]);

  const { data, isFetching, error } = useQuery({
    queryKey: ["breakdown", query],
    queryFn: () => fetchBreakdown(query),
    staleTime: 30_000,
  });

  function setGroupBy(next: GroupBy) {
    const sp = new URLSearchParams(params.toString());
    sp.set("group_by", next);
    router.replace(`${pathname}?${sp.toString()}`);
  }

  // Build the drill-down /search URL for a group row: keep current filters,
  // add the row's group key as the appropriate filter.
  function searchHref(row: BreakdownRow): string {
    const sp = new URLSearchParams();
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      if (v) sp.set(k, v);
    }
    if (row.group_key !== "(neuvedeno)") {
      sp.set(groupBy, row.group_key);
    }
    return `/search?${sp.toString()}`;
  }

  const rows = data?.rows ?? [];
  const totalCount = rows.reduce((s, r) => s + r.count, 0);

  return (
    <div className="space-y-4">
      <FilterBar />

      <div className="flex items-center gap-3">
        <span className="text-sm text-neutral-600">Rozpad podle</span>
        <div className="inline-flex overflow-hidden rounded-md border border-neutral-300">
          {(["disposition", "locality"] as const).map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => setGroupBy(g)}
              className={
                "px-3 py-1.5 text-sm " +
                (groupBy === g
                  ? "bg-neutral-900 text-white"
                  : "bg-white text-neutral-700 hover:bg-neutral-100")
              }
            >
              {g === "disposition" ? "Dispozice" : "Lokalita"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-neutral-500">
          {isFetching ? "Načítám…" : `${rows.length} skupin · ${totalCount} nabídek`}
        </span>
      </div>

      {error ? (
        <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          Chyba: {String(error)}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="overflow-hidden rounded-md border border-neutral-200">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-xs uppercase text-neutral-500">
              <tr>
                <th className="px-3 py-2 text-left">
                  {groupBy === "disposition" ? "Dispozice" : "Lokalita"}
                </th>
                <th className="px-3 py-2 text-right">Počet</th>
                <th className="px-3 py-2 text-right">Ø cena</th>
                <th className="px-3 py-2 text-right">Min</th>
                <th className="px-3 py-2 text-right">Max</th>
                <th className="px-3 py-2 text-right">Med Kč/m²</th>
                <th className="px-3 py-2 text-right">Δ 6m</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && !isFetching ? (
                <tr>
                  <td
                    colSpan={7}
                    className="px-3 py-8 text-center text-neutral-500"
                  >
                    Žádná data pro tyto filtry.
                  </td>
                </tr>
              ) : null}
              {rows.map((r) => (
                <tr
                  key={r.group_key}
                  className="border-t border-neutral-100 hover:bg-neutral-50"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={searchHref(r)}
                      className="text-neutral-900 hover:underline"
                    >
                      {r.group_key}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.count}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-700">
                    {formatPriceCZK(r.avg_price_czk)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                    {formatPriceCZK(r.min_price_czk)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                    {formatPriceCZK(r.max_price_czk)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPpm2(r.median_ppm2)}
                  </td>
                  <td
                    className={
                      "px-3 py-2 text-right tabular-nums " +
                      changeColor(r.change_pct_6m)
                    }
                  >
                    {r.change_pct_6m === null
                      ? "—"
                      : formatScorePct(r.change_pct_6m)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <BreakdownMap rows={rows} groupBy={groupBy} />
      </div>

      <div className="border-t border-neutral-200 pt-6">
        <GeolocationHeatmap />
      </div>
    </div>
  );
}
