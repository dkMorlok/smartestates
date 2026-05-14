# Architecture

## Principles
- **Boring tech.** Postgres, Redis, Python, Next.js. No exotic infra.
- **Scrapers never write to canonical tables.** Raw → normalize → canonical, always.
- **Scoring is offline and versioned.** Never computed on request.
- **Single VPS, Docker Compose, until forced off.** No Kubernetes until usage demands it.
- **Observability from day one.** Sentry + Prometheus + structured logs.

## Services

```
┌──────────────┐        ┌──────────────┐
│   web        │  ────► │   api        │
│  Next.js     │        │  FastAPI     │
└──────────────┘        └──────┬───────┘
                               │
                       ┌───────┴────────┐
                       │                │
                  ┌────▼────┐      ┌────▼─────┐
                  │ postgres│      │  redis   │
                  │ +PostGIS│      │ broker+  │
                  │         │      │ cache    │
                  └────▲────┘      └────▲─────┘
                       │                │
        ┌──────────────┼────────────────┤
        │              │                │
┌───────┴──────┐ ┌─────┴───────┐ ┌──────┴────────┐
│ worker-      │ │ worker-     │ │  scheduler    │
│ ingest       │ │ analytics   │ │  (celery beat)│
│ (scrapers)   │ │ (scoring,   │ │               │
│              │ │  market     │ │               │
│              │ │  stats,     │ │               │
│              │ │  dedup)     │ │               │
└───────┬──────┘ └─────────────┘ └───────────────┘
        │
   ┌────▼─────┐    ┌──────────────┐
   │ s3 / r2  │    │  geocoder    │
   │ raw html,│    │ Nominatim+   │
   │ photos   │    │  RÚIAN       │
   └──────────┘    └──────────────┘
```

### `api` (FastAPI)
Read-heavy. Serves the web app and admin UI. No business logic that belongs in workers. Talks to Postgres (read replica when we have one) and Redis (cache). Stateless, horizontally scalable behind a reverse proxy.

### `web` (Next.js App Router)
SSR for SEO-relevant pages (listing detail, market pages). Client-side for map and filters. TanStack Query for fetching, URL-encoded state for shareable filters.

### `worker-ingest` (Celery)
Runs scraper jobs. Network-bound, bursty, frequently fails. Scaled separately from analytics. Strict per-source rate limits via Redis token buckets. Writes to `raw_listing` and S3, never to canonical tables.

### `worker-analytics` (Celery)
Normalization, dedup, geocoding, market stats, scoring. CPU-bound, predictable. Reads `raw_listing`, writes `listing`, `property`, `score`, `market_stat`.

### `scheduler` (Celery Beat)
Single instance, single container. Enqueues periodic jobs. Idempotency in job handlers prevents double-execution if it ever restarts mid-tick.

### `postgres` + PostGIS
Single primary. Add async read replica when API read load justifies it. PITR via WAL archiving to S3. Partition `raw_listing` and `listing_version` by month.

### `redis`
Three logical DBs: `0` broker, `1` cache, `2` rate-limit token buckets. Persistence on (AOF). Not the source of truth for anything.

### `geocoder`
Self-hosted Nominatim seeded with RÚIAN + OSM. Reverse proxy in front for caching. Address-string → point with precision label. See `GEO.md`.

### Object store
S3 / Cloudflare R2 in production, MinIO locally. Stores raw HTML/JSON snapshots, photo thumbnails, model artifacts, DB dumps. Lifecycle policies: raw HTML expires after 90 days unless flagged for replay.

## Request flow (read)
1. Browser → `web` (Next.js)
2. `web` → `api` for data (server components or client `fetch`)
3. `api` checks Redis cache; on miss queries Postgres
4. `api` returns JSON with `model_version` and pagination cursor
5. `web` renders, client takes over interactivity

## Job flow (ingest)
1. Beat enqueues `ingest.discover(source=sreality, params=...)`
2. Worker fetches search-result pages, emits `ingest.fetch(source, listing_id)` per new/changed listing
3. `ingest.fetch` retrieves detail JSON, stores raw payload in S3, writes `raw_listing` row
4. `ingest.parse` validates with pydantic, writes parsed JSON
5. `normalize` upserts into `listing`, links to `property`
6. `geocode` resolves address, links/creates `property` with PostGIS point
7. `dedup` clusters across sources
8. `diff` writes `listing_version` row on field changes
9. Nightly `market_stat` recomputes segment statistics
10. Nightly `score` runs hedonic regression and writes per-listing scores
11. `notify` evaluates watchlists and sends alerts

## Deployment
- **Production:** Hetzner CX42 or similar (~16GB RAM, 4 vCPU, NVMe). Docker Compose. nginx in front (TLS via certbot or Caddy).
- **Staging:** identical, smaller box.
- **Dev:** local Docker Compose with MinIO and bundled Nominatim.

CI/CD: GitHub Actions → build images → push to GHCR → SSH deploy script pulls and `docker compose up -d`. No fancy orchestration. Database migrations run as a one-shot container before app containers restart.

## Scaling triggers (don't pre-optimize)
| Symptom | Move |
|---|---|
| API p95 > 500ms sustained | Add read replica |
| Worker queue depth > 10k for > 30 min | Add ingest workers |
| Postgres CPU > 70% sustained | Tune queries first, then scale up, then partition |
| Disk > 70% | Lifecycle raw HTML to glacier-class storage |
| > 5 sources, > 100k active listings | Consider splitting worker-ingest per source class |

## What we explicitly are NOT doing yet
- Kubernetes / k3s
- Multi-region
- gRPC between services (HTTP/JSON is fine)
- A message broker beyond Redis (no Kafka, no RabbitMQ)
- Microservices beyond the four above
- A separate "ML platform"
