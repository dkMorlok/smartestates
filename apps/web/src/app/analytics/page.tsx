import { Suspense } from "react";

import { AnalyticsClient } from "@/components/analytics-client";

export const metadata = { title: "Analytika · Realitní Skener" };

export default function AnalyticsPage() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <header className="mb-4">
        <h1 className="text-lg font-semibold">Tržní analytika</h1>
        <p className="text-sm text-neutral-500">
          Agregace aktivních nabídek podle dispozice nebo lokality. Klikni na
          řádek pro filtr v seznamu.
        </p>
      </header>
      <Suspense
        fallback={<p className="py-8 text-sm text-neutral-500">Načítání…</p>}
      >
        <AnalyticsClient />
      </Suspense>
    </main>
  );
}
