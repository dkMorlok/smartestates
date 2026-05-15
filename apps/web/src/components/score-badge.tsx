import { cn } from "@/lib/utils";

type ScoreBadgeProps = {
  /** Composite 0..100 — higher is better. */
  composite: number | string | null;
  /**
   * Predicted-vs-asking gap as a signed percentage. Negative = cheaper than
   * predicted = good for the buyer.
   */
  undervaluationPct?: number | string | null;
  /** 0..1 model confidence. Below 0.5 we tag "nízká důvěra". */
  confidence?: number | string | null;
  size?: "sm" | "md";
};

function toNum(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function compositeTone(value: number): {
  bg: string;
  text: string;
  border: string;
} {
  if (value < 30) {
    return {
      bg: "bg-red-100",
      text: "text-red-800",
      border: "border-red-200",
    };
  }
  if (value < 60) {
    return {
      bg: "bg-amber-100",
      text: "text-amber-800",
      border: "border-amber-200",
    };
  }
  return {
    bg: "bg-emerald-100",
    text: "text-emerald-800",
    border: "border-emerald-200",
  };
}

export function ScoreBadge({
  composite,
  undervaluationPct,
  confidence,
  size = "sm",
}: ScoreBadgeProps) {
  const compositeNum = toNum(composite);
  const underNum = toNum(undervaluationPct);
  const confidenceNum = toNum(confidence);

  const pillSize =
    size === "md"
      ? "px-2.5 py-1 text-sm font-semibold"
      : "px-2 py-0.5 text-xs font-semibold";
  const tagSize =
    size === "md" ? "px-2 py-0.5 text-xs" : "px-1.5 py-0.5 text-[10px]";

  const tone =
    compositeNum === null
      ? { bg: "bg-neutral-100", text: "text-neutral-500", border: "border-neutral-200" }
      : compositeTone(compositeNum);

  // Undervaluation tag: negative = cheaper than predicted = positive signal.
  let underTag: React.ReactNode = null;
  if (underNum !== null) {
    const rounded = Math.round(underNum);
    const good = rounded < 0;
    const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
    const cls = good
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : rounded > 0
        ? "bg-red-50 text-red-700 border-red-200"
        : "bg-neutral-50 text-neutral-600 border-neutral-200";
    underTag = (
      <span
        className={cn(
          "inline-flex items-center rounded-md border",
          tagSize,
          cls,
        )}
        title="podhodnocení vs. predikce"
      >
        {sign}
        {Math.abs(rounded)} %
      </span>
    );
  }

  const lowConfidence =
    confidenceNum !== null && confidenceNum < 0.5 ? (
      <span
        className={cn(
          "inline-flex items-center rounded-md border border-neutral-200 bg-neutral-50 text-neutral-600",
          tagSize,
        )}
        title={`Důvěra ${(confidenceNum * 100).toFixed(0)} %`}
      >
        nízká důvěra
      </span>
    ) : null;

  return (
    <div className="inline-flex flex-wrap items-center gap-1.5">
      <span
        className={cn(
          "inline-flex items-center rounded-full border tabular-nums",
          pillSize,
          tone.bg,
          tone.text,
          tone.border,
        )}
        aria-label="skóre"
      >
        {compositeNum === null ? "n/a" : Math.round(compositeNum)}
      </span>
      {underTag}
      {lowConfidence}
    </div>
  );
}
