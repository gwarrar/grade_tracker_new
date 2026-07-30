"use client";

/**
 * The two pieces every master/detail page shares.
 *
 * The tables themselves differ per entity and stay separate — a generic table
 * driven by a column config would be longer than the three it replaced, and every
 * per-entity detail would have to be smuggled through it.
 */

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { usePathname, useRouter } from "@/i18n/navigation";

/**
 * Read and write the selected record's id in the query string.
 *
 * In the URL rather than in state, which is what makes a selected record
 * linkable, makes Back close the panel, and survives a refresh.
 *
 * @returns The current id (or null) and a setter that navigates.
 */
export function useSelection(): [string | null, (id: string | null) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const selected = params.get("id");

  const select = (id: string | null) => {
    // Rebuilt from the existing parameters rather than written fresh. The earlier
    // version composed `?id=...` from the pathname alone, which silently dropped
    // every other parameter — so once the grades page keeps its filters, its sort
    // and its page number in the URL, clicking a row would have reset all three.
    const next = new URLSearchParams(params);
    if (id === null) next.delete("id");
    else next.set("id", id);

    const query = next.toString();
    // `scroll: false`, or the browser jumps to the top and the row just clicked
    // leaves the viewport exactly as the panel opens.
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return [selected, select];
}

/**
 * Read and write one query parameter, leaving the rest of the URL alone.
 *
 * The same contract as {@link useSelection} for anything that is not the selected
 * row: filters, sort keys, page numbers. Setting a value to `null` — or to the
 * fallback — removes the parameter instead of writing an empty one, so a URL that
 * has been reset to its defaults is the bare path.
 *
 * @param name - The parameter to read and write.
 * @param fallback - Returned when the parameter is absent, and treated as the
 *   value that means "not set" when writing.
 * @returns The current value and a setter that navigates.
 */
export function useUrlParam(
  name: string,
  fallback = "",
): [string, (value: string | null) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const current = params.get(name) ?? fallback;

  const set = (value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null || value === "" || value === fallback) next.delete(name);
    else next.set(name, value);

    // Changing a filter invalidates the page number: page 4 of an unfiltered list
    // is rarely page 4 of a filtered one, and an out-of-range page renders empty.
    if (name !== "page") next.delete("page");

    const query = next.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return [current, set];
}

/**
 * A value that settles after the user stops typing.
 *
 * Without it, a six-character search is six requests and six re-renders, and the
 * responses can arrive out of order.
 *
 * @param value - The immediate value.
 * @param delay - Milliseconds of quiet before settling. 250ms sits below the
 *   threshold where a search field starts to feel laggy.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
