# Operations

## Environments
- **dev** — local Docker Compose, MinIO, bundled Nominatim, synthetic data fixtures.
- **staging** — small VPS, real sources at low rate, ephemeral data.
- **prod** — Hetzner CX42 or equivalent, daily backups, on-call.

## Deployment

### Topology (prod, single VPS)
```
nginx (TLS, Caddy alternative)
  ├── web        (Next.js, port 3000)
  ├── api        (FastAPI, port 8000)
  ├── worker-ingest
  ├── worker-analytics
  ├── scheduler  (Celery Beat, single instance)
  ├── postgres   (Postgres 16 + PostGIS)
  ├── redis
  ├── nominatim
  └── minio (or external R2)
```

### Process
1. Push to `main` → GitHub Actions builds and tags images, pushes to GHCR.
2. Tag a release → triggers deploy workflow.
3. Deploy workflow SSHes to prod, runs:
   - `docker compose pull`
   - `docker compose run --rm api alembic upgrade head` (one-shot migrations)
   - `docker compose up -d` (rolling on web/api/workers)
4. Health check probes `/healthz` on api and `/api/healthz` on web.
5. On failure, rollback script repins previous image tags.

Blue/green is not worth it at this scale. Migrations are written backward-compatible (add columns nullable, deploy, backfill, then NOT NULL in a later migration).

## Healthchecks

### Service-level
- `GET /healthz` → 200 if process alive.
- `GET /readyz` → 200 if DB, Redis, S3 reachable; else 503.
- Workers: heartbeat via Celery, monitored by Flower or custom.

### Data-level (run hourly)
- Per-source canary: fetch a known stable listing, parse, compare field count to baseline. Alert if drop > 20%.
- Active-listing count per source vs 7-day rolling avg. Alert if drop > 30%.
- Geocode rooftop rate vs 7-day rolling avg. Alert if drop > 10%.
- Score job last-run timestamp. Alert if > 28h ago.

## Monitoring

### Errors
**Sentry** for backend (api, workers) and frontend (web). Separate projects per service. PII scrubbed (no emails, no IPs in event payloads).

### Metrics
**Prometheus** + **Grafana**. Exposed by api and workers via `/metrics`.

Key metrics:
- `http_requests_total{method,route,status}`
- `http_request_duration_seconds` (histogram)
- `celery_jobs_total{queue,task,status}`
- `celery_jobs_duration_seconds`
- `celery_queue_depth{queue}`
- `ingest_listings_total{source,stage,status}`
- `ingest_fetch_duration_seconds{source}`
- `geocode_requests_total{precision,cache_hit}`
- `dedup_clusters_total{method}`
- `score_run_duration_seconds`
- `db_connections_active`
- `redis_memory_bytes`

### Dashboards
- **Ops overview:** service uptime, error rates, queue depths.
- **Ingestion:** per-source success rates, listings/hour, parse quarantine rate.
- **Data quality:** field completeness, geocode precision, dedup auto-rate.
- **DB:** slow queries, lock waits, replication lag (when applicable).
- **Business:** active listings, new today, top scores, watchlist activity.

### Logs
**Loki** (or Grafana Cloud free tier early on). Structured JSON. Correlation IDs propagate from HTTP request → enqueued job → downstream jobs. Retention 14 days hot, 90 days cold.

### Alerts (Alertmanager or Grafana OnCall)

Paging:
- API 5xx rate > 1% over 5 min.
- API p95 latency > 1s over 10 min.
- Any source success rate < 80% over 1 hour.
- Queue depth > 10,000 for > 30 min.
- DB connections > 90% of pool for > 5 min.
- Daily backup failed.
- Disk > 85%.

Email/Slack only:
- Parser extraction rate drop > 10%.
- Field completeness drop > 10%.
- Spike in `parse_quarantine` rows.
- Score run took > 2× p95.

## Backups
- `pg_dump` nightly to S3, 30-day retention, encrypted at rest.
- Continuous WAL archiving for PITR, 7-day window.
- Test restore monthly into staging from latest dump.
- S3 bucket lifecycle: raw HTML > 90d → glacier; backups > 90d → glacier; both > 1y → delete.
- Configuration (compose files, nginx config, alembic versions) versioned in git.

## Secrets
- Stored in a secrets manager (Doppler, 1Password Connect, or sops+age in git for early stage).
- Never in `.env` files committed to git.
- Rotated quarterly: DB password, Redis password, S3 keys, SMTP credentials, Sentry DSN (low-risk).
- App-level encryption for any PII at rest beyond auth credentials.

## Security
- TLS everywhere via Caddy auto-cert or Let's Encrypt.
- nginx in front: WAF rules, rate-limit on auth endpoints, IP allowlist for admin paths in early stage.
- Postgres not exposed publicly; bound to docker network.
- Redis password-protected, not on public interface.
- Dependabot / Renovate for dependency PRs.
- CSP, HSTS, X-Content-Type-Options set on web responses.
- Argon2id for password hashing.
- Session cookies HttpOnly, Secure, SameSite=Lax.
- Admin endpoints require MFA when added (Phase 2).
- Audit log writes for any admin action.

## On-call (when team > 1)
- One primary, one secondary, weekly rotation.
- Pager: PagerDuty free tier or Grafana OnCall.
- Runbooks in `docs/runbooks/` for each paging alert.
- Postmortem mandatory for any user-facing incident > 15 min.

## Runbooks (skeleton, expand later)
- `sreality-blocked.md` — Sreality returning 429/403
- `parser-broken.md` — parse extraction rate dropped
- `geocoder-down.md` — Nominatim unreachable
- `db-disk-full.md` — Postgres disk pressure
- `queue-overflow.md` — Celery queue depth alert
- `bad-deploy-rollback.md` — rollback procedure

## Cost ceilings (rough)
At MVP scale (50k active listings, < 100 users):
- VPS: ~€60/month
- S3/R2: ~€10/month
- Domain + email: ~€5/month
- Sentry: free tier
- Grafana Cloud: free tier
- Geocoder tiles: Protomaps self-host or MapTiler ~€30/month
- **Total ~€100–150/month.** Don't over-engineer for scale we don't have.
