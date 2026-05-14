# Geo & Mapping Strategy

## Why this matters
- Address precision drives dedup quality, segment definition, and user trust on the map.
- Bulk Google Geocoding is expensive and ToS-restricted for our use.
- RÚIAN (the official CZ address registry) is free, downloadable, and dramatically better than Nominatim-with-OSM for CZ addresses.

## Geocoder

**Self-hosted Nominatim seeded with RÚIAN + OSM CZ extract.**

Setup outline:
1. Pull RÚIAN CSV/GML from ČÚZK (`https://vdp.cuzk.cz/`).
2. Pull `czech-republic-latest.osm.pbf` from Geofabrik.
3. Convert RÚIAN to OSM tags via custom loader, merge with OSM extract.
4. Import into Nominatim Postgres.
5. Run as a containerized service, reverse-proxied with response caching.

Result: ~95% of CZ addresses geocode to rooftop precision, vs ~60% with vanilla Nominatim.

Refresh RÚIAN quarterly (it doesn't change fast).

### Caching
Aggressive. Every (`normalized_address`, `locality`) tuple → Redis with 30-day TTL. Hit rate after a week of operation should be > 90% because the same buildings get relisted constantly.

## Address normalization

Before geocoding:
1. Strip diacritics for matching only (`unidecode`); keep original for display.
2. Lowercase, collapse whitespace.
3. Standardize abbreviations: `ul.` → `ulice`, `nám.` → `náměstí`, `tř.` → `třída`, etc.
4. Parse house number into `cislo_popisne` and `cislo_orientacni` (CZ has two; RÚIAN uses both).
5. Detect Praha district from postcode prefix (110xx → Praha 1, 120xx → Praha 2, etc.) as fallback.

## Precision levels

Store one of:
- `rooftop` — matched to a building polygon in RÚIAN
- `parcel` — matched to a parcel
- `street` — street name + approximate house number range
- `locality` — only municipality known
- `source_gps` — coordinates given by source (e.g., Sreality `gps` field); we trust these but verify they fall within the stated locality

Surfaced in the UI: pin styling differs by precision. Don't show a rooftop-style pin for a locality centroid.

## Linking listings to properties

Order of preference:
1. **RÚIAN address code match** — bulletproof, when both have it.
2. **`ST_DWithin(geom, geom_b, 3m)`** AND same `address_normalized` — same building.
3. **`ST_DWithin(geom, geom_b, 30m)`** AND fuzzy address match (Levenshtein < 5) — likely same building, lower confidence.
4. Otherwise create new `property`.

When a listing's geom is `locality`-precision, don't link or create — flag for review.

## Boundaries

Imported into PostGIS:
- **Kraje** (regions): from ČÚZK, OSM, or ArcČR.
- **Okresy** (districts): same.
- **Obce** (municipalities): same.
- **Městské části / městské obvody** for Praha, Brno, Plzeň, Ostrava: critical for Praha which is split into 22 administrative districts AND 57 city districts (yes, both layers; we use the 22 administrative ones).
- **Katastrální území** (cadastral areas): for finer Praha segmentation. Praha 1 alone has 7.
- **Custom neighborhoods**: if we want micro-areas like "Karlín" or "Smíchov-sever", draw them manually or buy.

All stored as `geography(MultiPolygon, 4326)` with GIST indexes.

## Geo features for scoring

Stored per property, computed once per geocode:
- `distance_to_nearest_metro_m`
- `distance_to_nearest_tram_m`
- `distance_to_nearest_bus_m`
- `distance_to_nearest_train_m`
- `transit_score` (composite, decays with distance)
- `nearest_park_m`
- `noise_proxy` (distance to nearest primary/secondary road)
- `poi_density_800m` (count of grocery, café, restaurant, pharmacy)
- `school_score` (Phase 2 with ČŠI data)
- `flood_zone` (`Q5`/`Q20`/`Q100`/`Q500`/none) from DIBAVOD
- `radon_index` (low/medium/high) from ČGS data
- `mining_subsidence_zone` (boolean) from ČBÚ for Ostrava/Karviná/Most

Recomputed when underlying layers update (quarterly), not per listing scoring run.

## Map (frontend)

**MapLibre GL JS** (open-source fork of Mapbox GL JS v1, no Mapbox account needed).

Tile sources, choose one:
- **Protomaps**, self-hosted (cheapest at scale)
- **MapTiler** (paid, easy, good CZ coverage)
- **Mapy.cz / Seznam Mapy API** (CZ-specific, beautiful, but commercial use requires license — check ToS)
- **OSM raster** (slow, ugly, free — emergency only)

Recommend Protomaps for production, MapTiler dev tier for staging.

### Rendering rules
- **Zoom < 13:** server returns clusters via `ST_ClusterDBSCAN`. Cluster size shown in pin.
- **Zoom 13–15:** individual pins, color by score (low-saturation palette, accessible).
- **Zoom > 15:** pins + building outlines if available.
- Bbox query is debounced 300ms; max 500 pins returned, paginated otherwise.
- Selection sync: clicking a pin highlights the table row and vice versa.

### Pin design
- Color: composite score (cool → warm scale, with a colorblind-safe palette).
- Shape: property type icon.
- Halo: confidence (full opacity = high, hollow = low).
- Hover: small card with price, ppm², score, disposition.

## Don'ts
- Don't show a rooftop-style pin for a centroid geocode.
- Don't cluster client-side above ~5k pins.
- Don't paginate the map view (use bbox); paginate the table.
- Don't fall back silently to a locality centroid — flag it.
- Don't use Google Maps tiles for production: ToS restrictions and cost.
