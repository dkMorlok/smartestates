"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import {
  formatArea,
  formatPriceCZK,
  formatPricePerM2,
  humanize,
} from "@/lib/format";
import type { ListingQuery, ListingSummary } from "@/lib/types";
import { useListings } from "@/lib/use-listings";

const columnHelper = createColumnHelper<ListingSummary>();

const columns = [
  columnHelper.accessor("disposition", {
    header: "Dispozice",
    cell: (c) => humanize(c.getValue()),
  }),
  columnHelper.accessor("size_m2", {
    header: "Plocha",
    cell: (c) => formatArea(c.getValue()),
  }),
  columnHelper.accessor("price_czk", {
    header: "Cena",
    cell: (c) => formatPriceCZK(c.getValue()),
  }),
  columnHelper.display({
    id: "price_per_m2",
    header: "Cena / m²",
    cell: (c) =>
      formatPricePerM2(c.row.original.price_czk, c.row.original.size_m2),
  }),
  columnHelper.accessor("ownership_type", {
    header: "Vlastnictví",
    cell: (c) => humanize(c.getValue()),
  }),
  columnHelper.accessor("building_type", {
    header: "Stavba",
    cell: (c) => humanize(c.getValue()),
  }),
  columnHelper.accessor("city_district", {
    header: "Městská část",
    cell: (c) => c.getValue() ?? "—",
  }),
  columnHelper.accessor("locality", {
    header: "Lokalita",
    cell: (c) => c.getValue() ?? "—",
  }),
  columnHelper.accessor("canonical_url", {
    header: "Zdroj",
    cell: (c) => (
      <a
        href={c.getValue()}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-blue-700 underline"
      >
        {c.row.original.source_slug}
      </a>
    ),
  }),
];

export function ListingsTable({ query }: { query: ListingQuery }) {
  const router = useRouter();
  const { data, isLoading, isError, error, isPlaceholderData } =
    useListings(query);

  const rows = useMemo(() => data?.data ?? [], [data]);
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (isLoading) {
    return <p className="py-8 text-sm text-neutral-500">Načítání…</p>;
  }
  if (isError) {
    return (
      <p className="py-8 text-sm text-red-600">
        Chyba při načítání: {(error as Error).message}
      </p>
    );
  }
  if (rows.length === 0) {
    return (
      <p className="py-8 text-sm text-neutral-500">
        Žádné nabídky neodpovídají filtru.
      </p>
    );
  }

  return (
    <div className={isPlaceholderData ? "opacity-60" : undefined}>
      <p className="py-3 text-sm text-neutral-600">
        {data?.meta.total ?? rows.length} nabídek
      </p>
      <div className="overflow-x-auto rounded-md border border-neutral-200">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-neutral-50 text-left text-xs uppercase text-neutral-500">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => (
                  <th key={header.id} className="px-3 py-2 font-medium">
                    {flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => router.push(`/listings/${row.original.id}`)}
                className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50"
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
