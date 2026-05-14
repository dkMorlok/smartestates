# Data Model

## Design rules
- **Three layers:** `raw_*` (immutable, source of truth from scrapers), canonical (`listing`, `property`), derived (`market_stat`, `score`).
- **Never `UPDATE` raw data.** Append-only, partitioned by month.
- **Property ≠ Listing.** A property is the physical asset; multiple listings (across time, sources, agencies) link to one property.
- **Every derived row has a `model_version`** so we can roll back scoring changes.

## Tables

### Sources & runs

```sql
CREATE TABLE source (
  id            SERIAL PRIMARY KEY,
  slug          TEXT UNIQUE NOT NULL,         -- 'sreality', 'bezrealitky'
  kind          TEXT NOT NULL,                -- 'json_api', 'html', 'feed'
  base_url      TEXT NOT NULL,
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  rate_limit_rps NUMERIC NOT NULL DEFAULT 1.0,
  config_jsonb  JSONB NOT NULL DEFAULT '{}',
  health        TEXT NOT NULL DEFAULT 'unknown', -- ok/degraded/down
  last_ok_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_run (
  id          BIGSERIAL PRIMARY KEY,
  source_id   INT REFERENCES source(id),
  stage       TEXT NOT NULL,                  -- 'discover','fetch','parse'
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status      TEXT NOT NULL,                  -- running/ok/failed
  stats_jsonb JSONB NOT NULL DEFAULT '{}',
  error_text  TEXT
);
```

### Raw layer

```sql
CREATE TABLE raw_listing (
  id                BIGSERIAL,
  source_id         INT NOT NULL REFERENCES source(id),
  source_listing_id TEXT NOT NULL,
  fetched_at        TIMESTAMPTZ NOT NULL,
  url               TEXT NOT NULL,
  http_status       INT,
  content_hash      TEXT NOT NULL,             -- sha256 of raw payload
  raw_s3_key        TEXT NOT NULL,             -- where the JSON/HTML lives
  parsed_jsonb      JSONB,
  parser_version    TEXT,
  parse_status      TEXT,                      -- ok/quarantine/failed
  parse_error       TEXT,
  PRIMARY KEY (id, fetched_at)
) PARTITION BY RANGE (fetched_at);

-- partitions per month, created by migration job
CREATE INDEX ON raw_listing (source_id, source_listing_id, fetched_at DESC);
CREATE INDEX ON raw_listing (content_hash);
```

### Canonical layer

```sql
CREATE TABLE property (
  id                    BIGSERIAL PRIMARY KEY,
  geom                  geography(Point, 4326),
  address_normalized    TEXT,
  address_precision     TEXT NOT NULL,         -- rooftop/parcel/street/locality
  country               CHAR(2) NOT NULL DEFAULT 'CZ',
  admin1                TEXT,                  -- kraj
  admin2                TEXT,                  -- okres
  locality              TEXT,                  -- obec
  city_district         TEXT,                  -- městská část
  cadastral_area        TEXT,                  -- katastrální území
  postcode              TEXT,
  ruian_address_code    TEXT UNIQUE,           -- CZ official address ID
  ruian_building_code   TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON property USING GIST (geom);
CREATE INDEX ON property (ruian_address_code);
CREATE INDEX ON property (city_district, locality);

CREATE TABLE listing (
  id                BIGSERIAL PRIMARY KEY,
  property_id       BIGINT REFERENCES property(id),
  source_id         INT NOT NULL REFERENCES source(id),
  source_listing_id TEXT NOT NULL,
  canonical_url     TEXT NOT NULL,
  first_seen_at     TIMESTAMPTZ NOT NULL,
  last_seen_at      TIMESTAMPTZ NOT NULL,
  status            TEXT NOT NULL,             -- active/withdrawn/sold/unknown

  -- pricing
  price             NUMERIC,
  currency          CHAR(3) NOT NULL DEFAULT 'CZK',
  price_hidden      BOOLEAN NOT NULL DEFAULT FALSE,
  price_per_m2      NUMERIC GENERATED ALWAYS AS
                      (CASE WHEN size_m2 > 0 THEN price/size_m2 END) STORED,

  -- physical
  size_m2           NUMERIC,
  usable_area_m2    NUMERIC,
  land_area_m2      NUMERIC,
  rooms             INT,
  bathrooms         INT,
  floor_current     INT,
  floor_total       INT,
  year_built        INT,

  -- CZ-specific (see CZ_NOTES.md)
  property_type     TEXT NOT NULL,             -- byt/dum/pozemek/komercni/...
  disposition       TEXT,                      -- 1+kk, 2+1, etc.
  ownership_type    TEXT,                      -- osobni/druzstevni/statni
  building_type     TEXT,                      -- panel/cihla/smisena/drevo
  condition         TEXT,                      -- novostavba/velmi_dobry/...
  energy_class      CHAR(1),                   -- A..G

  -- features as JSONB for flexibility
  features_jsonb    JSONB NOT NULL DEFAULT '{}',
   -- {has_balcony, has_loggia, has_terrace, has_cellar, has_lift,
   --  has_parking, has_garage, has_garden, furnished, ...}

  description       TEXT,
  agency            TEXT,
  agent_name        TEXT,
  is_owner_direct   BOOLEAN,

  -- dedup
  dedup_cluster_id  BIGINT,

  -- bookkeeping
  raw_listing_id    BIGINT,                    -- last raw row that produced this
  parser_version    TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (source_id, source_listing_id)
);

CREATE INDEX ON listing (status, price) WHERE status = 'active';
CREATE INDEX ON listing (property_id);
CREATE INDEX ON listing (dedup_cluster_id);
CREATE INDEX ON listing (property_type, ownership_type, disposition);
CREATE INDEX ON listing (last_seen_at DESC);
```

