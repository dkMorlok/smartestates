# Czech-Specific Notes

Read this before writing any normalization or scoring code. Most of the "obvious" cross-country real estate logic breaks on CZ specifics. This document captures the traps.

## Property types

Czech canonical types we model:
- **byt** — flat/apartment. The bulk of inventory.
- **dum** — family house.
- **pozemek** — land plot.
- **komercni** — commercial.
- **chata / chalupa** — cottage / countryside cabin (don't merge with `dum`).
- **garáž** — garage.
- **ostatní** — other.

Sub-classifications matter: a `chata` priced as a `dum` will look "undervalued" and shouldn't.

## Disposition (the dominant size descriptor)

CZ describes flats by room layout first, m² second. A "2+kk" means 2 rooms + kitchenette; "3+1" means 3 rooms + separate kitchen. Buyers search by disposition more than by m².

Canonical values:
`1+kk`, `1+1`, `2+kk`, `2+1`, `3+kk`, `3+1`, `4+kk`, `4+1`, `5+kk`, `5+1`, `6+`, `atypicky`, `garsoniera`.

Garsoniéra ≈ studio = `1+kk` for our purposes but mark separately if disclosed.

Rules:
- Always store disposition. Listings missing it are quarantined for review.
- Segment by disposition. Do not bucket "1+kk" with "2+kk".
- `+1` (separate kitchen) trades at a slight premium over `+kk` (kitchenette) in pre-1990 buildings.

## Ownership type — the biggest CZ-specific scoring trap

Three legal forms:
1. **Osobní vlastnictví (OV)** — personal/freehold ownership. The buyer owns the unit and a share of common parts. Standard.
2. **Družstevní vlastnictví (DV)** — cooperative ownership. The buyer owns a share in a housing cooperative + the right to use a specific unit. Conversion to OV often possible but costly and slow.
3. **Státní / obecní** — state/municipal. Rare, mostly historical, often with sitting tenants.

**Price impact:** DV trades 10–25% below OV for the same physical unit. Reasons: mortgage harder to get, resale restrictions, the underlying ownership is a share, not real estate.

**The trap:** any system that averages prices across ownership types will report every DV listing as "20% undervalued." This has happened in every CZ real estate analytics tool ever shipped. Don't be the next.

**What to do:**
- `ownership_type` is a hard segment key. Never average across.
- If ownership_type is missing/unknown, do not score; quarantine for review.
- Add risk flag `druzstevni_mismarked` for any listing where ownership_type is missing AND price < 0.85 × segment_median.

## Building type

Sreality and most sources expose:
- **panel** — prefab panel building, mostly 1960s–1980s, large blocks.
- **cihla** — brick, broader range of ages.
- **smíšená** — mixed.
- **dřevo** — wood, rare for flats.
- **kámen** — stone, mostly older buildings.

**Price impact:** cihla > smíšená > panel, roughly 10–15% gap between panel and cihla in the same district.

Panel buildings from 1960–1990 are aging into a capex window — façade insulation (`zateplení`), elevator replacement, pipework. Watch for `revitalizace` or `po revitalizaci` in descriptions; missing = likely upcoming bill of ~3,000 CZK/m² assessed to owners.

## Condition (`stav objektu`)

Sreality enum:
- `novostavba` — new build
- `velmi dobrý` — very good
- `dobrý` — good
- `v rekonstrukci` — under reconstruction
- `po rekonstrukci` — after reconstruction
- `před rekonstrukcí` — before reconstruction (needs work)
- `špatný` — bad
- `projekt` — project (paper only)

Map to canonical: `new / very_good / good / needs_work / before_reconstruction / ruin / project`.

Don't trust "very good" without photo evidence; agency optimism is real. Phase 3 photo-based features can validate.

## Energy class (PENB)

Mandatory in listings since 2013. Values A–G. Often missing or "G – nezadáno" (G = not provided / default).

- Track presence as a data-quality signal: missing PENB after 2013 is a small negative flag.
- Class F/G adds risk flag `class_g_energy`.
- Effect on price is moderate but growing as energy costs rise.

## Addresses (RÚIAN)

**RÚIAN** = Registr územní identifikace, adres a nemovitostí. Official, free, downloadable from ČÚZK.

- Every address has a unique `kód adresního místa` (address point code). This is the gold key for dedup and property linking.
- CZ uses **two house numbers**: `číslo popisné` (descriptive number, building-level) and `číslo orientační` (orientation number, street-level). E.g., "Vinohradská 2128/175" — 2128 is `popisné`, 175 is `orientační`.
- Parse both; either alone is insufficient.
- Praha addresses also include `městská část` and `katastrální území`. Track both.

Diacritics: store original with diacritics, normalize separately for matching (`unidecode`).

## Praha specifics

- **22 administrative city districts** (`městský obvod` / `městská část` — Praha 1–22) + 57 self-governing city districts. We use the 22-district layer.
- Each administrative district contains multiple `katastrální území` (cadastral areas). Praha 1 alone has 7. For micro-segmentation, use katastrální území.
- Postcode prefixes give district hint: `110xx` → Praha 1, `120xx` → Praha 2, etc.
- Metro lines are A (green), B (yellow), C (red), and the under-construction D. Distance to nearest metro station is a strong price feature, distance to Anděl / Florenc / Můstek etc. as transfer nodes even more so.
- Tram density matters; bus-only neighborhoods discount.
- Vltava floodplain is real (2002, 2013 floods); DIBAVOD data is free.
- Anti-Airbnb regulation tightening — listings marketed for short-term rental get a yield-risk flag.

## Other cities (Phase 3)

- **Brno** — second city, ~400k pop, university-driven rental market. Districts: Brno-střed, Brno-sever, Žabovřesky, etc.
- **Ostrava** — coal-mining history; subsidence zones (ČBÚ data); price gradient by district extreme.
- **Plzeň** — Škoda-driven economy, more stable.
- **Liberec** — smaller, tourism-influenced.
- **Olomouc, České Budějovice, Hradec Králové, Pardubice** — regional centers, thinner inventory; segment relaxation triggers more often.

## Listing language patterns

Regex risk keywords (case-insensitive, diacritics-normalized):
```
exekuc|dražb|drazb|břemen|bremen|předkupní|predkupni|zástavní|zastavni|
dluh|insolvenc|insolventn|zatížen|zatizen|spoluvlastnic|na demolic|
havarijní stav|havarijni stav|sporn[áé]
```

Positive keywords (boost confidence, not price):
```
revitaliz|zatepl|po rekonstrukci|po kompletní rekonstrukci|
bezbarier|kolaudac|protokol
```

## Money / numbers

- Currency CZK (Kč). Always.
- Display: thin space as thousand separator, decimal comma. `4 950 000 Kč` not `4,950,000 CZK`.
- Store as integer CZK; do not use floats.
- Hidden prices (`Cena: Info v RK`, `Cena na vyžádání`) are common for premium. Treat as `price_hidden=TRUE`, quarantine from scoring, list with "Price on request."

## Fees / costs the user cares about

- **SVJ** (společenství vlastníků jednotek) — owners' association fees. Typically 30–80 CZK/m²/month, sometimes higher with elevator/concierge. Listings often state this; parse it.
- **Fond oprav** — reserve fund contribution, often bundled into SVJ fee.
- **Daň z nemovitých věcí** — property tax. Trivial in CZ (~5 CZK/m²/year for flats in most municipalities); don't over-model.
- **Real estate transfer tax** — abolished in 2020. Don't include.

## Rental market (for yield, Phase 2)

- Rental listings on Sreality (`category_type_cb=2`) and Bezrealitky.
- Praha rents 350–600 CZK/m²/month for typical 2+kk in 2024–2025; Brno 250–400; regional cities lower.
- Average gross yield in Praha 3.5–4.5%; regional cities 5–7%.
- Furnished vs unfurnished significant gap (~15%); model separately.
- Short-term (Airbnb) rentals: higher gross, much higher operational cost and regulatory risk; do not blend into long-term yield estimates.

## Useful CZ data sources

- **ČÚZK / RÚIAN** — addresses, cadastre.  `https://vdp.cuzk.cz/`
- **ČSÚ** — statistical office, demographics, economy.  `https://www.czso.cz/`
- **ČŠI** — school inspections.  `https://www.csicr.cz/`
- **DIBAVOD** — water/flood data.  `https://www.dibavod.cz/`
- **ČBÚ** — mining authority, subsidence zones.
- **MapaKriminality** (Policie ČR) — crime statistics.  `https://www.mapakriminality.cz/`
- **OpenStreetMap CZ** — POIs, transit.

## Vocabulary cheat-sheet

| CZ | EN |
|---|---|
| byt | flat |
| dům | house |
| pozemek | land plot |
| chata / chalupa | cottage |
| dispozice | layout/disposition |
| vlastnictví osobní | personal/freehold ownership |
| vlastnictví družstevní | cooperative ownership |
| panelák | panel building |
| cihla | brick |
| užitná plocha | usable area |
| zastavěná plocha | built-up area |
| podlahová plocha | floor area |
| sklep | cellar |
| lodžie | loggia |
| balkón | balcony |
| terasa | terrace |
| garáž | garage |
| stání | parking spot |
| výtah | lift |
| patro / podlaží | floor / storey |
| přízemí | ground floor |
| zvýšené přízemí | raised ground floor |
| podkroví | attic / loft |
| novostavba | new build |
| rekonstrukce | reconstruction/renovation |
| revitalizace | building-wide renovation |
| zateplení | insulation/cladding |
| kolaudace | building approval / final inspection |
| exekuce | foreclosure |
| dražba | auction |
| věcné břemeno | easement / encumbrance |
| předkupní právo | right of first refusal |
| zástavní právo | lien / mortgage charge |
| SVJ | owners' association |
| fond oprav | repair fund |
| nájem | rent |
| pronájem | leasing (rental) |
| prodej | sale |
| městská část | city district |
| katastrální území | cadastral area |
| katastr nemovitostí | real estate cadastre |
| RK / realitka | real estate agency |
| RK = realitní kancelář | |
