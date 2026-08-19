/** One threshold-to-label entry in an organisation grading scale. */
export interface GradeBand {
  min_percentage: number;
  label: string;
  /**
   * Worth in a grade point average, or absent until the institution decides.
   *
   * Optional because a GPA only means something once somebody says what an A is
   * worth, and no relationship to `min_percentage` may be assumed or enforced: a
   * German 1-6 scale awards its *lowest* number to its *highest* threshold.
   */
  points?: number | null;
}

/** Stable reason a grading scale cannot be saved. */
export type GradingScaleError =
  | "empty"
  | "order"
  | "zero"
  | "duplicate"
  | "duplicateLabel"
  | "percentage"
  | "label"
  | "points";

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
  if (
    bands.some(
      (band) =>
        band.points != null && (!Number.isFinite(band.points) || band.points < 0),
    )
  ) {
    return "points";
  }

  // Labels are the key every distribution is bucketed by: `Distribution` reads
  // `distribution[label]` and keys its rows on it, so two bands called "P" render
  // twice from one bucket, double the total, and halve every percentage in the
  // chart. The grades filter renders two identical options with a duplicate key.
  // A pass/fail-with-distinction scale reaches this by accident.
  const labels = bands.map((band) => band.label.trim());
  if (new Set(labels).size !== labels.length) return "duplicateLabel";

  const thresholds = bands.map((band) => band.min_percentage);
  if (new Set(thresholds).size !== thresholds.length) return "duplicate";
  if (thresholds.some((threshold, index) => index > 0 && threshold > thresholds[index - 1]!)) {
    return "order";
  }
  return thresholds.at(-1) === 0 ? null : "zero";
}