### History

```sql
CREATE TABLE listing_version (
  id              BIGSERIAL,
  listing_id      BIGINT NOT NULL REFERENCES listing(id),
  observed_at     TIMESTAMPTZ NOT NULL,
  price           NUMERIC,
  status          TEXT,
  fields_changed  JSONB NOT NULL,              -- {field: [old, new]}
  PRIMARY KEY (id, observed_at)
) PARTITION BY RANGE (observed_at);

CREATE INDEX ON listing_version (listing_id, observed_at DESC);
```

### Photos

```sql
CREATE TABLE photo (
  id          BIGSERIAL PRIMARY KEY,
  listing_id  BIGINT NOT NULL REFERENCES listing(id) ON DELETE CASCADE,
  ord         INT NOT NULL,
  url_source  TEXT NOT NULL,                   -- hotlink original
  phash       BIT(64),                         -- perceptual hash for dedup
  s3_thumb_key TEXT,                           -- our 400px thumbnail
  width       INT,
  height      INT,
  UNIQUE (listing_id, ord)
);
CREATE INDEX ON photo USING hash (phash);
```

### Dedup

```sql
CREATE TABLE dedup_cluster (
  id                    BIGSERIAL PRIMARY KEY,
  canonical_listing_id  BIGINT REFERENCES listing(id),
  method                TEXT NOT NULL,         -- 'ruian_exact','fuzzy','manual'
  confidence            NUMERIC,               -- 0..1
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by           TEXT,
  reviewed_at           TIMESTAMPTZ
);

CREATE TABLE dedup_review_queue (
  id              BIGSERIAL PRIMARY KEY,
  listing_a_id    BIGINT NOT NULL REFERENCES listing(id),
  listing_b_id    BIGINT NOT NULL REFERENCES listing(id),
  signals_jsonb   JSONB NOT NULL,              -- which heuristics matched
  status          TEXT NOT NULL DEFAULT 'pending', -- pending/merged/rejected
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Market segments & stats

```sql
CREATE TABLE market_segment (
  id              BIGSERIAL PRIMARY KEY,
  city_district   TEXT,
  locality        TEXT,
  property_type   TEXT NOT NULL,
  disposition     TEXT,
  ownership_type  TEXT,
  building_type   TEXT,
  size_bucket     TEXT NOT NULL,               -- e.g. '40-60'
  condition_bucket TEXT,
  geom            geography(Polygon, 4326),
  UNIQUE (city_district, locality, property_type, disposition,
          ownership_type, building_type, size_bucket, condition_bucket)
);
CREATE INDEX ON market_segment USING GIST (geom);

