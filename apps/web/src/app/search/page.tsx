import { Suspense } from "react";

import { SearchClient } from "@/components/search-client";

export default function SearchPage() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <header className="mb-4">
        <h1 className="text-lg font-semibold">Realitní Skener</h1>
        <p className="text-sm text-neutral-500">
          Nabídky bytů — Praha, prodej. Filtry se ukládají do URL.
        </p>
      </header>
      {/* useSearchParams requires a Suspense boundary in the App Router. */}
      <Suspense
        fallback={<p className="py-8 text-sm text-neutral-500">Načítání…</p>}
      >
        <SearchClient />
      </Suspense>
    </main>
  );
}
