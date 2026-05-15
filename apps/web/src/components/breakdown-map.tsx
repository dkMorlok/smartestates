"use client";

import maplibregl, { type Map as MaplibreMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import type { BreakdownRow, GroupBy } from "@/lib/types";

const TILE_STYLE = "https://tiles.openfreemap.org/styles/positron";
const PRAHA_CENTER: [number, number] = [14.4378, 50.0755];
const DEFAULT_ZOOM = 10;

// Bubble radius from sample count, sqrt-scaled and clamped so a single big
// group doesn't dwarf everything else.
function bubbleRadiusPx(count: number, maxCount: number): number {
  if (maxCount <= 0) return 12;
  const scaled = Math.sqrt(count / maxCount);
  return Math.max(12, Math.round(scaled * 44));
}

function fmtKc(n: number | string | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return `${new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(
    Math.round(v),
  )} Kč/m²`;
}

interface Props {
  rows: BreakdownRow[];
  groupBy: GroupBy;
}

export function BreakdownMap({ rows, groupBy }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: TILE_STYLE,
      center: PRAHA_CENTER,
      zoom: DEFAULT_ZOOM,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Re-render bubbles whenever rows change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    const positioned = rows.filter(
      (r) => r.centroid_lat !== null && r.centroid_lon !== null,
    );
    const maxCount = positioned.reduce((m, r) => Math.max(m, r.count), 0);

    for (const r of positioned) {
      const radius = bubbleRadiusPx(r.count, maxCount);
      const el = document.createElement("div");
      el.style.width = `${radius}px`;
      el.style.height = `${radius}px`;
      el.className =
        "flex items-center justify-center rounded-full border-2 border-white " +
        "bg-blue-600/70 text-[10px] font-semibold text-white shadow cursor-pointer";
      el.title = [
        r.group_key,
        `${r.count} nabídek`,
        fmtKc(r.median_ppm2),
        r.change_pct_6m === null
          ? null
          : `Δ 6m: ${r.change_pct_6m >= 0 ? "+" : ""}${r.change_pct_6m.toFixed(1)} %`,
      ]
        .filter(Boolean)
        .join(" · ");
      el.textContent = String(r.count);
      markersRef.current.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([r.centroid_lon!, r.centroid_lat!])
          .addTo(map),
      );
    }

    if (positioned.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of positioned) {
        bounds.extend([r.centroid_lon!, r.centroid_lat!]);
      }
      map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 400 });
    }
  }, [rows, groupBy]);

  return (
    <div className="relative h-[calc(100vh-16rem)] min-h-[400px] w-full overflow-hidden rounded-md border border-neutral-200">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-2 top-2 rounded bg-white/90 px-2 py-1 text-xs text-neutral-700 shadow">
        Bublina = počet nabídek
      </div>
    </div>
  );
}
