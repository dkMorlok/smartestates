import { redirect } from "next/navigation";

export default function Home() {
  // The product is table-first; there is no marketing landing page (UI.md).
  redirect("/search");
}
