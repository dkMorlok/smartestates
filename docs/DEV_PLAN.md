# Development Plan

Eight weeks to MVP. Two engineers ideal; one engineer is feasible if you cut Phase-2 prep work.

Each week has: goal, tasks, exit criteria, hard truths.

---

## Week 1 — Foundation

**Goal:** infrastructure stands, one source ingests one listing end-to-end.

**Tasks**
- Repo init: monorepo with `apps/api`, `apps/web`, `services/worker`, `services/scraper`, `packages/shared`, `infra/compose`, `docs/`.
- CI: GitHub Actions for lint, type-check, test, image build.
- Docker Compose dev stack: Postgres 16 + PostGIS, Redis, MinIO, Mailhog.
- Alembic baseline migration with `source`, `source_run`, `raw_listing` (+ first month partition), `property`, `listing`, minimal scaffolding for the rest.
- `packages/shared`: pydantic models for `ParsedListing`, enums for `property_type`, `disposition`, `ownership_type`, `building_type`, `condition`, `energy_class`.
- Source SDK interface (`Source` protocol) and Sreality skeleton with one endpoint call.
- Sentry projects (api, worker, web).
- `/healthz` and `/readyz` on api.
- `make dev` brings everything up cleanly.

**Exit**
- One Sreality listing fetched, stored in S3, written to `raw_listing`.
- All services boot cleanly from `docker compose up`.

**Hard truths**
- This is the boring week. Don't skip it. The compounding cost of bad foundations is the most common reason these projects collapse at month 4.

---

## Week 2 — Sreality end-to-end

**Goal:** Praha byty prodej ingestion runs, parses, normalizes; data in `listing` table.

**Tasks**
- Sreality `discover()`: paginate `category_main=1, category_type=1, region=10`. Stop on empty page.
- `fetch()`: detail endpoint, raw JSON to S3, `raw_listing` row, content_hash dedup.
- `parse()`: pydantic `ParsedListing` with explicit `SREALITY_ITEM_MAP` for all known keys. Unknown keys logged.
- `normalize()`: upsert into `listing`, handle disposition parsing, ownership_type mapping, building_type mapping.
- Quarantine table for parse failures.
- Celery worker + beat configured; one scheduled run every 6h for Praha byty.
- Redis token-bucket rate limiter (1 rps).
- Basic Grafana dashboard with `source_run.stats_jsonb` counts.

**Exit**
- Praha byty prodej (~15k–20k listings) fully ingested.
- Parse success rate > 95%.
- Quarantine rate < 5%.
- Re-running ingestion is idempotent (no duplicate rows, content_hash skips unchanged).

**Hard truths**
- Sreality's items list will have edge cases (free-text values where you expected enums, missing fields, oddities). Don't fight them; quarantine and review.
- 20k listings is enough to find data-shape surprises. 200 is not.

---

## Week 3 — Geo + dedup tier 1

**Goal:** every listing has a point + property linkage; same-source duplicates collapsed.

**Tasks**
- Nominatim container, RÚIAN download script, seeding job.
- `geocode()` stage: prefer Sreality `gps` field, verify against RÚIAN, classify precision.
- `property` linking: RÚIAN address code → existing; else `ST_DWithin` + normalized address.
- Dedup tier 1: same `(source_id, source_listing_id)` is impossible by UNIQUE; cluster by RÚIAN code + size + disposition + ownership_type.
- Photo records: store URL + width/height. No phash yet (Phase 2).
- Address normalization utility (diacritics, abbreviations, postcode → district fallback).

**Exit**
- ≥ 95% listings geocoded at street precision or better.
- ≥ 80% rooftop.
- `property` count: ~70–80% of listing count (some buildings have multiple flats).
- Dedup auto-cluster rate measured and documented.

**Hard truths**
- RÚIAN setup will take longer than you think. Budget a full day for the loader script.
- Some Sreality listings have `gps` outside their stated locality. Don't trust blindly — validate.

---

## Week 4 — Web skeleton

**Goal:** users can search, filter, see properties on a map, open a detail page.

**Tasks**
- Next.js app: App Router, shadcn/ui base components, Tailwind config.
- `/search` page: split view, table + map, URL-encoded filters.
- TanStack Query for fetching, TanStack Table virtualized.
- MapLibre GL JS, Protomaps tiles (or MapTiler dev).
- API endpoints: `GET /v1/listings`, `GET /v1/listings/{id}`, `GET /v1/map/listings`.
- Filter chips: city_district, disposition, ownership_type, price range, size range.
- Property detail page: photos, key facts, map, raw description, source link.
- Czech locale: number formatting, date formatting, all strings.

**Exit**
- Load `/search`, filter to "Praha 5, 2+kk, osobni", see ~50 results in table and on map.
- Click row → side panel with detail.
- Filter state survives reload.
- Mobile-responsive enough to be usable (not yet polished).

