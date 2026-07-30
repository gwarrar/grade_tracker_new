/**
 * The drifting starfield behind the hero.
 *
 * A **server component that ships no JavaScript at all.** Three elements, each
 * carrying one `box-shadow` listing every star in its layer — so a 240-star field is
 * three DOM nodes and three paints, not 240 of each.
 *
 * ## Why not a canvas
 *
 * The requirement was that it must not block the main thread. A CSS field *cannot*,
 * because there is no JavaScript with which to block it:
 *
 * | | main thread | JS shipped | reduced motion | parallax |
 * |---|---|---|---|---|
 * | box-shadow layers | none — compositor only | 0 KB | one media query | three speeds, free |
 * | canvas + rAF | a callback every frame, forever | ~80 lines, plus device-pixel-ratio, resize, and an IntersectionObserver to pause it offscreen | a JS branch | by hand |
 * | three.js / tsparticles | worse | 150–600 KB | by hand | free |
 *
 * Canvas would buy per-star twinkle and cursor interaction. Neither was asked for,
 * and neither survives `prefers-reduced-motion` anyway.
 *
 * Positions come from {@link starLayers}, which is seeded — see that module for why.
 * The animation and the fade live in `globals.css`.
 */

import { starLayers } from "@/lib/starfield";

// Any fixed value works; this one is a constant so the field never shifts between
// builds. Change it only to deliberately reshuffle the sky.
const SEED = 0x5eed;

/**
 * Render the starfield.
 *
 * Paints nothing of its own and is `absolute inset-0`, so it takes the size of
 * whatever it is placed inside — the caller decides where the sky is.
 */
export function Starfield() {
  return (
    <div aria-hidden className="starfield pointer-events-none absolute inset-0 overflow-hidden">
      {starLayers(SEED).map((layer) => (
        <div
          key={layer.duration}
          className="starfield-layer"
          style={{
            width: layer.size,
            height: layer.size,
            opacity: layer.opacity,
            animationDuration: `${layer.duration}s`,
            boxShadow: layer.boxShadow,
          }}
        />
      ))}
    </div>
  );
}
