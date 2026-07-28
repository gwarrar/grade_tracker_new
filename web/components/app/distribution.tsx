"use client";

/**
 * Grade distribution as horizontal bars.
 *
 * Deliberate choices, in the order they were made:
 *
 * **Form.** Magnitude across a small ordered set → bars. Horizontal rather than
 * vertical because the category labels are text ("A", "B"…) with a threshold
 * beside them, and horizontal bars give labels a full line instead of a cramped
 * rotated axis.
 *
 * **Colour.** One series, so one hue. A rainbow across A–F would imply five
 * unrelated categories; a red-to-green ramp would encode a value judgement the
 * bar length already carries. The band letter carries identity, so there is no
 * legend — a legend for a single series is a box that says what the title said.
 *
 * **No charting library.** Five bars is a flex row and a width. A dependency here
 * would ship a rendering engine to draw five rectangles.
 *
 * Marks follow the house rules: thin bars, rounded data-ends, a surface gap
 * between them, recessive baseline, and direct labels — with five bars, labelling
 * every one is still selective.
 */

import { useTranslations } from "next-intl";

import { formatNumber, formatPercent } from "@/lib/format";

interface Props {
  /** Band label to count, e.g. `{ A: 12, B: 30, … }`. */
  distribution: Record<string, number>;
  /** Band order, worst last. Taken from the organisation's grading scale. */
  order: string[];
  locale: string;
}

export function Distribution({ distribution, order, locale }: Props) {
  const t = useTranslations("stats");

  const bands = order.map((label) => ({ label, count: distribution[label] ?? 0 }));
  const total = bands.reduce((sum, band) => sum + band.count, 0);
  // The scale is the largest band, not the total: with a long tail every bar
  // would otherwise be a sliver and the shape would be unreadable.
  const peak = Math.max(...bands.map((band) => band.count), 1);

  if (total === 0) {
    return (
      <div className="rounded-xl border border-line bg-surface p-6">
        <h2 className="text-sm font-medium text-text">{t("distribution")}</h2>
        <p className="mt-4 text-center text-sm text-subtle">{t("noData")}</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <h2 className="text-sm font-medium text-text">{t("distribution")}</h2>

      {/* A table, not a div soup: the data genuinely is rows of label/value, and
          this gives screen readers the figures without a separate "table view"
          toggle. The bar is decoration layered on a real cell. */}
      <table className="mt-4 w-full">
        <caption className="sr-only">{t("distribution")}</caption>
        <tbody>
          {bands.map((band) => {
            const share = band.count / total;
            return (
              <tr key={band.label} className="group">
                <th
                  scope="row"
                  className="numeric w-8 py-1.5 text-start text-sm font-medium text-text"
                >
                  {band.label}
                </th>
                <td className="w-full py-1.5 ps-2">
                  {/* The track is the surface; the fill is the mark. 2px of gap
                      comes from the track's own padding so fills never touch. */}
                  <div className="h-2.5 w-full rounded-full bg-bg-subtle">
                    <div
                      className="h-full rounded-full bg-brand transition-opacity group-hover:opacity-80"
                      style={{ width: `${(band.count / peak) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="numeric w-14 py-1.5 pe-1 text-end text-sm text-text">
                  {formatNumber(band.count, locale)}
                </td>
                {/* The share is the hover layer's job on a denser chart; with five
                    rows it fits permanently, which is better than hiding it behind
                    a pointer that a keyboard user does not have. */}
                <td className="numeric w-14 py-1.5 text-end text-sm text-subtle">
                  {formatPercent(share * 100, locale)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
