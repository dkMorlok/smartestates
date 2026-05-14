# Ingestion Pipeline

## Goals
- One module per source. Adding a source must not require changing the core.
- Resilient to source breakage. Snapshot raw, version parsers, replay offline.
- Polite. Respect rate limits, identify ourselves, back off on errors.
- Idempotent. Re-running any stage produces the same result.

## Source SDK

Every source implements:

```python
class Source(Protocol):
    slug: str                              # 'sreality'
    kind: Literal['json_api','html','feed']

    def discover(self, params: dict, since: datetime | None) \
            -> Iterator[ListingRef]: ...

    def fetch(self, ref: ListingRef) -> RawDocument: ...

    def parse(self, raw: RawDocument) -> ParsedListing: ...

    def health_check(self) -> SourceHealth: ...
```

`ListingRef = (source_slug, source_listing_id, url, hint_jsonb)`
`RawDocument = (content_bytes, content_type, http_status, headers, fetched_at)`
`ParsedListing` — pydantic model, see `packages/shared/schemas.py`.

## Pipeline stages (Celery queues)

```
discover ─► fetch ─► parse ─► normalize ─► geocode ─► dedup ─► diff
                                                              │
                                                              └─► (nightly) market_stat ─► score ─► notify
```

| Queue | Concurrency | Time budget | Notes |
|---|---|---|---|
| `ingest.discover` | 2 per source | minutes | Redis lock per `(source, params_hash)` |
| `ingest.fetch` | 8–16 | seconds | network-bound, token-bucket rate-limited |
| `ingest.parse` | CPU cores | ms | pure CPU |
| `normalize` | 4 | ms | DB-bound |
| `geocode` | 2 | 100–500ms | external service caps |
| `dedup` | 4 | ms | DB-bound |
| `diff` | 4 | ms | DB-bound |
| `analytics.market_stat` | 1 | minutes | nightly |
| `analytics.score` | 2 | minutes | nightly |
| `notify` | 1 | ms | rate-limited per user |

## Stage details

### discover
- Beat enqueues `ingest.discover(source, params)` per `(source × region × category × type)`.
- Worker paginates the source's search endpoint. Stops when a page yields zero new `source_listing_id`s.
- Emits `ingest.fetch(source, listing_ref)` per result, but **only if** the search response shows the listing is new OR `last_modification` is later than our `listing.last_seen_at`.
- Writes a `source_run` row with counts.

### fetch
- Acquires token from Redis token bucket (key: `rl:{source_slug}`).
- HTTP GET with our `User-Agent: RealitniSkener/0.1 (+contact@example.cz)`.
- Stores raw payload to S3 keyed `raw/{source_slug}/{yyyy-mm}/{listing_id}/{fetched_at}.{ext}`.
- Inserts `raw_listing` row with `content_hash = sha256(payload)`.
- **Skip parse if `content_hash` matches the most recent prior row** — page unchanged.
- Retries: exponential backoff (1m, 5m, 30m, 2h, dead). Dead → DLQ.
- 429/503 → mark source `degraded`, back off, alert if it persists 30+ min.

### parse
- Looks up source module by slug, calls `source.parse(raw)`.
- pydantic validation. On validation error, mark `raw_listing.parse_status='quarantine'`, store the error, continue. **Never crash the worker on bad data.**
- Emits `normalize(raw_listing_id)` on success.

### normalize
- Maps source-specific enums to canonical enums (e.g., Sreality "Užitná plocha" → `usable_area_m2`).
- Currency assumed CZK unless stated otherwise; reject non-CZK to a quarantine table.
- Disposition string parsed against a fixed regex set (`1+kk`, `2+1`, `3+kk`, `atypicky`, etc.). Unknown → `null`, flag for review.
- Upserts `listing` by `(source_id, source_listing_id)`.
- Sets `last_seen_at = now()`. If `status` was `withdrawn` and we see it again, flip to `active` and record in `listing_version`.

### geocode
- See `GEO.md`. If source provides GPS (Sreality does), trust it with `address_precision='source_gps'` but still resolve street name from RÚIAN reverse.
- If no GPS, geocode address string. Result has a precision label.
- Find or create `property` by RÚIAN address code (preferred) or by `ST_DWithin(geom, 0.001°)` + same `address_normalized`.

### dedup
Three tiers:
1. **Exact:** same `ruian_address_code` + size within ±2 m² + same disposition + same ownership_type → auto-cluster.
2. **Strong:** same property_id + price within ±5% + listed within 30 days → auto-cluster.
3. **Fuzzy:** distance < 30m + same disposition + size within ±5% + photo phash Hamming distance < 8 → enqueue to `dedup_review_queue`.

