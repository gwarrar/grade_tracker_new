/** One threshold-to-label entry in an organisation grading scale. */
export interface GradeBand {
  min_percentage: number;
  label: string;
}

/** Stable reason a grading scale cannot be saved. */
export type GradingScaleError =
  | "empty"
  | "order"
  | "zero"
  | "duplicate"
  | "percentage"
  | "label";

/**
 * Mirror the backend grading-scale invariants before an administrator saves.
 *
 * @param bands - Bands in intended display order.
 * @returns The first invalid invariant, or null for a valid scale.
 */
export function validateGradingScale(bands: GradeBand[]): GradingScaleError | null {
  if (bands.length === 0) return "empty";
  if (
    bands.some(
      (band) =>
        !Number.isFinite(band.min_percentage) ||
        band.min_percentage < 0 ||
        band.min_percentage > 100,
    )
  )
    return "percentage";
  if (bands.some((band) => band.label.trim() === "")) return "label";

  const thresholds = bands.map((band) => band.min_percentage);
  if (new Set(thresholds).size !== thresholds.length) return "duplicate";
  if (thresholds.some((threshold, index) => index > 0 && threshold > thresholds[index - 1]!)) {
    return "order";
  }
  return thresholds.at(-1) === 0 ? null : "zero";
}
