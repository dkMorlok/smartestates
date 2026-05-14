"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchListings } from "./api";
import type { ListingQuery } from "./types";

/** Fetch a page of listings for the current filter state. */
export function useListings(query: ListingQuery) {
  return useQuery({
    queryKey: ["listings", query],
    queryFn: () => fetchListings(query),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
