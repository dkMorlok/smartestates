# API

REST, versioned (`/v1`). JSON in/out. Cursor pagination. Auth via session cookies (web app) or API tokens (power users, Phase 2).

## Conventions
- All responses wrapped: `{ data, meta }` where `meta` contains `cursor`, `total_estimate`, `model_version` where relevant.
- All times ISO 8601, UTC.
- All money in minor units (`price_haler` = CZK × 100? No — use `price_czk` as integer CZK to keep things readable; haler precision irrelevant for real estate).
- All filters use snake_case query params.
- Errors: RFC 7807 problem+json.
- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- Idempotency: write endpoints accept `Idempotency-Key` header.

## Endpoints

### Listings

```
GET /v1/listings
  ?bbox=lon1,lat1,lon2,lat2
  &city_district=Praha%205
  &property_type=byt
  &disposition=2+kk,3+kk
  &ownership_type=osobni
  &min_price=&max_price=
  &min_ppm2=&max_ppm2=
  &min_size_m2=&max_size_m2=
  &min_undervaluation_pct=
  &min_yield_pct=
  &max_risk_score=
  &exclude_flags=druzstevni_mismarked,flood_zone
  &min_confidence=0.5
  &sort=composite_desc|undervaluation_desc|price_asc|listing_date_desc
  &cursor=
  &limit=50
→ 200
{
  "data": [ListingSummary, ...],
  "meta": { "cursor": "eyJ...", "total_estimate": 1234,
            "model_version": "score-v3" }
}
```

```
GET /v1/listings/{id}
→ 200 ListingDetail
```

```
GET /v1/listings/{id}/history
→ 200 { "data": [ {observed_at, price, status, fields_changed}, ... ] }
```

```
GET /v1/listings/{id}/comparables?n=20
→ 200 { "data": [ListingSummary, ...] }
```

```
GET /v1/listings/{id}/score
→ 200 {
  "model_version": "score-v3",
  "computed_at": "...",
  "composite": 78.4,
  "components": {
    "undervaluation_pct": 14.2,
    "undervaluation_abs_czk": 850000,
    "yield_gross_pct": 4.6,
    "yield_confidence": 0.72,
    "liquidity_score": 65,
    "location_score": 81,
    "risk_score": 22,
    "confidence_score": 0.81
  },
  "risk_flags": ["panel_capex_due"],
  "segment_id": 14523,
  "segment_n_samples": 87,
  "segment_relaxation_level": 0,
  "explanation": [
    "Predicted ppm² 95,400; listed at 81,800 → 14.2% under model.",
    "Segment has 87 comparable active listings in Praha 5, panel, 2+kk, 50-70 m², good condition.",
    "Risk flag: panel building 1972, no renovation noted — capex likely."
  ]
}
```

### Map

```
GET /v1/map/listings?bbox=...&zoom=...&[same filters as /listings]
→ 200
{
  "type": "FeatureCollection",
  "features": [
    {"type":"Feature","geometry":{...},"properties":{
       "kind":"cluster","count":42,"avg_score":67
     }},
    {"type":"Feature","geometry":{...},"properties":{
       "kind":"listing","id":123,"price":4900000,"ppm2":86000,
       "composite":78,"confidence":0.8,"disposition":"2+kk"
     }}
  ]
}
```
Clustered when `zoom < 13`. Max 1000 features. Cached 60s.

### Markets

```
GET /v1/markets/segments?city_district=&property_type=
→ 200 list of segments with latest stats

GET /v1/markets/{segment_id}/stats?from=2024-01-01&to=2025-12-31
→ 200 time series of ppm2_median, dom_median, n_active
```

### Watchlists & alerts

```
POST /v1/watchlists           { name, criteria, notify_email }
GET  /v1/watchlists
GET  /v1/watchlists/{id}
PATCH /v1/watchlists/{id}     partial update
DELETE /v1/watchlists/{id}

GET  /v1/me/alerts?status=undismissed
POST /v1/alerts/{id}/dismiss
```

### Auth

```
POST /v1/auth/register        { email, password, display_name }
POST /v1/auth/login           { email, password }
POST /v1/auth/logout
POST /v1/auth/password-reset/request   { email }
POST /v1/auth/password-reset/confirm   { token, new_password }
GET  /v1/me
```

Session cookie HttpOnly, Secure, SameSite=Lax, 30-day expiry, rolling.

### Admin (role=admin only)

```
GET  /v1/admin/sources                       list + health
POST /v1/admin/sources/{slug}/pause
POST /v1/admin/sources/{slug}/resume
POST /v1/admin/sources/{slug}/canary         trigger health check

GET  /v1/admin/runs?source=&stage=&status=   recent source_runs
GET  /v1/admin/dlq                           dead-letter jobs
POST /v1/admin/dlq/{job_id}/replay

GET  /v1/admin/dedup-queue?status=pending
POST /v1/admin/dedup-clusters/merge          { listing_ids, canonical_id }
POST /v1/admin/dedup-clusters/reject         { queue_id }

GET  /v1/admin/scoring/configs
POST /v1/admin/scoring/configs               new model_version
POST /v1/admin/scoring/configs/{v}/promote   make it the public default

GET  /v1/admin/data-quality                  current dashboard data
```

## Schemas (key ones)

```typescript
type ListingSummary = {
  id: number;
  property_type: 'byt'|'dum'|'pozemek'|'komercni'|'ostatni';
  disposition: string | null;
  ownership_type: 'osobni'|'druzstevni'|'statni' | null;
  building_type: string | null;
  city_district: string | null;
  locality: string;
  size_m2: number | null;
  price_czk: number | null;
  price_per_m2: number | null;
  composite: number | null;
  undervaluation_pct: number | null;
  yield_gross_pct: number | null;
  confidence: number;
  risk_flags: string[];
  thumb_url: string | null;
  first_seen_at: string;
  source_slug: string;
};

type ListingDetail = ListingSummary & {
  description: string | null;
  features: Record<string, boolean | number | string>;
  photos: { url: string; thumb_url: string; }[];
  geom: { lat: number; lon: number; precision: string };
  agency: string | null;
  is_owner_direct: boolean | null;
  canonical_url: string;
  property_id: number;
  dedup_cluster_id: number | null;
  price_history: { observed_at: string; price: number }[];
};
```

## Caching
- `GET /v1/listings` results cached by query hash for 60s.
- `GET /v1/listings/{id}` cached 5 min, busted on listing update.
- `GET /v1/map/listings` cached 60s.
- `GET /v1/markets/.../stats` cached 1h.
- Admin endpoints: no cache.

## Rate limits
- Anonymous: 60 req/min/IP.
- Authenticated user: 300 req/min.
- API token (future): per-token limit configured.

## Errors

```json
{
  "type": "https://errors.example.cz/listing-not-found",
  "title": "Listing not found",
  "status": 404,
  "detail": "No listing with id=12345",
  "instance": "/v1/listings/12345"
}
```

## What we are not doing
- GraphQL (REST is enough; if a power user wants flexibility, give them SQL access later).
- WebSockets for live updates (alerts go via email; the data doesn't move minute-by-minute).
- Public unauthenticated bulk download (legal exposure, scraping concerns).
