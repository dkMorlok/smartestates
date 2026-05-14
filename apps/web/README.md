# Realitní Skener — Web

Minimal Week-4 web skeleton: a table-first listing search backed by the
`/v1/listings` API. Map view and property detail page are follow-ups.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript · Tailwind v4 ·
TanStack Query · TanStack Table

## Develop

```bash
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at the API
npm install
npm run dev                  # http://localhost:3000  → redirects to /search
```

The API must be running (the dev stack exposes it on `:8000`; its CORS
config already allows `http://localhost:3000`).

## Scripts

- `npm run dev` — dev server
- `npm run build` / `npm run start` — production build
- `npm run lint` — `next lint`
- `npm run typecheck` — `tsc --noEmit`

## Layout

```
src/
  app/
    layout.tsx          root layout + TanStack Query provider
    page.tsx            redirects to /search
    search/page.tsx     search page shell (Suspense boundary)
  components/
    search-client.tsx   derives the API query from URL params
    filter-bar.tsx      URL-encoded filter form
    listings-table.tsx  TanStack Table over /v1/listings
    providers.tsx
  lib/
    api.ts              typed fetch client
    use-listings.ts     TanStack Query hook
    types.ts            API response types
    format.ts           cs-CZ number/price formatting
    utils.ts            cn()
```

## Not yet wired

- Not part of the Docker Compose dev stack (run it with `npm run dev`).
- No shadcn/ui component layer yet — styling is plain Tailwind.
- Map view (MapLibre) and property detail page are the next slice.
