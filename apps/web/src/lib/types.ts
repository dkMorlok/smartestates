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
