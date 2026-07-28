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
    // `scroll: false`, or the browser jumps to the top and the row just clicked
    // leaves the viewport exactly as the panel opens.
    router.push(id ? `${pathname}?id=${encodeURIComponent(id)}` : pathname, {
      scroll: false,
    });
  };

  return [selected, select];
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
