import { cn } from "@/lib/utils";

// Czech labels for known flags. Unknown codes render verbatim (they are
// technical identifiers and intentionally machine-readable).
const RISK_LABELS: Record<string, string> = {
  price_too_low: "podezřele nízká cena",
  legal_encumbrance: "právní zátěž",
  druzstevni_mismarked: "družstevní past",
  panel_capex_due: "panelák bez revitalizace",
  top_floor_no_lift: "horní patro bez výtahu",
  class_g_energy: "energie F/G",
  photo_count_low: "málo fotek",
  description_keywords: "varovné slovo v popisu",
};

// Codes that warrant a louder visual treatment.
const HIGH_SEVERITY = new Set<string>([
  "price_too_low",
  "legal_encumbrance",
  "druzstevni_mismarked",
]);

type RiskFlagsProps = {
  flags: string[] | null | undefined;
};

export function RiskFlags({ flags }: RiskFlagsProps) {
  if (!flags || flags.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {flags.map((flag) => {
        const label = RISK_LABELS[flag] ?? flag;
        const high = HIGH_SEVERITY.has(flag);
        return (
          <li key={flag}>
            <span
              className={cn(
                "inline-flex items-center rounded-md border px-2 py-0.5 text-xs",
                high
                  ? "border-red-200 bg-red-50 text-red-800"
                  : "border-neutral-200 bg-neutral-50 text-neutral-700",
              )}
              title={flag}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
