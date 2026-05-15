import type { ListingDetail } from "@/lib/types";
import {
  formatArea,
  formatPriceCZK,
  formatPricePerM2,
  humanize,
} from "@/lib/format";

const DASH = "—";

function KeyFact({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </dt>
      <dd className="text-sm text-neutral-900">{value ?? DASH}</dd>
    </div>
  );
}

function formatFloor(current: number | null, total: number | null): string | null {
  if (current === null) return null;
  if (total === null) return String(current);
  return `${current} / ${total}`;
}

export function ListingDetailView({ listing }: { listing: ListingDetail }) {
  const place = [listing.city_district, listing.locality]
    .filter((s): s is string => Boolean(s))
    .join(" · ");

  return (
    <article className="mx-auto max-w-5xl space-y-6 px-6 py-6">
      <header className="space-y-2">
        <div className="text-sm text-neutral-500">{place || DASH}</div>
        <h1 className="text-2xl font-semibold">
          {humanize(listing.disposition)} · {formatArea(listing.size_m2)} ·{" "}
          {formatPriceCZK(listing.price_czk)}
        </h1>
        <p className="text-sm text-neutral-600">
          {formatPricePerM2(listing.price_czk, listing.size_m2)}
        </p>
        <a
          href={listing.canonical_url}
          target="_blank"
          rel="noreferrer"
          className="inline-block text-sm text-blue-700 underline"
        >
          Otevřít na {listing.source_slug} →
        </a>
      </header>

      {listing.photos.length > 0 && (
        <section className="flex gap-2 overflow-x-auto">
          {listing.photos.map((p) => (
            // Source photos vary in dimensions; plain <img> is simpler than
            // configuring Next/Image for every source domain at MVP scope.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={p.url}
              src={p.url}
              alt=""
              loading="lazy"
              className="h-48 w-auto rounded-md object-cover"
            />
          ))}
        </section>
      )}

      <section>
        <dl className="grid grid-cols-2 gap-4 rounded-md border border-neutral-200 p-4 sm:grid-cols-3 md:grid-cols-4">
          <KeyFact label="Vlastnictví" value={humanize(listing.ownership_type)} />
          <KeyFact label="Stavba" value={humanize(listing.building_type)} />
          <KeyFact label="Stav" value={humanize(listing.condition)} />
          <KeyFact label="Užitná plocha" value={formatArea(listing.usable_area_m2)} />
          <KeyFact label="Pokoje" value={listing.rooms} />
          <KeyFact
            label="Patro"
            value={formatFloor(listing.floor_current, listing.floor_total)}
          />
          <KeyFact label="Rok kolaudace" value={listing.year_built} />
          <KeyFact label="Energ. třída" value={listing.energy_class} />
          <KeyFact label="PSČ" value={listing.postcode} />
          <KeyFact label="Katastr" value={listing.cadastral_area} />
          <KeyFact label="RK / agent" value={listing.agency ?? listing.agent_name} />
          <KeyFact
            label="Soukromý prodej"
            value={
              listing.is_owner_direct === null
                ? null
                : listing.is_owner_direct
                  ? "Ano"
                  : "Ne"
            }
          />
        </dl>
      </section>

      {listing.description && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-neutral-700">Popis</h2>
          <p className="whitespace-pre-line text-sm leading-relaxed text-neutral-800">
            {listing.description}
          </p>
        </section>
      )}
    </article>
  );
}
