import { notFound } from "next/navigation";

import { ListingDetailView } from "@/components/listing-detail";
import { fetchListing, fetchListingScore } from "@/lib/api";

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
  // Fetch the listing and its score in parallel. A failed score fetch must
  // not break the page — we degrade to the "not computed" neutral state.
  const [listing, score] = await Promise.all([
    fetchListing(numericId),
    fetchListingScore(numericId).catch(() => null),
  ]);
  if (listing === null) {
    notFound();
  }
  return <ListingDetailView listing={listing} score={score} />;
}
