"use client";

import { useQuery } from "@tanstack/react-query";
import maplibregl, { type Map as MaplibreMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import { fetchBreakdown } from "@/lib/api";
import type { BreakdownRow } from "@/lib/types";

const TILE_STYLE = "https://tiles.openfreemap.org/styles/positron";
// Centred roughly on Czechia so the initial frame shows the whole country
// even before fitBounds runs; we then zoom in to the actual data extent.
const CZ_CENTER: [number, number] = [15.5, 49.8];
const DEFAULT_ZOOM = 6.5;

// Sequential cool→warm scale (blue → yellow → red), driven by median ppm².
// Stops are picked to read well on the positron basemap.
const SCALE_STOPS = [
  [0.0, [37, 99, 235]],   // tailwind blue-600
  [0.5, [234, 179, 8]],   // amber-500
  [1.0, [220, 38, 38]],   // red-600
] as const;

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function colorFor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  for (let i = 1; i < SCALE_STOPS.length; i++) {
    const [t0, c0] = SCALE_STOPS[i - 1];
    const [t1, c1] = SCALE_STOPS[i];
    if (clamped <= t1) {
      const localT = (clamped - t0) / (t1 - t0);
      const r = Math.round(lerp(c0[0], c1[0], localT));
      const g = Math.round(lerp(c0[1], c1[1], localT));
      const b = Math.round(lerp(c0[2], c1[2], localT));
      return `rgb(${r},${g},${b})`;
    }
  }
  return `rgb(${SCALE_STOPS.at(-1)![1].join(",")})`;
}

function num(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtKc(n: number | null): string {
  if (n === null) return "—";
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(
    Math.round(n),
  )} Kč/m²`;
}

function bubbleRadiusPx(count: number, maxCount: number): number {
  if (maxCount <= 0) return 16;
  const scaled = Math.sqrt(count / maxCount);
  return Math.max(16, Math.round(scaled * 52));
}

export function GeolocationHeatmap() {
  const { data, isFetching } = useQuery({
    queryKey: ["breakdown", "geolocation"],
    queryFn: () => fetchBreakdown({ group_by: "city_district" }),
    staleTime: 60_000,
  });

  type Positioned = BreakdownRow & { lat: number; lon: number; ppm2: number };
  const rows = useMemo<Positioned[]>(() => {
    const out: Positioned[] = [];
    for (const r of data?.rows ?? []) {
      const lat = Number(r.centroid_lat);
      const lon = Number(r.centroid_lon);
      const ppm2 = num(r.median_ppm2);
      if (Number.isFinite(lat) && Number.isFinite(lon) && ppm2 !== null) {
        out.push({ ...r, lat, lon, ppm2 });
      }
    }
    return out;
  }, [data]);

  const { minPpm2, maxPpm2 } = useMemo(() => {
    const vals = rows.map((r) => r.ppm2).sort((a, b) => a - b);
    return {
      minPpm2: vals[0] ?? 0,
      maxPpm2: vals[vals.length - 1] ?? 0,
    };
  }, [rows]);

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

    const maxCount = rows.reduce((m, r) => Math.max(m, r.count), 0);
    const range = maxPpm2 - minPpm2;

    for (const r of rows) {
      const t = range > 0 ? (r.ppm2 - minPpm2) / range : 0.5;
      const radius = bubbleRadiusPx(r.count, maxCount);
      const el = document.createElement("div");
      el.style.width = `${radius}px`;
      el.style.height = `${radius}px`;
      el.style.background = colorFor(t);
      el.className =
        "flex items-center justify-center rounded-full border-2 border-white " +
        "text-[10px] font-semibold text-white shadow-md cursor-pointer";
      el.textContent = String(r.count);
      el.title = `${r.group_key} · ${r.count} nabídek · ${fmtKc(r.ppm2)}`;
      markersRef.current.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([r.lon, r.lat])
          .addTo(map),
      );
    }

    if (rows.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of rows) bounds.extend([r.lon, r.lat]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 10, duration: 400 });
    }
  }, [rows, minPpm2, maxPpm2]);

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-base font-semibold">Geolokace</h2>
          <p className="text-xs text-neutral-500">
            Mediánová cena za m² podle městské části. Velikost bubliny =
            počet aktivních nabídek.
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
        <Legend min={minPpm2} max={maxPpm2} />
      </div>
    </div>
  );
}

function Legend({ min, max }: { min: number; max: number }) {
  const gradient = `linear-gradient(90deg, ${colorFor(0)}, ${colorFor(0.5)}, ${colorFor(1)})`;
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-white/95 px-3 py-2 text-xs text-neutral-700 shadow">
      <div className="mb-1 font-medium">Medián Kč/m²</div>
      <div
        className="h-2 w-48 rounded"
        style={{ background: gradient }}
      />
      <div className="mt-1 flex justify-between tabular-nums">
        <span>{fmtKc(min)}</span>
        <span>{fmtKc(max)}</span>
      </div>
    </div>
  );
}