**Hard truths**
- Map clustering will fight you. Start with simple server-side `ST_ClusterDBSCAN`; don't try fancy client clustering.
- Don't decorate. Table-first. No hero, no marketing copy.

---

## Week 5 — Market stats + scoring v1

**Goal:** every active listing has a score with components and confidence.

**Tasks**
- `market_segment` definition + materialization job for Praha (one segment per district × disposition × ownership × building_type × size_bucket × condition_bucket).
- Nightly `market_stat` job computes ppm² stats per segment from active listings within 90 days.
- Segment relaxation hierarchy.
- Hedonic regression: fit per (city, property_type, ownership_type) using statsmodels Huber regressor.
- `score` job: per active listing, compute residual, undervaluation_pct, risk_flags, confidence, composite.
- `score_latest` materialized view.
- Property detail: score panel with components, risk flags, market histogram showing this listing's position.
- API: `GET /v1/listings/{id}/score`, `GET /v1/markets/{segment_id}/stats`.

**Exit**
- ≥ 90% of active Praha listings have a score with confidence ≥ 0.5.
- Top 50 "undervalued" listings reviewed manually; obvious false positives understood and risk-flagged.
- Score job completes in < 10 minutes.

**Hard truths**
- The first version of the regression will surface a lot of noise. That's fine — the architecture supports versioning, ship v1, learn, ship v2.
- Manual review of the top 50 is non-negotiable. Without it you ship the družstevní bug.

---

## Week 6 — Listing history, comparables, data quality

**Goal:** users can see how a listing's price moved and what's comparable; ops can see data health.

**Tasks**
- `diff` stage: compute `fields_changed` per listing on each re-ingest, write `listing_version`.
- Price-history sparkline on property detail.
- Comparables endpoint: nearest 20 listings by segment + distance.
- Data quality dashboard (Grafana): field completeness, geocode precision distribution, parse quarantine rate, dedup auto-rate, score confidence distribution.
- Source canary job (hourly) for Sreality.
- Replay tooling: rerun parser version X over raw_listing range Y.

**Exit**
- Detail page shows price history when changes have been observed.
- Comparables visible and sensible.
- Data quality dashboard live, alerts wired.

**Hard truths**
- You won't have much price-history yet (only 5 weeks of data). The feature is structurally there; data will fill in.

---

## Week 7 — Second source (Bezrealitky)

**Goal:** Bezrealitky listings ingested through the same SDK, dedup'd against Sreality.

**Tasks**
- Bezrealitky source module: GraphQL discovery + detail.
- Item mapping to canonical fields.
- Cross-source dedup tier 2: same RÚIAN code + price within ±5%.
- Photo phash for tier 3 dedup (defer the matching threshold tuning; just compute and store).
- Admin: source health page, recent runs page.
- Soft launch internal: invite 5–10 friendly users for a week.

**Exit**
- Bezrealitky ingestion stable for ≥ 3 days.
- Dedup catches most obvious cross-source duplicates (manually verify on 50 samples).
- No regressions to Sreality pipeline.

**Hard truths**
- This week's biggest value is validating the SDK abstraction. If adding Bezrealitky requires changes outside `services/scraper/sources/bezrealitky/`, refactor.

---

## Week 8 — Hardening, polish, soft launch

**Goal:** ship to a small public group.

**Tasks**
- Backup script + monthly restore drill scheduled.
- Rate-limit on API endpoints.
- nginx + TLS in front (Caddy).
- Production VPS provisioned, deployment workflow tested twice.
- Sentry release tagging, source maps for frontend.
- Privacy policy, terms of service, contact page.
- Runbooks for the top 5 paging alerts.
- Soft launch to 20–50 users, feedback channel (email or simple form).

**Exit**
- Production live for one week without paging incidents.
- Backup restore drill passes.
- First batch of user feedback collected.

**Hard truths**
- Half of what you ship in week 8 will be paperwork (privacy policy, terms, GDPR contact). Don't skip — without it you're legally exposed.
- The product will look unfinished. That's correct. Polish in Phase 2.

---

## Standing rules across all weeks

- Every PR: ≥ 1 test for happy path, ≥ 1 test for an error case.
- No PR merges to `main` without CI green.
- Migrations reviewed line-by-line; never rewrite a shipped migration.
- `docs/` updated in the same PR that changes behavior.
- One source = one folder = one set of tests. Source modules are pluggable, the core is not.
- 20–30% of time reserved for unplanned maintenance (parser breakage, ops fires). Don't fill it with features.
- End-of-week 30-minute review: what broke, what surprised, what to cut from next week.

## Team setup if one engineer
Cut weeks 6 and 7 by half. Defer cross-source dedup to Phase 2. Ship a single-source MVP at week 8 with Sreality only, then add Bezrealitky as week 9–10.

## Team setup if three+ engineers
Don't. At this stage three people on a greenfield project means coordination overhead exceeds output. Hire when the MVP is shipped and validated.
