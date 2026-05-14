# Roadmap

## MVP (v0, 8 weeks, 1–2 engineers)

**Scope:** Praha only, byty only (prodej), Sreality as the only source, basic scoring with hedonic regression, search + map + detail pages. No accounts.

### In scope
- Postgres + PostGIS schema (raw, canonical, derived layers).
- Sreality source module via undocumented JSON API.
- RÚIAN-seeded Nominatim, address-precision tracking.
- Dedup tier 1 only (RÚIAN exact + same-source duplicates).
- Hedonic regression scoring with components and confidence.
- Market stats segmentation incl. ownership_type & building_type.
- Risk flags: 8 critical ones from `SCORING.md`.
- Web: search (table + map), property detail, market overview.
- Filters URL-encoded.
- Sentry + basic Grafana dashboards.
- Daily Postgres backup + monthly restore test.
- Source canary monitoring.

### Out of scope (deferred)
- Multi-source.
- User accounts, watchlists, alerts.
- Photo perceptual-hash dedup.
- Yield estimation (no rental data yet).
- ČŠI / crime / flood overlays.
- ML/advanced scoring.
- Mobile native.
- Public API.

### Exit criteria
- Sreality ingestion runs nightly without manual intervention for 7 consecutive days.
- ≥ 25,000 active Praha-byt listings ingested and scored.
- ≥ 95% of listings geocoded at street precision or better; ≥ 80% rooftop.
- Search returns results in < 500ms p95.
- Internal review: top 20 "undervalued" listings sanity-checked by a human; no obvious družstevní mismarking, no obvious legal-encumbrance noise.
- Zero scraping-related complaints from Seznam.

---

## Phase 2 (months 3–4): Credibility & users

### In scope
- Second source: **Bezrealitky** (owner-direct, critical for unbiased signals).
- User accounts (email + password, magic links).
- Watchlists + email alerts (daily digest first; per-listing real-time Phase 3).
- Photo perceptual hashing for cross-source dedup.
- Dedup review queue + admin UI.
- Yield estimation v1: scrape Sreality rentals, build rental segments, estimate gross yield with confidence.
- Risk overlays: floodplain (DIBAVOD), building age + panel building capex risk.
- Scoring v2: A/B framework, multiple `model_version`s coexisting.
- Data quality dashboard public to logged-in users (transparency).
- Czech + English UI toggle.

### Exit criteria
- 2 sources stable, < 5% disagreement on shared listings after dedup.
- 100+ registered users.
- ≥ 50 watchlists with at least one alert delivered.
- Documented model comparison (v1 vs v2) with metrics.

---

## Phase 3 (months 5–6): Depth

### In scope
- **Transaction data integration** — Land Registry (ČÚZK), Cenová mapa where licensable.
- Undervaluation anchored on sold prices, not asking prices. This is the credibility upgrade.
- Third + fourth sources (Reality.idnes, regional sites).
- Multi-city: Brno, Ostrava, Plzeň, Liberec, Olomouc.
- Family houses (`dum`) support.
- ČŠI school quality data, ČSÚ crime data overlays.
- Per-property page (one URL per physical property aggregating all listings over time).
- Net yield calculation with user-editable assumptions.
- API tokens for power users.
- Real-time price-drop alerts (within 1h).
- Mobile-friendly responsive web.

### Exit criteria
- ≥ 4 sources, ≥ 100k active listings across CZ.
- Undervaluation backtested against actual transactions: median absolute error documented.
- 500+ active users.

---

## Phase 4 (months 7–9): Scale & ML

### In scope
- Postgres read replica for the API.
- Worker pool partitioned by source class.
- Browser-pool worker (Playwright) for any source that requires JS, when legal.
- ML rerank on top of rule-based score, *only if* it measurably improves backtested precision-at-K vs hedonic alone.
- Photo-based features (interior quality, room detection) — Phase 4 only.
- Public market reports (auto-generated PDFs per district).
- Pozemky (land) and komerční (commercial) property types.

### Exit criteria
- p95 latency unchanged under 5× load.
- ML model passes A/B with statistically significant improvement.

---

## Phase 5 (months 10–12+): Optional

- Native mobile (only if web analytics show > 40% mobile usage and friction).
- B2B API offering for funds and agencies.
- Slovakia expansion (similar legal framework, smaller market).
- Sold-price prediction model (not just undervaluation residual).
- Portfolio mode: track owned properties + their estimated values over time.

---

## Anti-roadmap (things we will NOT do)
- Build our own MLS / listing platform. We're an analytics tool, not a marketplace.
- Become a brokerage. Different regulatory regime, different business.
- Generate AI listing descriptions or photos. Out of scope and bad signal hygiene.
- "Chat with your properties" LLM features. Not what users need.
- Crypto / tokenization. No.
- Scale into countries we don't understand the legal regime of.
