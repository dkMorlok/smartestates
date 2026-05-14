import type { ListingPage, ListingQuery } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

/** Build a query string from defined ListingQuery fields only. */
function toSearchParams(query: ListingQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

export async function fetchListings(query: ListingQuery): Promise<ListingPage> {
  const qs = toSearchParams(query);
  const res = await fetch(`${API_BASE}/v1/listings${qs ? `?${qs}` : ""}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Listings request failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as ListingPage;
}
