"use client";

/**
 * Reveals its children when they scroll into view.
 *
 * Motion rather than anime.js here: this is React-state-driven and per-instance,
 * which is exactly the split described in the plan — anime.js owns the landing
 * page's choreographed timelines, Motion owns anything tied to component state.
 *
 * `once` by default. A section that re-animates every time it scrolls past is
 * distracting on the way back up, and it makes the page feel unstable.
 */

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Seconds to wait, for staggering siblings. */
  delay?: number;
  className?: string;
}

export function Reveal({ children, delay = 0, className }: Props) {
  const reduced = useReducedMotion();

  // Reduced motion gets the finished state immediately, not a shorter animation.
  if (reduced) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
