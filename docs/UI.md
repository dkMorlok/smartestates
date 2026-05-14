# UI

## Principles
- **Table-first.** This is an investor tool. Density beats whitespace.
- **No marketing aesthetics.** No hero gradients, no glassmorphism, no "AI-feeling" UI.
- **URL is state.** All filters, sort, map bbox, selection encoded in URL. Shareable, bookmarkable, refresh-safe.
- **Show the work.** Score components and risk flags visible; never just a magic number.
- **Senior users.** Default text size larger than typical; high contrast; predictable interactions.

## Stack
- Next.js 14 App Router, TypeScript strict.
- shadcn/ui (Radix + Tailwind) for primitives.
- TanStack Query for fetching, TanStack Table for grid, TanStack Virtual for virtualization.
- MapLibre GL JS for map.
- Recharts for time-series (price history, market trends).
- Form: react-hook-form + zod.

## Pages

### `/` Dashboard
- Hero block: "N new opportunities today" + 5–10 top listings (composite > threshold, confidence > 0.6, not seen by user).
- Below: market overview chart (ppm² by district, 12-month trend).
- Source health badges (green/yellow/red).
- No marketing. Looks like a Bloomberg terminal lite, not a startup landing page.

### `/search` (primary workspace)
Split view:

```
┌───────────────────────────────────────────────────────────────┐
│  Filter chips: [Praha 5] [2+kk,3+kk] [osobni] [+10% under]    │
├──────────────────────────────────┬────────────────────────────┤
│  Table (virtualized)              │  Map (MapLibre)            │
│  ┌─────────────────────────────┐  │                            │
│  │ □ Score Price ppm² ...      │  │   ● ● ●                    │
│  │ ─────────────────────────── │  │  ●   ● ●                   │
│  │ ★ 84 4.9M 86k Praha 5 2+kk  │  │     ●  ●                   │
│  │ ★ 81 6.2M 78k Praha 8 3+kk  │  │  ●     ●                   │
│  │   78 ...                     │  │                            │
│  └─────────────────────────────┘  │                            │
└──────────────────────────────────┴────────────────────────────┘
```

- Table columns (configurable, persisted): score (composite + sparkline of components), price, ppm², size, disposition, district, ownership, condition, year, energy, DOM, confidence, source.
- Click row → property detail in side panel (desktop) or new page (mobile).
- Selection syncs with map highlight.
- Sort by any column.
- Bulk actions: add to watchlist, export CSV.
- Map: bbox filters table; drawing a polygon also filters.

### `/listing/[id]` (property detail)
Sections, top to bottom:
1. **Header:** address, price big, ppm², size, key facts. Source link as a small button.
2. **Photo strip:** thumbnails, lightbox.
3. **Score panel:** composite + radar/bar chart of components + confidence label + explanation paragraph.
4. **Risk flags:** each flag as a bordered chip with hover explanation.
5. **Market comparison:** histogram of segment ppm², this listing marked. Caption: "Praha 5, panel, 2+kk, 50–70 m², good condition — 87 active listings."
6. **Price history:** sparkline + table of changes (date, old → new, % change).
7. **Comparables:** 10 nearest comparable listings, table.
8. **Map:** building location, transit stops within 800m, flood/risk overlays toggleable.
9. **Yield estimate:** rent estimate, HOA assumption, computed yield, with inputs the user can edit (recomputes locally).
10. **Description:** raw description (HTML-stripped, with key terms highlighted: `exekuce`, `dražba`, etc.).
11. **Actions:** add to watchlist, set price alert, dismiss.

### `/watchlists`
- List of saved searches with criteria summary.
- Each: matches today, matches yesterday, alert count.
- Edit / delete / pause notifications.

### `/me/alerts`
- Reverse chronological list of triggered alerts.
- Click → listing detail.
- Dismiss / mute the rule.

### `/markets/[segment]`
- Segment overview: definition, n_active, ppm² distribution histogram.
- Time series: ppm² median over 24 months.
- DOM trend.
- Top opportunities currently in this segment.

### `/admin/*` (role=admin)
- Sources page: per-source health, last successful run, pause/resume, manual canary trigger.
- Runs page: table of recent `source_run`s with status, counts, errors.
- DLQ: dead-letter jobs, replay button.
- Dedup review: side-by-side comparison of two candidate listings, merge or reject.
- Data quality: dashboard of field completeness, geocoding precision distribution, source success rates.
- Scoring configs: list model versions, promote one to default.

## Components (shadcn-based)
- `ListingTable` — virtualized, sortable, column-configurable.
- `ListingMap` — MapLibre wrapper with cluster support.
- `ScorePanel` — composite + components, with explainer.
- `RiskFlag` — chip with hover popover.
- `MarketHistogram` — segment distribution with current listing marked.
- `PriceHistory` — sparkline + table.
- `FilterBar` — filter chips, URL-synced.
- `WatchlistForm` — criteria builder.

## UX rules
- **Loading:** skeletons, never spinners on the main content.
- **Empty:** explicit empty states with a suggested filter relaxation.
- **Errors:** inline with retry; never silent.
- **No surprise navigation:** clicking a row never leaves the search context unless explicit.
- **Keyboard:** `/` focuses filter, `j/k` moves table selection, `Enter` opens detail, `Esc` closes.
- **Color:** colorblind-safe palette. Score color scale is also encoded by shape/icon so it's not color-only.
- **Locale:** Czech first, English toggle. Numbers formatted CZ-style (`4 950 000 Kč`, decimal comma).
- **Timezone:** all times Europe/Prague.

## Performance budgets
- First Contentful Paint < 1.5s on broadband.
- Search page interactive < 2s.
- Table: smooth scroll with 5,000 virtualized rows.
- Map: 60fps panning with up to 1,000 visible pins (clustered above).
- Filter change → table update < 200ms (cached) / < 800ms (uncached).

## Things we will not build (yet)
- Marketing site / landing page. The dashboard is the front page for now.
- Mobile native apps. Responsive web first.
- "Compare two listings side-by-side" view. Phase 2.
- In-app messaging / contact agent. Out of scope.
- Social features. Out of scope.