CREATE TABLE market_stat (
  segment_id          BIGINT NOT NULL REFERENCES market_segment(id),
  as_of_date          DATE NOT NULL,
  n_samples           INT NOT NULL,
  ppm2_median         NUMERIC,
  ppm2_trimmed_mean   NUMERIC,
  ppm2_p25            NUMERIC,
  ppm2_p75            NUMERIC,
  ppm2_stddev         NUMERIC,
  dom_median_days     NUMERIC,                  -- days on market
  rent_ppm2_median    NUMERIC,                  -- monthly rent / m²
  relaxation_level    INT NOT NULL DEFAULT 0,   -- 0=exact, 1=widened, ...
  PRIMARY KEY (segment_id, as_of_date)
);
```

### Scoring

```sql
CREATE TABLE score (
  listing_id           BIGINT NOT NULL REFERENCES listing(id),
  model_version        TEXT NOT NULL,
  computed_at          TIMESTAMPTZ NOT NULL,
  segment_id           BIGINT REFERENCES market_segment(id),

  undervaluation_pct   NUMERIC,                 -- residual vs hedonic prediction
  undervaluation_abs   NUMERIC,                 -- CZK
  yield_gross_pct      NUMERIC,
  yield_confidence     NUMERIC,                 -- 0..1
  liquidity_score      NUMERIC,                 -- 0..100
  location_score       NUMERIC,
  risk_score           NUMERIC,
  confidence_score     NUMERIC,
  composite            NUMERIC,                 -- 0..100

  components_jsonb     JSONB NOT NULL,          -- full breakdown
  risk_flags           TEXT[],

  PRIMARY KEY (listing_id, model_version, computed_at)
);

CREATE INDEX ON score (listing_id, computed_at DESC);
CREATE INDEX ON score (composite DESC) WHERE computed_at > now() - interval '7 days';

-- latest-score materialized view for fast list queries
CREATE MATERIALIZED VIEW score_latest AS
SELECT DISTINCT ON (listing_id) *
FROM score
ORDER BY listing_id, computed_at DESC;
CREATE UNIQUE INDEX ON score_latest (listing_id);
```

### Geo layers (PostGIS)

```sql
CREATE TABLE flood_zone (
  id      SERIAL PRIMARY KEY,
  kind    TEXT,                                 -- 'Q5','Q20','Q100','Q500'
  geom    geography(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ON flood_zone USING GIST (geom);

CREATE TABLE transit_stop (
  id      SERIAL PRIMARY KEY,
  kind    TEXT,                                 -- 'metro','tram','bus','train'
  name    TEXT,
  line    TEXT,
  geom    geography(Point, 4326) NOT NULL
);
CREATE INDEX ON transit_stop USING GIST (geom);

CREATE TABLE poi (
  id      SERIAL PRIMARY KEY,
  kind    TEXT,                                 -- 'school','park','grocery',...
  source  TEXT,                                 -- 'osm','manual'
  name    TEXT,
  geom    geography(Point, 4326) NOT NULL,
  tags_jsonb JSONB
);
CREATE INDEX ON poi USING GIST (geom);
CREATE INDEX ON poi (kind);
```

### Users, watchlists, alerts

```sql
CREATE TABLE app_user (
  id            BIGSERIAL PRIMARY KEY,
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT,
  display_name  TEXT,
  role          TEXT NOT NULL DEFAULT 'user',   -- user/admin
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

CREATE TABLE watchlist (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  criteria_jsonb JSONB NOT NULL,                -- filter spec
  notify_email  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alert_event (
  id            BIGSERIAL PRIMARY KEY,
  watchlist_id  BIGINT NOT NULL REFERENCES watchlist(id) ON DELETE CASCADE,
  listing_id    BIGINT NOT NULL REFERENCES listing(id),
  triggered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at  TIMESTAMPTZ,
  dismissed_at  TIMESTAMPTZ
);
CREATE INDEX ON alert_event (watchlist_id, triggered_at DESC);
```

### Audit

```sql
CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  actor       TEXT NOT NULL,                    -- user_id or 'system:<job>'
  action      TEXT NOT NULL,
  target      TEXT,
  before_jsonb JSONB,
  after_jsonb  JSONB,
  at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Migrations
Alembic. One migration per logical change. Never edit a shipped migration. Partitions for `raw_listing` and `listing_version` created by a monthly cron job two months ahead.

## Backup & retention
- Daily `pg_dump` to S3, 30-day retention.
- Continuous WAL archiving for PITR, 7-day window.
- `raw_listing` partitions older than 90 days moved to glacier-class S3 and detached from the table (re-attachable for replay).
- Test restore every month. Untested backups don't exist.
