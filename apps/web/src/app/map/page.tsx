import { ListingsMap } from "@/components/listings-map";

export default function MapPage() {
  return (
    <main className="mx-auto max-w-7xl space-y-4 px-6 py-4">
      <header>
        <h1 className="text-lg font-semibold">Mapa nabídek</h1>
        <p className="text-sm text-neutral-500">
          Posuňte mapou — výpis se aktualizuje podle aktuálního výřezu.
        </p>
      </header>
      <ListingsMap />
    </main>
  );
}
