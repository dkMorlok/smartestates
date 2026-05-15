import type {
  BBox,
  ListingDetail,
  ListingPage,
  ListingQuery,
  ListingScore,
  MapResponse,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

/** Build a query string from defined fields only (skips empty/null/undefined). */
function toSearchParams<T extends object>(query: T): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query) as [string, unknown][]) {
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

/** Fetch one listing's full detail. Returns null on 404. */
export async function fetchListing(id: number): Promise<ListingDetail | null> {
  const res = await fetch(`${API_BASE}/v1/listings/${id}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Listing ${id} request failed: ${res.status}`);
  }
  return (await res.json()) as ListingDetail;
}

/**
 * Fetch a listing's score. Returns null on 404 (no confident score yet — UI
 * renders a neutral "not computed" state, not an error).
 */
export async function fetchListingScore(
  id: number,
): Promise<ListingScore | null> {
  const res = await fetch(`${API_BASE}/v1/listings/${id}/score`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Listing ${id} score request failed: ${res.status}`);
  }
  return (await res.json()) as ListingScore;
}

export async function fetchMapListings(
  bbox: BBox,
  zoom: number,
): Promise<MapResponse> {
  const qs = toSearchParams({ ...bbox, zoom });
  const res = await fetch(`${API_BASE}/v1/listings/map?${qs}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Map request failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as MapResponse;
}
