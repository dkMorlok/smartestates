# Realitní Skener

Find undervalued real estate investment opportunities in the Czech Republic.

Architectural and product docs live in `docs/`. **Read `docs/CZ_NOTES.md` first** — it covers Czech-specific traps (especially the družstevní-vs-osobní ownership trap) you'll hit immediately if you skip it.

## Status

Weeks 1–3:
- Dev stack via Docker Compose (Postgres+PostGIS, Redis, MinIO; optional Nominatim)
- Postgres schema (Alembic baseline) for source / raw / canonical / scoring layers
- Shared pydantic schemas + CZ-specific normalization (disposition, ownership, building type, condition, energy class, floor, address)
- Source SDK + Sreality module (discover/fetch/parse against the JSON endpoints)
- Celery worker + beat with rate-limited pipeline: discover → fetch → parse → normalize → geocode → dedup
- Geocode stage: source-GPS verified against locality bbox, optional Nominatim enrichment, property linking (RÚIAN / spatial proximity)
- Dedup tier 1: same-source duplicates collapsed per property
- FastAPI app with `/healthz`, `/readyz`, `/v1/listings`
- Tests covering CZ normalization, Sreality parsing, geocoding, dedup
- CI on GitHub Actions

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Celery · Redis · Postgres 16 + PostGIS · httpx · pydantic v2 · pytest · ruff · mypy

## Quick start

```bash
cp .env.example .env
make build
make up
make migrate
```

Then:

- API:    http://localhost:8000/healthz
- API:    http://localhost:8000/v1/listings
- MinIO:  http://localhost:9001 (minioadmin / minioadmin)
- Postgres: `make psql`
- Logs:   `make logs`

## Trigger a Sreality discovery run

```bash
make sreality-discover-praha
```

This enqueues one `ingest.discover` task for Praha byty prodej. The worker
will paginate the Sreality search endpoint, snapshot raw payloads to MinIO,
parse, validate, normalize, and upsert into `listing`. The beat schedule runs
the same job every 6 hours automatically.

## Project layout

```
.
├── docs/                          architectural + product docs
├── src/
│   ├── shared/                    config, enums, schemas, normalization, logging
│   ├── db/                        SQLAlchemy ORM + session factory
│   ├── api/                       FastAPI app and routers
│   ├── scraper/                   Source SDK + per-source modules
│   │   ├── base.py                Source protocol + registry
│   │   ├── http.py                shared httpx + retry
│   │   ├── ratelimit.py           Redis token bucket
│   │   ├── storage.py             S3 raw-payload storage
│   │   └── sources/sreality/      Sreality source implementation
│   └── worker/                    Celery app + tasks
│       ├── celery_app.py          queue routing + beat schedule
│       └── tasks/                 ingest, normalize, ops
├── migrations/                    Alembic
├── tests/                         pytest suite
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── pyproject.toml
└── Makefile
```

## Development

```bash
make test              # pytest
make lint              # ruff
make typecheck         # mypy
make check             # all three
make format            # ruff format
make revision m="add foo"  # new alembic migration
```

## What's next

See `docs/DEV_PLAN.md` for the week-by-week plan. Week 2 focuses on the
Sreality full-region sweep and parse robustness; Week 3 brings in Nominatim
+ RÚIAN and dedup. Don't add a second source until Sreality runs cleanly
for a week without manual intervention.

## License

TBD.
