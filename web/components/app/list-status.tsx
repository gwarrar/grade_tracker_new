"use client";

/**
 * What a list shows when it has no rows to show.
 *
 * The three list screens each wrote this by hand, and all three wrote the same two
 * branches: loading, and empty. None of them wrote the third.
 *
 * That is the bug worth fixing here. A failed request leaves `data` undefined, so
 * `rows.length === 0` is true and the table rendered **"No data"** — telling a
 * teacher their course has no students when the truth was that the server refused
 * the request. "Broken" and "genuinely empty" have to look different, or the reader
 * makes decisions on the wrong one.
 *
 * The error branch carries `role="alert"` so it is announced rather than silently
 * swapped in, and the whole thing renders through the `.empty` class in
 * `globals.css` — which existed, described exactly this, and had zero usages while
 * twelve call sites hand-rolled its Tailwind equivalent.
 */

import type { UseQueryResult } from "@tanstack/react-query";

import { useApiError } from "@/lib/use-api-error";

export function ListStatus({
  query,
  isEmpty,
  loadingLabel,
  emptyLabel,
}: {
  /** The query backing the list. Only its status flags are read. */
  query: Pick<UseQueryResult, "isPending" | "isError" | "error">;
  /** Whether the list rendered zero rows. Checked only once the query succeeded. */
  isEmpty: boolean;
  loadingLabel: string;
  emptyLabel: string;
}) {
  const describe = useApiError();

  if (query.isPending) return <p className="empty">{loadingLabel}</p>;

  if (query.isError) {
    return (
      <p className="empty text-fail" role="alert">
        {describe(query.error)}
      </p>
    );
  }

  return isEmpty ? <p className="empty">{emptyLabel}</p> : null;
}
