"use client";

import { useQuery } from "@tanstack/react-query";
import maplibregl, { type Map as MaplibreMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import { fetchBreakdown } from "@/lib/api";
import type { BreakdownRow, GroupBy } from "@/lib/types";

const TILE_STYLE = "https://tiles.openfreemap.org/styles/positron";
// Centred on Czechia; fitBounds zooms into the actual data extent after load.
const CZ_CENTER: [number, number] = [15.5, 49.8];
const DEFAULT_ZOOM = 6.5;

// Sequential cool→warm scale (blue → amber → red) for the ppm² heatmap.
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
  return Math.max(14, Math.round(scaled * 48));
}

type Positioned = BreakdownRow & {
  lat: number;
  lon: number;
  ppm2: number | null;
};

export interface AggregateMapProps {
  /** Which dimension to group by (drives the API call). */
  groupBy: GroupBy;
  /** When "ppm2", bubbles are colored by median ppm²; "none" = flat blue. */
  colorBy: "ppm2" | "none";
  title: string;
  description: string;
  /** Height in pixels. */
  heightPx?: number;
  /** Cap the number of bubbles rendered (keeps locality maps usable). */
  topN?: number;
}

export function AggregateMap({
  groupBy,
  colorBy,
  title,
  description,
  heightPx = 520,
  topN,
}: AggregateMapProps) {
  const { data, isFetching } = useQuery({
    queryKey: ["breakdown", "aggregate-map", groupBy],
    queryFn: () => fetchBreakdown({ group_by: groupBy }),
    staleTime: 60_000,
  });

  const rows = useMemo<Positioned[]>(() => {
    const all = data?.rows ?? [];
    const out: Positioned[] = [];
    for (const r of all) {
      const lat = Number(r.centroid_lat);
      const lon = Number(r.centroid_lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      out.push({ ...r, lat, lon, ppm2: num(r.median_ppm2) });
    }
    out.sort((a, b) => b.count - a.count);
    return topN !== undefined ? out.slice(0, topN) : out;
  }, [data, topN]);

  const ppm2Vals = useMemo(
    () => rows.map((r) => r.ppm2).filter((v): v is number => v !== null),
    [rows],
  );
  const minPpm2 = ppm2Vals.length ? Math.min(...ppm2Vals) : 0;
  const maxPpm2 = ppm2Vals.length ? Math.max(...ppm2Vals) : 0;

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

  // Re-render bubbles on data change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    const maxCount = rows.reduce((m, r) => Math.max(m, r.count), 0);
    const range = maxPpm2 - minPpm2;

    for (const r of rows) {
      const radius = bubbleRadiusPx(r.count, maxCount);
      const el = document.createElement("div");
      el.style.width = `${radius}px`;
      el.style.height = `${radius}px`;
      if (colorBy === "ppm2" && r.ppm2 !== null) {
        const t = range > 0 ? (r.ppm2 - minPpm2) / range : 0.5;
        el.style.background = colorFor(t);
      } else {
        el.style.background = "rgba(37, 99, 235, 0.72)";
      }
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
      map.fitBounds(bounds, { padding: 60, maxZoom: 11, duration: 400 });
    }
  }, [rows, minPpm2, maxPpm2, colorBy]);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-xs text-neutral-500">{description}</p>
        </div>
        <span className="text-xs text-neutral-500">
          {isFetching ? "Načítám…" : `${rows.length} oblastí`}
        </span>
      </div>

      <div
        className="relative w-full overflow-hidden rounded-md border border-neutral-200"
        style={{ height: heightPx }}
      >
        <div
          ref={containerRef}
          style={{ position: "absolute", top: 0, right: 0, bottom: 0, left: 0 }}
        />
        {colorBy === "ppm2" ? <PriceLegend min={minPpm2} max={maxPpm2} /> : null}
      </div>
    </section>
  );
}

function PriceLegend({ min, max }: { min: number; max: number }) {
  const gradient = `linear-gradient(90deg, ${colorFor(0)}, ${colorFor(0.5)}, ${colorFor(1)})`;
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-white/95 px-3 py-2 text-xs text-neutral-700 shadow">
      <div className="mb-1 font-medium">Medián Kč/m²</div>
      <div className="h-2 w-48 rounded" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between tabular-nums">
        <span>{fmtKc(min)}</span>
        <span>{fmtKc(max)}</span>
      </div>
    </div>
  );
}
