"use client";

/**
 * The sliding master/detail shell.
 *
 * Selecting a row narrows the list and springs a detail panel in from the side.
 * The shell owns only the motion — the list and the panel contents belong to the
 * page, so students, courses and grades share the choreography without sharing a
 * data shape.
 *
 * Two deliberate constraints:
 *
 * - **Only `transform` and `opacity` animate.** The width change is a `flex-basis`
 *   on the container driven by Motion's `layout` prop, which Motion implements as
 *   a transform rather than a per-frame layout. Animating `width` directly would
 *   re-layout every row on every frame.
 * - **`layout` sits on the container, never on the rows.** With 200 rows each
 *   measuring itself, the first frame costs more than the whole animation.
 *
 * Openness is a prop, not state: the caller derives it from the URL, which is what
 * makes a selected row linkable and the Back button work.
 */

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

const SPRING = { type: "spring", stiffness: 280, damping: 32 } as const;

interface Props {
  /** The list, always rendered. */
  children: ReactNode;
  /** The panel contents, or null when nothing is selected. */
  detail: ReactNode;
  /**
   * Changes whenever the selection changes, so the panel animates between
   * records rather than only in and out.
   */
  detailKey?: string | null;
}

export function MasterDetail({ children, detail, detailKey }: Props) {
  const reduced = useReducedMotion();
  const open = detail !== null && detail !== undefined;

  // Reduced motion collapses the whole thing to an instant layout change. Not a
  // shorter animation — no animation, which is what the preference asks for.
  if (reduced) {
    return (
      <div className="flex gap-6">
        <div className={open ? "hidden lg:block lg:w-[42%] lg:shrink-0" : "w-full"}>
          {children}
        </div>
        {open && <aside className="min-w-0 flex-1">{detail}</aside>}
      </div>
    );
  }

  return (
    <motion.div layout className="flex gap-6">
      <motion.div
        layout
        // On narrow screens the panel takes the whole width instead of splitting
        // it: two 42% columns on a phone are two unreadable columns.
        className={`min-w-0 ${open ? "hidden lg:block" : "w-full"}`}
        animate={{ flexBasis: open ? "42%" : "100%" }}
        transition={SPRING}
        style={{ flexGrow: open ? 0 : 1, flexShrink: 0 }}
      >
        {children}
      </motion.div>

      {/* popLayout so the outgoing panel is taken out of flow immediately — with
          the default mode the incoming and outgoing panels briefly sit side by
          side and shove the list back to full width mid-animation. */}
      <AnimatePresence mode="popLayout" initial={false}>
        {open && (
          <motion.aside
            key={detailKey ?? "detail"}
            className="min-w-0 flex-1"
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={SPRING}
          >
            {detail}
          </motion.aside>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
