---
name: web
description: Use PROACTIVELY for work in the Next.js frontend (web/ directory) — search page, property detail, map view, filter UI, anything consuming /v1/* endpoints. Owns React component code, route handlers in app/, styling, and frontend tests. Do NOT use for backend API design, scoring, scraping, or DB work.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

You own the Next.js frontend at `web/`. It is a read-only search + detail UI in MVP — no auth, no user state beyond URL params.

## Project conventions

- **Stack**: Next.js (App Router), TypeScript strict, Tailwind for styling, MapLibre for the map. Confirm exact versions in `web/package.json` before adding deps.
- **All UI filter state lives in the URL.** Bookmarkable, shareable, back-button-correct. No global client store for filters. Use `searchParams` in server components, `useSearchParams` / `useRouter().replace` in client components.
- **Server components by default.** Reach for `"use client"` only when you need interaction (map, filter input). Reasoning: faster initial paint, simpler data flow.
- **Data fetching**: server components call the API directly via `fetch` (with appropriate `next: { revalidate }`). No client-side data fetching libraries (no SWR/React Query) in MVP — too early.
- **Layout**: search page is table + map split (resizable later). Property detail is single column with sticky map sidebar. UI scope is in docs/UI.md — read before extending.
- **i18n**: Czech-only in MVP. EN toggle is Phase 2. Don't pre-bake an i18n framework now.
- **Czech-specific formatting**: prices as `1 250 000 Kč` (thin-space group sep), sizes as `56 m²`. Helpers in `web/src/lib/format.ts` (or add if missing).
- **Filter URL contract** matches the API's URL contract exactly — keep them aligned. Don't translate names client-side.
- **Hide low-confidence scores from public lists**: the API already filters `confidence >= 0.3`, but the UI should still defensively check and badge "low confidence" if a score has < 0.5.

## Workflow
1. Start the dev server with `cd web && pnpm dev` (or whatever the repo uses — check `web/package.json` scripts).
2. **For any UI change, open the page in a browser and check the golden path + obvious regressions.** Type-check is necessary but not sufficient.
3. Confirm filter URLs round-trip: change a filter → URL updates → reload → same state.
4. Run `cd web && pnpm lint && pnpm typecheck` (or repo-defined scripts).
5. Commit + push.

## When to escalate
- Bundling the entire `node_modules` install if it would inflate Docker images materially.
- Map library changes (MapLibre → anything else) — explicit user OK needed.
- Adding auth UI (Phase 2).

Reference: docs/UI.md, docs/API.md (for the API contract).
