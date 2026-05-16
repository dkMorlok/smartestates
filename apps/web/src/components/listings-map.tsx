"use client";

import { useQuery } from "@tanstack/react-query";
import maplibregl, { type Map as MaplibreMap, Marker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import { fetchMapListings } from "@/lib/api";
import { formatPriceCZK } from "@/lib/format";
import type { BBox } from "@/lib/types";

// OpenFreeMap serves free OSM-based vector tiles; swap for Protomaps or
// MapTiler in production (see docs/GEO.md).
const TILE_STYLE = "https://tiles.openfreemap.org/styles/positron";

// Wenceslas Square — sensible default centre for an MVP that is Praha-only.
const PRAHA_CENTER: [number, number] = [14.4378, 50.0755];
const DEFAULT_ZOOM = 12;

interface View {
  bbox: BBox;
  zoom: number;
}

export function ListingsMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const [view, setView] = useState<View | null>(null);

  // Initialise the map once. The dev React Strict-Mode double-invocation is
  // handled by the early-return guard.
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

    const publishView = () => {
      const b = map.getBounds();
      setView({
        bbox: {
          min_lon: b.getWest(),
          min_lat: b.getSouth(),
          max_lon: b.getEast(),
          max_lat: b.getNorth(),
        },
        zoom: Math.round(map.getZoom()),
      });
    };
    map.on("load", publishView);
    map.on("moveend", publishView);

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  const { data, isFetching } = useQuery({
    queryKey: ["map", view],
    queryFn: () => fetchMapListings(view!.bbox, view!.zoom),
    enabled: view !== null,
    staleTime: 30_000,
  });

  // Re-render markers whenever the response changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data) return;

    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    if (data.mode === "pins") {
      for (const pin of data.pins) {
        const el = document.createElement("a");
        el.href = `/listings/${pin.id}`;
        el.title = [pin.disposition, formatPriceCZK(pin.price_czk)]
          .filter(Boolean)
          .join(" · ");
        el.className =
          "block h-3 w-3 rounded-full bg-blue-600 ring-2 ring-white shadow";
        markersRef.current.push(
          new maplibregl.Marker({ element: el })
            .setLngLat([pin.lon, pin.lat])
            .addTo(map),
        );
      }
    } else {
      for (const cluster of data.clusters) {
        const el = document.createElement("div");
        el.className =
          "flex h-8 min-w-8 items-center justify-center rounded-full " +
          "bg-blue-600/85 px-2 text-xs font-semibold text-white shadow";
        el.textContent = String(cluster.count);
        markersRef.current.push(
          new maplibregl.Marker({ element: el })
            .setLngLat([cluster.lon, cluster.lat])
            .addTo(map),
        );
      }
    }
  }, [data]);

  const counterText = data
    ? data.mode === "pins"
      ? `${data.pins.length} nabídek`
      : `${data.clusters.reduce((s, c) => s + c.count, 0)} nabídek ve ${data.clusters.length} shlucích`
    : "Načítání…";

  return (
    <div
      className="relative w-full overflow-hidden rounded-md border border-neutral-200"
      style={{ height: "calc(100vh - 9rem)", minHeight: 480 }}
    >
      <div
        ref={containerRef}
        style={{ position: "absolute", top: 0, right: 0, bottom: 0, left: 0 }}
      />
      <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-white/90 px-2 py-1 text-xs text-neutral-700 shadow">
        {isFetching ? "…" : ""} {counterText}
      </div>
    </div>
  );
}
