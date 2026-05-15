import { notFound } from "next/navigation";

import { ListingDetailView } from "@/components/listing-detail";
import { fetchListing } from "@/lib/api";

// Detail data is dynamic — no static prerendering.
export const dynamic = "force-dynamic";

export default async function ListingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isInteger(numericId) || numericId <= 0) {
    notFound();
  }
  const listing = await fetchListing(numericId);
  if (listing === null) {
    notFound();
  }
  return <ListingDetailView listing={listing} />;
}
