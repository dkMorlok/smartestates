import Link from "next/link";

export function Nav() {
  return (
    <nav className="border-b border-neutral-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3 text-sm">
        <Link href="/search" className="font-semibold text-neutral-900">
          Realitní Skener
        </Link>
        <Link
          href="/search"
          className="font-medium text-neutral-600 hover:text-neutral-900"
        >
          Hledat
        </Link>
        <Link
          href="/map"
          className="font-medium text-neutral-600 hover:text-neutral-900"
        >
          Mapa
        </Link>
      </div>
    </nav>
  );
}
