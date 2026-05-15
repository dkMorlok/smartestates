// Types mirroring the Realitní Skener API (see src/api/routers/listings.py).
// Pydantic serialises Decimal as a JSON string, so numeric money/area fields
// arrive as `string`; treat them as `number | string` and coerce on display.

export type Decimalish = number | string | null;

export interface ListingSummary {
  id: number;
  source_slug: string;
  canonical_url: string;
  property_type: string;
  disposition: string | null;
  ownership_type: string | null;
  building_type: string | null;
  condition: string | null;
  size_m2: Decimalish;
  price_czk: Decimalish;
  locality: string | null;
  city_district: string | null;
  status: string;
  lat: number | null;
  lon: number | null;
  // Joined from latest score (optional — server may not include this yet).
  // See Week 5d: /v1/listings score join.
  score?: ListingScoreSummary | null;
}

// Minimal score view that travels with each ListingSummary row.
export interface ListingScoreSummary {
  composite: Decimalish;
  undervaluation_pct: Decimalish;
  confidence_score: Decimalish;
}

export interface ListingPage {
  data: ListingSummary[];
  meta: {
    limit: number;
    offset: number;
    total: number;
  };
}

// Query params accepted by GET /v1/listings. Undefined fields are omitted.
export interface ListingQuery {
  status?: string;
  property_type?: string;
  disposition?: string;
  ownership_type?: string;
  city_district?: string;
  locality?: string;
  min_price?: number;
  max_price?: number;
  min_size?: number;
  max_size?: number;
  limit?: number;
  offset?: number;
}

export const DISPOSITIONS = [
  "garsoniera",
  "1+kk",
  "1+1",
  "2+kk",
  "2+1",
  "3+kk",
  "3+1",
  "4+kk",
  "4+1",
  "5+kk",
  "5+1",
  "6+",
  "atypicky",
] as const;

export const OWNERSHIP_TYPES = ["osobni", "druzstevni", "statni"] as const;

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

export interface PhotoOut {
  url: string;
  width: number | null;
  height: number | null;
}

export interface ListingDetail extends ListingSummary {
  usable_area_m2: Decimalish;
  land_area_m2: Decimalish;
  rooms: number | null;
  bathrooms: number | null;
  floor_current: number | null;
  floor_total: number | null;
  year_built: number | null;
  energy_class: string | null;
  description: string | null;
  agency: string | null;
  agent_name: string | null;
  is_owner_direct: boolean | null;
  features: Record<string, unknown>;
  postcode: string | null;
  cadastral_area: string | null;
  address_normalized: string | null;
  photos: PhotoOut[];
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

export interface BBox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

export interface MapPin {
  id: number;
  lat: number;
  lon: number;
  price_czk: Decimalish;
  disposition: string | null;
}

export interface MapCluster {
  lat: number;
  lon: number;
  count: number;
}

export interface MapResponse {
  mode: "pins" | "clusters";
  pins: MapPin[];
  clusters: MapCluster[];
}

// ---------------------------------------------------------------------------
// Score
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Analytics (breakdown)
// ---------------------------------------------------------------------------

export type GroupBy = "disposition" | "locality";

export interface BreakdownRow {
  group_key: string;
  count: number;
  avg_price_czk: Decimalish;
  min_price_czk: Decimalish;
  max_price_czk: Decimalish;
  avg_ppm2: Decimalish;
  median_ppm2: Decimalish;
  median_ppm2_180d_ago: Decimalish;
  change_pct_6m: number | null;
  centroid_lat: number | null;
  centroid_lon: number | null;
}

export interface BreakdownResponse {
  group_by: GroupBy;
  rows: BreakdownRow[];
}

// Query params accepted by GET /v1/analytics/breakdown.
export interface BreakdownQuery {
  group_by?: GroupBy;
  property_type?: string;
  disposition?: string;
  ownership_type?: string;
  city_district?: string;
  min_price?: number;
  max_price?: number;
  min_size?: number;
  max_size?: number;
}

// /v1/listings/{id}/score. Numerics arrive as Decimal-strings; coerce on use.
export interface ListingScore {
  listing_id: number;
  model_version: string;
  computed_at: string;
  composite: Decimalish;
  undervaluation_pct: Decimalish;
  undervaluation_abs: Decimalish;
  yield_gross_pct: Decimalish;
  yield_confidence: Decimalish;
  liquidity_score: Decimalish;
  location_score: Decimalish;
  risk_score: Decimalish;
  confidence_score: Decimalish;
  risk_flags: string[];
  components: Record<string, unknown>;
}
