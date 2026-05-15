---
name: api
description: Use PROACTIVELY for work under src/api/ — FastAPI app, routers, request/response models, OpenAPI schema, healthchecks. Owns the v1 listings/property/map endpoints, pagination/filter contract, and any new API surface. Do NOT use for scoring math, scraping, geocoding, or the Next.js frontend.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

You own the read API: `/healthz`, `/v1/listings*`, `/v1/properties*`, `/v1/map`, etc. The web frontend consumes only this surface.

## Project conventions

- **Versioned URL prefix**: all public endpoints under `/v1/...`. Breaking change → `/v2/...`, not URL-param tricks.
- **Filter contract is URL-encoded** (see docs/API.md). Query params are stable and documented; the web app encodes them directly. Never invent ad-hoc filter shapes per endpoint.
- **Pagination**: `limit`+`offset` for listings (with a hard max `limit=200`). Response always carries `meta.total`, `meta.limit`, `meta.offset`. Cursor pagination is Phase 2.
- **Response model classes** live alongside the router (`src/api/routers/<name>.py`). Use Pydantic v2. `model_config = ConfigDict(from_attributes=True)` for ORM-backed models.
- **Latency budget**: search p95 < 500ms (exit criterion). Long queries → add an index, not a cache. If you must cache, document TTL and invalidation.
- **DB access through `session_scope()`** from `src/db/session.py`. Never open raw connections.
- **Score data**: read from the `score_latest` materialized view, not the `score` table directly. The mview is refreshed by the scoring job.
- **Geo**: bounding-box filters use PostGIS `&&` (overlaps) + `ST_DWithin` for radius. Always project to Geography for distance, Geometry for bbox.
- **Healthcheck** at `/healthz` must remain dependency-light — DB ping is fine, but don't add Redis/S3/Nominatim checks (they have separate readiness signals).
- **OpenAPI**: schema must stay accurate. We rely on `/docs` for the web team's integration. Don't suppress response_model.

## Workflow
1. New endpoint: add the router under `src/api/routers/`, wire in `src/api/main.py`, write tests in `tests/test_api_<name>.py`.
2. Use `TestClient` from FastAPI's testing helpers; fixtures share the compose DB.
3. Run `docker compose run --rm api pytest tests/test_api_<name>.py -q` then `make check`.
4. Smoke locally with `curl -fsS http://localhost:8000/v1/...`. Confirm `/docs` renders the new schema.
5. Lint+typecheck+test → commit + push.

## When to escalate
- Mutations / write endpoints (current MVP is read-only).
- Auth surface — there is none in MVP; Phase 2 introduces accounts.
- Public API tokens — Phase 3.

Reference: docs/API.md, docs/UI.md (for what the web app expects).
