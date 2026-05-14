# Risks & Hard Parts

Ranked by severity × likelihood. Each has a mitigation.

## Legal & compliance

### 1. Sreality ToS prohibits automated retrieval
**Severity: high. Likelihood of action: medium.**

Seznam's ToS for sreality explicitly prohibit automated access. They have technical means to block and have done so to scrapers. While the undocumented JSON API is used by their own SPA, accessing it as a third party is still a ToS violation.

**Mitigations:**
- Stay polite: ≤1 req/sec sustained, identifiable User-Agent with contact, bulk runs in low-traffic windows.
- Snapshot raw payloads so we never need to re-fetch.
- Have a paid-feed fallback identified before launch (e.g., Casafari, Reapit) and budget to switch if blocked.
- Reach out to Seznam business development about a data partnership; cheap insurance.
- Don't scrape photos in bulk; hotlink originals or fetch one thumbnail per listing.

### 2. GDPR exposure on agent contact details and listing photos
**Severity: high. Likelihood: low if we're careful.**

Agent names, phone numbers, emails in listings are personal data. Photos may include identifying interior details, vehicles, etc.

**Mitigations:**
- Minimize PII retention: store agency name, drop personal phone/email unless a user explicitly looks up a listing.
- Provide a clear right-to-erasure flow at `/privacy/erasure`.
- Document lawful basis (legitimate interest for the analytics use case).
- Don't republish photos publicly; hotlink originals so the source's CDN remains the publisher.
- DPA with any third party we share data with.

### 3. Cenová mapa / commercial use restrictions
**Severity: medium.**

Prague's Cenová mapa is free for non-commercial use. A subscription product is commercial.

**Mitigation:** license it properly before relying on it, or use only ČÚZK raw data which has clearer terms.

## Data & model

### 4. Družstevní vs osobní mispricing trap
**Severity: high. Likelihood: certain on first launch unless mitigated.**

Družstevní (cooperative) flats trade 10–25% below osobní (freehold) for the same physical unit because the buyer isn't getting the legal title. Every naive comparator across CZ has shipped this bug.

**Mitigation:** ownership_type is a hard segment key, never averaged across. Risk flag `druzstevni_mismarked` for any listing where ownership_type is missing/ambiguous AND price is below segment median.

### 5. Asking-price-vs-asking-price is circular
**Severity: high. Likelihood: structural.**

If we have no sold-price ground truth, "undervalued" means "cheaper than other listings" — which themselves are often optimistic asks. The whole concept becomes vibes.

**Mitigation:**
- MVP: be honest in UI. Label undervaluation as "vs current market asking prices."
- Phase 3 priority: ingest transaction data (ČÚZK). This is the single biggest credibility upgrade.
- Backtest scores against actual sold prices once available; publish the calibration.

### 6. Geocoding imprecision misleads users
**Severity: medium.**

Listings often have intentionally fuzzy addresses ("near Karlín metro"). Showing a rooftop pin for a centroid is a lie users will catch.

**Mitigation:** address_precision is shown in UI; pin style varies by precision; properties with locality-only precision excluded from map view.

### 7. Cold-start in thin markets
**Severity: medium.**

Outside Praha and Brno, segment comp counts drop fast. Score confidence collapses; users see "score: N/A".

**Mitigation:** segment relaxation hierarchy. Communicate confidence clearly. Don't expand to a city until we know it has enough volume.

### 8. Source HTML/API changes break parsers
**Severity: medium. Likelihood: every 1–3 months per source.**

Sreality has redesigned 4+ times in a decade. The undocumented JSON shape is more stable than HTML but not guaranteed.

**Mitigation:**
- Snapshot every raw payload to S3 so we can replay through new parsers.
- Canary fetches a known stable listing hourly; alerts on field-count drop.
- Parser is versioned in DB; rerunning old raw through new parsers is one job.
- Budget 20–30% engineering time for parser maintenance.

### 9. Cross-source dedup is genuinely hard
**Severity: medium.**

Same flat listed by 3 agencies with slightly different addresses, different sizes (one counts loggia, another doesn't), different photos. Naive dedup leaves the catalog noisy.

**Mitigation:**
- Multi-signal clustering (address, size band, price band, photo phash).
- Manual review queue for low-confidence pairs.
- RÚIAN address code is gold when both sources include it.

### 10. Distressed-listing scams skew "undervalued" results
**Severity: medium.**

Listings with `exekuce`/`dražba`/`břemeno` issues look fantastic on ppm² alone.

**Mitigation:** explicit risk flags trained on description regex + agency churn signals; cap risk-flagged listings' composite contribution; manual review of top 20 daily during MVP.

## Operational

### 11. Single VPS is a SPOF
**Severity: low while MVP, medium later.**

If the box dies we're down until restored.

**Mitigation:** daily encrypted backups off-box; documented restore runbook; tested monthly; second region cold standby once revenue justifies it.

### 12. Beat-clock drift / duplicate jobs
**Severity: low.**

Two beat instances → duplicate scrapes → block.

**Mitigation:** single beat container, idempotent jobs, Redis locks per source.

### 13. Cost overruns from photos and tiles
**Severity: low.**

Mirroring photos at scale or paying per map tile load can explode.

**Mitigation:** never mirror full photos (hotlink), self-host map tiles via Protomaps, monitor S3/egress bills weekly.

### 14. Maintenance burden compounds with sources
**Severity: medium.**

Each source breaks independently; with 6 sources expect 1–2 incidents per week.

**Mitigation:** strict per-source isolation; only add sources after stabilizing existing ones; consider a paid aggregator (Casafari etc.) once we've shipped what we can with public/permissive sources.

## Product & trust

### 15. First wrong score destroys trust
**Severity: high.**

Investors are picky. Show them one "undervalued" listing that's obviously družstevní or has a legal encumbrance, and they're gone.

**Mitigation:**
- Show components and risk flags, not just composite.
- Confidence labels visible.
- Manual review of top results before public launch.
- "Report bad score" button feeding the dedup/review queue.

### 16. User expectations of "AI" features
**Severity: low. Annoying.**

Users will ask for ChatGPT-style features.

**Mitigation:** be explicit in product copy: this is a quantitative analytics tool. No chat, no LLM-generated descriptions. The differentiator is data quality, not chrome.

## Open questions we can't resolve until building
- Will Sreality's undocumented endpoint remain accessible at our planned rate? (Test in week 1.)
- What does ČÚZK transaction data actually look like in bulk? Format and coverage. (Research in week 1.)
- Is Bezrealitky's GraphQL going to be stable enough to depend on? (Probe in week 2.)
- Will RÚIAN address codes be present in enough listings for tier-1 dedup to be useful? (Measure after first ingest.)
- What's the actual rental-comp coverage by district? (Measure once rental ingestion is on.)
