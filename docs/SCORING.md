# Scoring Model

## Principles
- **No black-box single number.** Composite score is shown alongside its components and a confidence value.
- **Hedonic regression, not raw segment means.** Same flat in same building can differ 30% by floor, condition, etc.
- **Segment carefully.** In CZ, ownership_type and building_type dominate price — must be segment keys.
- **Confidence is first-class.** Low-comp segments return a score with `confidence < 0.5` and the UI labels it as such.
- **Versioned.** Every score row has `model_version`. Rolling out a new model is shipping a new version, not editing the old one.

## What we compute per listing

| Field | Type | Meaning |
|---|---|---|
| `undervaluation_pct` | -50..+50 | Residual vs hedonic prediction in % terms |
| `undervaluation_abs` | CZK | Same in absolute money |
| `yield_gross_pct` | 0..15 | Estimated annual rent / asking price |
| `yield_confidence` | 0..1 | Quality of rental comps |
| `liquidity_score` | 0..100 | Function of segment DOM and turnover |
| `location_score` | 0..100 | Composite of transit, amenities, schools |
| `risk_score` | 0..100 | Higher = riskier; based on flags |
| `confidence_score` | 0..1 | Sample size, completeness, age of comps |
| `composite` | 0..100 | Weighted blend (weights stored in DB, A/B-able) |
| `risk_flags` | string[] | Explicit list, shown verbatim in UI |

## Segments

Segment key for CZ flats:
```
(city_district, property_type, ownership_type, building_type,
 disposition, size_bucket, condition_bucket)
```

Size buckets (m²): `<35`, `35-50`, `50-70`, `70-90`, `90-120`, `120-160`, `>160`.
Condition buckets: `new`, `very_good`, `good`, `needs_work`, `before_reconstruction`, `ruin`.

**Minimum comps:** 30 active listings within the last 90 days. If below threshold:
1. Widen size bucket to neighbors.
2. Widen condition bucket to neighbors.
3. Drop building_type.
4. Widen to parent admin area (Praha 5 → Praha).
5. Drop disposition (keep ownership_type and property_type — never drop these).

`relaxation_level` is recorded with the stat so we know how loose the segment was. Each relaxation step lowers confidence.

## Hedonic regression

Fit nightly per (city, property_type, ownership_type). Robust regression (Huber loss) to limit outlier influence.

```
log(price_per_m2) ~
    C(building_type) +
    C(disposition) +
    C(condition) +
    floor_current +
    I(floor_current = floor_total AND has_lift = FALSE) +   -- top-floor walk-up discount
    log(size_m2) +
    year_built_bucket +
    energy_class +
    has_balcony + has_loggia + has_terrace +
    has_cellar + has_parking +
    distance_to_metro_m +                  -- Praha only
    distance_to_tram_m +
    distance_to_train_m +
    C(city_district)
```

Per-listing **undervaluation** = `predicted_log_ppm2 - actual_log_ppm2`, converted to percent and clamped to ±50%.

Why hedonic instead of just segment median:
- Two listings in the same segment can legitimately differ 20% based on floor, lift, energy class.
- Median ignores those, calls all the bad ones "undervalued."
- Regression residuals separate "actually cheap" from "cheap because top-floor walk-up with class G energy."

## Yield estimation

Gross yield = `(rent_estimate_monthly × 12 - hoa_estimate_annual) / asking_price`.

Rent estimate:
- Find rental listings in same segment within 90 days.
- Take trimmed mean of price_per_m2_per_month.
- Multiply by listing's `size_m2`.

If fewer than 10 rental comps in segment → relax (same hierarchy as sale segments) → mark `yield_confidence` < 0.5.

If no rental comps at any relaxation → `yield_gross_pct = NULL`, `yield_confidence = 0`. **Do not fabricate.**

HOA estimate (`SVJ poplatky`): from listing if stated, else 50 CZK/m²/month default with `yield_confidence` reduced.

Net yield (Phase 2): subtract property tax (trivial in CZ, ~5 CZK/m²/year for flats), insurance, vacancy assumption (5%), management (10% if not self-managed). Expose all assumptions as user-editable in the property page.

## Liquidity

```
liquidity_score = scale(
    -0.6 * segment_dom_median_days
    -0.4 * (1 / segment_turnover_quarterly)
)
```
Scaled to 0..100 across all CZ segments. DOM under 30 days and turnover > 0.1/quarter → high liquidity.

## Location

Sub-scores 0..100, blended equal-weight initially:
- **Transit:** function of distance to nearest metro/tram/train + service frequency from GTFS.
- **Amenities:** count of grocery, café, restaurant, pharmacy, school within 800m (OSM POIs).
- **Green:** distance to nearest park > 1 ha.
- **Quiet:** inverse of road-noise proxy (distance to nearest primary/secondary road class).
- **Schools:** ČŠI inspection data when integrated; Phase 2.

## Risk flags (explicit, shown in UI)

Each flag is binary; risk_score is a function of count and severity.

| Flag | Trigger | Severity |
|---|---|---|
| `price_too_low` | listing ppm² < 0.6 × segment p25 | high |
| `legal_encumbrance` | description matches regex: `exekuc|dražb|břemen|předkupní|zástavní|dluh` | high |
| `druzstevni_mismarked` | ownership_type unclear AND price < segment_median × 0.85 | high |
| `panel_capex_due` | building_type=panel AND year_built 1960-1990 AND no `revitaliz` in description | medium |
| `flood_zone` | within Q100 floodplain (DIBAVOD) | medium |
| `top_floor_no_lift` | floor_current=floor_total AND has_lift=false AND floor_total>3 | low |
| `class_g_energy` | energy_class IN ('F','G') | low |
| `photo_count_low` | photo count < 4 | low |
| `price_dropped_fast` | price cut > 5% within 14 days of listing | medium (signal of motivated seller OR something wrong) |
| `agency_high_churn` | agency's listings have median DOM < 7 days and frequent relistings | medium |
| `description_keywords` | description matches risk regex (`havarijní stav`, `na demolici`, etc.) | varies |

## Confidence

```
confidence = product of:
  segment_sample_size_factor (0..1, sigmoid around N=30),
  relaxation_factor (1.0 at level 0, 0.6 at level 5),
  field_completeness (0..1, missing critical fields penalize),
  geocode_precision_factor (rooftop=1.0, street=0.85, locality=0.5),
  listing_freshness_factor (1.0 < 30d, drops to 0.5 at 180d)
```

Score with `confidence < 0.3` is hidden from public lists; visible in admin only.

## Composite

```
composite = sigmoid(
    +1.5 * z(undervaluation_pct)
    +0.6 * z(yield_gross_pct) * yield_confidence
    +0.3 * z(liquidity_score)
    +0.3 * z(location_score)
    -0.8 * z(risk_score)
) * 100
```

Weights live in a `scoring_config` table keyed by `model_version`. Changes go behind a feature flag and ship to internal users before public.

## Operational rules

- Score job runs nightly at 04:00 Europe/Prague over all `active` listings.
- New listing → score computed within next ingestion cycle, not on insert (avoid hot-path cost).
- Score recompute triggered by: market_stat update, listing field change, scoring_config change.
- A/B: two `model_version`s can coexist. UI shows one to users, dashboard compares them.

## What we are NOT doing yet
- Deep-learning rerank: not until rule-based has stable baseline metrics and we have transaction ground truth.
- Photo-based ML (e.g. "good interior detection"): defer until Phase 3.
- Sold-price prediction (vs asking-price comparison): requires transaction data integration, Phase 3.
