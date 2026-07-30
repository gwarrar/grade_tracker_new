/**
 * Page arithmetic, kept out of the component so it can be tested without React.
 */

/**
 * How many pages a total splits into.
 *
 * The edges are the point: an empty list is **one** page, not zero — a pager reading
 * "Page 1 of 0" looks broken, and there is always a page to show, it is just empty —
 * and an exact multiple must not gain a trailing empty page.
 *
 * @param total - Row count across all pages.
 * @param size - Rows per page.
 * @returns At least 1.
 */
export function pageCount(total: number, size: number): number {
  // Guards a caller passing 0 from an uninitialised state, which would otherwise
  // divide to Infinity and render an unbounded pager.
  if (size <= 0) return 1;
  return Math.max(1, Math.ceil(total / size));
}
