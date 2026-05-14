"use client";

import {
  type ReadonlyURLSearchParams,
  useSearchParams,
} from "next/navigation";
import { useMemo } from "react";

import type { ListingQuery } from "@/lib/types";

import { FilterBar } from "./filter-bar";
import { ListingsTable } from "./listings-table";

function numberParam(
  params: ReadonlyURLSearchParams,
  key: string,
): number | undefined {
  const raw = params.get(key);
  if (raw === null || raw.trim() === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function stringParam(
  params: ReadonlyURLSearchParams,
  key: string,
): string | undefined {
  return params.get(key)?.trim() || undefined;
}

/** Derive the API query from the URL search params. */
function queryFromParams(params: ReadonlyURLSearchParams): ListingQuery {
  return {
    city_district: stringParam(params, "city_district"),
    disposition: stringParam(params, "disposition"),
    ownership_type: stringParam(params, "ownership_type"),
    property_type: stringParam(params, "property_type"),
    min_price: numberParam(params, "min_price"),
    max_price: numberParam(params, "max_price"),
    min_size: numberParam(params, "min_size"),
    max_size: numberParam(params, "max_size"),
    limit: 50,
    offset: 0,
  };
}

export function SearchClient() {
  const params = useSearchParams();
  // Re-derive (and re-key the query) only when the URL actually changes.
  const query = useMemo(() => queryFromParams(params), [params]);

  return (
    <div className="flex flex-col gap-2">
      <FilterBar />
      <ListingsTable query={query} />
    </div>
  );
}