### diff
Compare current `listing` row to previous version. Any change in tracked fields (`price`, `status`, `description` checksum, `photos` checksum, key features) writes a `listing_version` row.

## Scheduling (Celery Beat)

```python
beat_schedule = {
  'sreality-discover-praha-byty-prodej': {
    'task': 'ingest.discover',
    'schedule': crontab(minute=0, hour='*/6'),
    'args': ('sreality', {'region': 10, 'category_main': 1, 'category_type': 1}),
  },
  # ... per region/category/type/source combo
  'sreality-discover-full-sweep': {
    'task': 'ingest.discover_full',
    'schedule': crontab(minute=0, hour=2),
    'args': ('sreality',),
  },
  'analytics-market-stat': {
    'task': 'analytics.market_stat_rebuild',
    'schedule': crontab(minute=0, hour=3),
  },
  'analytics-score-all-active': {
    'task': 'analytics.score_all_active',
    'schedule': crontab(minute=0, hour=4),
  },
  'analytics-refresh-score-latest': {
    'task': 'analytics.refresh_score_latest',
    'schedule': crontab(minute=30, hour=4),
  },
  'notify-watchlists': {
    'task': 'notify.evaluate_watchlists',
    'schedule': crontab(minute=0, hour=6),
  },
  'source-canary': {
    'task': 'ops.source_canary_all',
    'schedule': crontab(minute=0, hour='*'),
  },
}
```

## Sreality specifics

### Endpoints (undocumented but stable)
```
GET https://www.sreality.cz/api/cs/v2/estates
    ?category_main_cb={1=byty|2=domy|3=pozemky|4=komercni|5=ostatni}
    &category_type_cb={1=prodej|2=pronajem|3=drazby}
    &locality_region_id={10=Praha|11=Stredocesky|...}
    &page=1&per_page=60
GET https://www.sreality.cz/api/cs/v2/estates/{hash_id}
```

### Discovery
- `hash_id` is the stable `source_listing_id`.
- Search response includes `price`, `locality`, `gps`, `last_modification`, thumbnail URLs.
- Diff `last_modification` against our `listing.updated_at` to decide whether to fetch detail.

### Detail parsing
- `items[]` is a list of `{name, value, type, unit}` pairs. Maintain an explicit key map:
  ```python
  SREALITY_ITEM_MAP = {
    "Užitná plocha": "usable_area_m2",
    "Plocha pozemku": "land_area_m2",
    "Stavba": "building_type",     # 'panel','cihla',...
    "Stav objektu": "condition",
    "Vlastnictví": "ownership_type",  # 'osobni','druzstevni','statni'
    "Energetická náročnost budovy": "energy_class",
    "Poschodí": "floor_text",         # parse '2. patro z 5' → 2, 5
    "Rok kolaudace": "year_built",
    # ... etc
  }
  ```
- `meta_description` and `name` give disposition and locality summary; parse with regex.
- `_embedded.images[]` for photo URLs.
- `text.value` for description body (HTML-stripped).

### Politeness
- 1 req/sec sustained, 3 req/sec burst.
- All bulk runs scheduled 02:00–06:00 Europe/Prague.
- `User-Agent` identifies app + contact email.
- On 429 or 503: back off to 0.2 req/sec for 30 min, alert.

### Risk
- Anti-bot can ramp at any time. Snapshot every payload. Be ready to switch to lower rate or pause.
- The undocumented API may change. Canary fetches a known stable `hash_id` hourly and checks parse output shape.

## Adding a second source (Bezrealitky)

Bezrealitky has a public GraphQL endpoint (used by their own SPA). Same SDK applies:
- `discover()` issues a GraphQL search query, paginated.
- `fetch()` issues `GetAdvert` query for detail.
- `parse()` maps the GraphQL response to `ParsedListing`.

The point of the SDK: adding Bezrealitky should not change anything in normalize/geocode/dedup/score.

## Data quality outputs
Every ingestion run writes counts to `source_run.stats_jsonb`:
- `discovered`, `fetched`, `parsed_ok`, `parsed_quarantine`
- `geocoded_rooftop`, `geocoded_street`, `geocoded_locality`
- `deduped_auto`, `dedup_review_queued`
- `field_completeness`: % of listings with each key field present

Dashboards alert on:
- Parse success rate drop > 10% (parser break)
- Field completeness drop > 10% (HTML change)
- Geocode rooftop rate drop > 10% (RÚIAN issue)
- Discovery count drop > 30% vs 7-day avg (source change or block)
