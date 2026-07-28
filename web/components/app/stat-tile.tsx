"use client";

/**
 * A single headline figure.
 *
 * Not a chart. "How many students are there" is one number with no comparison
 * and no trend — plotting it would add axes and a legend to communicate a value
 * that a large numeral already communicates exactly.
 *
 * The figure wears a text token, never a series colour: colour here would imply a
 * category that does not exist.
 */

import type { ReactNode } from "react";

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  /** Secondary context, e.g. what the figure is out of. */
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <p className="text-xs uppercase tracking-wide text-subtle">{label}</p>
      <p className="numeric mt-2 text-3xl leading-none text-text">{value}</p>
      {hint && <p className="mt-2 text-xs text-subtle">{hint}</p>}
    </div>
  );
}
