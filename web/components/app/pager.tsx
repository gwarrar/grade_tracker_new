"use client";

/**
 * Previous / next paging for a server-paginated list.
 *
 * Deliberately not a numbered pager. Jumping to page 7 of 40 is a thing people do
 * when they are lost, and the fix for being lost is a filter, not a page number —
 * which is why this ships alongside the filter bar rather than instead of it.
 */

import { formatNumber } from "@/lib/format";
import { pageCount } from "@/lib/pager";

interface Props {
  page: number;
  size: number;
  total: number;
  locale: string;
  labels: { previous: string; next: string; status: (page: number, pages: number) => string };
  onPage: (page: number) => void;
}

export function Pager({ page, size, total, locale, labels, onPage }: Props) {
  const pages = pageCount(total, size);
  if (pages <= 1) return null;

  return (
    <nav
      className="flex items-center justify-between gap-4 border-t border-line px-4 py-3"
      aria-label={labels.status(page, pages)}
    >
      <button
        type="button"
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:opacity-40"
      >
        {labels.previous}
      </button>

      {/* aria-live so a screen reader hears the page change; the buttons stay put, so
          without it the only feedback is rows silently swapping underneath. */}
      <p className="numeric text-xs text-subtle" aria-live="polite">
        {labels.status(page, pages)}
        <span className="ms-2">({formatNumber(total, locale)})</span>
      </p>

      <button
        type="button"
        onClick={() => onPage(page + 1)}
        disabled={page >= pages}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:opacity-40"
      >
        {labels.next}
      </button>
    </nav>
  );
}
