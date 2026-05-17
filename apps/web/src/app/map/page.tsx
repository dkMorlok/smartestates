import { AggregateMap } from "@/components/aggregate-map";
import { ListingsMap } from "@/components/listings-map";
import { YieldMap } from "@/components/yield-map";

export default function MapPage() {
  return (
    <main className="mx-auto max-w-7xl space-y-8 px-6 py-4">
      <header>
        <h1 className="text-lg font-semibold">Mapa nabídek</h1>
        <p className="text-sm text-neutral-500">
          Více pohledů na trh: hustota nabídek, cena za m² podle městské části,
          a rozpad podle lokalit.
        </p>
      </header>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold">Hustota nabídek</h2>
          <p className="text-xs text-neutral-500">
            Posuňte mapou — při oddálení se nabídky shlukují, při přiblížení
            (zoom 13+) se zobrazí jednotlivé byty.
          </p>
        </div>
        <ListingsMap />
      </section>

      <AggregateMap
        groupBy="city_district"
        colorBy="ppm2"
        title="Cena za m² podle městské části"
        description="Bublina = počet nabídek; barva = medián Kč/m² (modrá = levně, červená = draho)."
      />

      <AggregateMap
        groupBy="locality"
        colorBy="none"
        title="Lokality (čtvrti)"
        description="Jedna bublina = jedna čtvrť. Velikost = počet aktivních nabídek. Zobrazujeme top 60 lokalit podle počtu."
        topN={60}
      />

      <YieldMap />
    </main>
  );
}
