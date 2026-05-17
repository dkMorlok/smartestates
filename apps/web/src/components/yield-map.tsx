"use client";

import { useQuery } from "@tanstack/react-query";
import maplibregl, { type Map as MaplibreMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import { fetchYield } from "@/lib/api";
import type { YieldRow } from "@/lib/types";

const TILE_STYLE = "https://tiles.openfreemap.org/styles/positron";
const CZ_CENTER: [number, number] = [15.5, 49.8];
const DEFAULT_ZOOM = 6.5;

// Cool→warm scale (low yield = blue/cool, high yield = red/hot). A 5 %
// gross yield is a sensible mid-point for CZ residential real estate.
const SCALE_STOPS = [
  [0.0, [37, 99, 235]],
  [0.5, [234, 179, 8]],
  [1.0, [220, 38, 38]],
] as const;

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function colorFor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  for (let i = 1; i < SCALE_STOPS.length; i++) {
    const [t0, c0] = SCALE_STOPS[i - 1];
    const [t1, c1] = SCALE_STOPS[i];
    if (c <= t1) {
      const lt = (c - t0) / (t1 - t0);
      const r = Math.round(lerp(c0[0], c1[0], lt));
      const g = Math.round(lerp(c0[1], c1[1], lt));
      const b = Math.round(lerp(c0[2], c1[2], lt));
      return `rgb(${r},${g},${b})`;
    }
  }
  return `rgb(${SCALE_STOPS.at(-1)![1].join(",")})`;
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  return `${n.toFixed(2)} %`;
}

function bubbleRadiusPx(sale: number, max: number): number {
  if (max <= 0) return 16;
  return Math.max(14, Math.round(Math.sqrt(sale / max) * 48));
}

type Positioned = YieldRow & { lat: number; lon: number };

export function YieldMap() {
  const { data, isFetching } = useQuery({
    queryKey: ["yield"],
    queryFn: () => fetchYield(),
    staleTime: 60_000,
  });

  const rows = useMemo<Positioned[]>(() => {
    const out: Positioned[] = [];
    for (const r of data?.rows ?? []) {
      const lat = Number(r.centroid_lat);
      const lon = Number(r.centroid_lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      out.push({ ...r, lat, lon });
    }
    return out;
  }, [data]);

  // Anchor the color scale to the actual range of yields we have; districts
  // missing a yield render gray.
  const yields = rows
    .map((r) => r.yield_pct)
    .filter((v): v is number => v !== null);
  const minY = yields.length ? Math.min(...yields) : 0;
  const maxY = yields.length ? Math.max(...yields) : 0;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: TILE_STYLE,
      center: CZ_CENTER,
      zoom: DEFAULT_ZOOM,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    const maxSale = rows.reduce((m, r) => Math.max(m, r.sale_count), 0);
    const range = maxY - minY;

    for (const r of rows) {
      const radius = bubbleRadiusPx(r.sale_count, maxSale);
      const el = document.createElement("div");
      el.style.width = `${radius}px`;
      el.style.height = `${radius}px`;
      if (r.yield_pct === null) {
        el.style.background = "rgba(115, 115, 115, 0.55)";
      } else {
        const t = range > 0 ? (r.yield_pct - minY) / range : 0.5;
        el.style.background = colorFor(t);
      }
      el.className =
        "flex items-center justify-center rounded-full border-2 border-white " +
        "text-[10px] font-semibold text-white shadow-md cursor-pointer";
      el.textContent = r.yield_pct === null ? "?" : `${r.yield_pct.toFixed(1)}`;
      el.title = `${r.city_district} · sale=${r.sale_count} · rent=${r.rent_count} · yield ${fmtPct(r.yield_pct)}`;
      markersRef.current.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([r.lon, r.lat])
          .addTo(map),
      );
    }

    if (rows.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of rows) bounds.extend([r.lon, r.lat]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 11, duration: 400 });
    }
  }, [rows, minY, maxY]);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-base font-semibold">Výnosnost (gross yield)</h2>
          <p className="text-xs text-neutral-500">
            Hrubý roční výnos = medián měsíčního nájmu Kč/m² × 12 ÷ medián
            prodejní ceny Kč/m². Velikost bublina = počet nabídek prodeje;
            barva = výnos. Šedá bublina = málo dat o nájmech.
          </p>
        </div>
        <span className="text-xs text-neutral-500">
          {isFetching ? "Načítám…" : `${rows.length} oblastí`}
        </span>
      </div>

      <div
        className="relative w-full overflow-hidden rounded-md border border-neutral-200"
        style={{ height: 520 }}
      >
        <div
          ref={containerRef}
          style={{ position: "absolute", top: 0, right: 0, bottom: 0, left: 0 }}
        />
        <YieldLegend min={minY} max={maxY} />
      </div>
    </section>
  );
}

function YieldLegend({ min, max }: { min: number; max: number }) {
  const gradient = `linear-gradient(90deg, ${colorFor(0)}, ${colorFor(0.5)}, ${colorFor(1)})`;
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-white/95 px-3 py-2 text-xs text-neutral-700 shadow">
      <div className="mb-1 font-medium">Roční výnos %</div>
      <div className="h-2 w-48 rounded" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between tabular-nums">
        <span>{fmtPct(min || null)}</span>
        <span>{fmtPct(max || null)}</span>
      </div>
    </div>
  );
}
