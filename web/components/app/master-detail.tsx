"use client";

/**
 * The sliding master/detail shell.
 *
 * Selecting a row narrows the list and slides a detail panel in from the side. The
 * shell owns only the motion — the list and the panel contents belong to the page, so
 * students, courses and grades share the choreography without sharing a data shape.
 *
 * Openness is a prop, not state: the caller derives it from the URL, which is what
 * makes a selected row linkable and the Back button work.
 *
 * ## Why this is CSS and not Motion
 *
 * It was `AnimatePresence` with a spring, and it had a bug a browser found and no
 * test could: **the panel never unmounted.** The exit animation ran to completion —
 * measured, ending at exactly `opacity: 0; translateX(40px)` with no animation still
 * running — and then `AnimatePresence` did not remove the child. In the first form,
 * with `mode="popLayout"` and `layout` on the container, it froze part-way at
 * `opacity: 0.579` and sat *visibly* over the full-width list after Back, unchanged
 * across fourteen samples over thirteen seconds.
 *
 * Three attempts failed to fix it: removing the redundant `layout` props, swapping the
 * exit spring for a time-bounded tween, and `mode="wait"` instead of `popLayout`. Each
 * improved the symptom — the residue ended up invisible and zero-width — but the node
 * still stayed in the DOM, and it still contained a focusable close button, so a
 * keyboard user could tab into an invisible panel. That is the real cost of the leak,
 * and it is not cosmetic.
 *
 * A closed panel here is not unmounted at all, so there is nothing to remove and no
 * removal callback to depend on. `visibility` carries the part Motion was needed for:
 * transitioned with a delay equal to the fade, it stays `visible` for the whole way
 * out and then flips to `hidden`, which takes the subtree out of both the tab order
 * and the accessibility tree. On the way in the delay is zero, so it is visible
 * immediately and the fade is seen.
 *
 * `prefers-reduced-motion` is handled by one media query in `globals.css` rather than
 * a duplicate React tree, which is how this file lost its second copy of the markup.
 */

import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  /** The list, always rendered. */
  children: ReactNode;
  /** The panel contents, or null when nothing is selected. */
  detail: ReactNode;
  /**
   * Changes whenever the selection changes. Used to restart the panel's entrance
   * when moving straight from one record to another, which would otherwise swap the
   * contents with no transition at all.
   */
  detailKey?: string | null;
}

export function MasterDetail({ children, detail, detailKey }: Props) {
  const open = detail !== null && detail !== undefined;

  const panelRef = useRef<HTMLElement>(null);
  // Where focus was when the panel opened, so it can be put back. Without this,
  // closing the panel drops focus onto <body> and the next Tab restarts from the top
  // of the page — the row that was being read is lost.
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      returnTo.current = document.activeElement as HTMLElement | null;
      // The panel is not focusable by itself; tabIndex={-1} makes it a programmatic
      // target only, so it never joins the tab order as a stop of its own.
      panelRef.current?.focus({ preventScroll: true });
      return;
    }
    // `isConnected` because the row may have been removed by the same action that
    // closed the panel — focusing a detached node silently does nothing and leaves
    // focus on <body> anyway.
    if (returnTo.current?.isConnected) returnTo.current.focus({ preventScroll: true });
    returnTo.current = null;
  }, [open]);

  return (
    <div className="flex gap-6">
      {/* On narrow screens the panel takes the whole width instead of splitting it:
          two 42% columns on a phone are two unreadable columns. */}
      <div className={`master-list min-w-0 ${open ? "hidden lg:block" : ""}`} data-open={open}>
        {children}
      </div>

      <aside
        ref={panelRef}
        tabIndex={-1}
        // Belt and braces with the `visibility: hidden` the closed state applies:
        // aria-hidden states the intent even if a future edit drops the CSS.
        aria-hidden={!open}
        className="detail-panel min-w-0 outline-none"
        data-open={open}
      >
        {/* Keyed so switching from one record straight to another replays the
            entrance rather than silently swapping the text. */}
        <div key={detailKey ?? "detail"} className="detail-panel-inner">
          {detail}
        </div>
      </aside>
    </div>
  );
}
