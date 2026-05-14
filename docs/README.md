# Realitní Skener (working name)

Find undervalued real estate investment opportunities in the Czech Republic by aggregating listings, comparing them against market segments, and scoring investment attractiveness.

## Status
Pre-MVP. Single-country (CZ), single-source first (Sreality), single-city focus (Praha) for v0.

## Stack
- **Backend:** Python 3.12, FastAPI, Celery, SQLAlchemy, Alembic
- **Frontend:** Next.js 14 (App Router), TypeScript, shadcn/ui, MapLibre GL JS, TanStack Query/Table
- **DB:** PostgreSQL 16 + PostGIS
- **Queue/cache:** Redis
- **Object store:** S3-compatible (R2 / MinIO local)
- **Geocoder:** Self-hosted Nominatim seeded with RÚIAN
- **Deployment:** Docker Compose on a single VPS until forced off

## Repo layout
```
apps/
  api/          FastAPI service
  web/          Next.js app
services/
  worker/       Celery workers + beat
  scraper/      Source SDK + per-source modules
packages/
  shared/       Pydantic models, enums, constants
infra/
  compose/      docker-compose files
  migrations/   Alembic
docs/           This directory
```

## Documents
| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | Services, deployment, request flow |
| `DATA_MODEL.md` | Schema, tables, indexes |
| `INGESTION.md` | Scraper SDK, Sreality specifics, pipeline |
| `SCORING.md` | Scoring model, hedonic regression, components |
| `GEO.md` | Geocoding, RÚIAN, map strategy |
| `API.md` | Endpoints, auth, pagination |
| `UI.md` | Pages, components, UX rules |
| `OPERATIONS.md` | Monitoring, backups, deploys, on-call |
| `ROADMAP.md` | MVP scope and phased plan |
| `RISKS.md` | Legal, technical, data-quality risks |
| `DEV_PLAN.md` | Week-by-week build plan |
| `CZ_NOTES.md` | Czech-specific gotchas (read this first) |

## First commands
```bash
# Bring up dev stack
docker compose -f infra/compose/dev.yml up -d

# Migrate
docker compose exec api alembic upgrade head

# Seed RÚIAN into geocoder
docker compose exec scraper python -m scripts.seed_ruian

# Trigger one Sreality discovery run for Praha byty
docker compose exec worker celery -A worker call ingest.discover \
  --args='["sreality", {"region": 10, "category_main": 1, "category_type": 1}]'
```

## Non-goals (for now)
- Multi-country
- Mobile native apps
- Public API for third parties
- ML-only scoring (rule-based + hedonic regression first)
- Real-time alerts (< 1 hour latency)
