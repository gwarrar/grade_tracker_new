/**
 * Where the stars go.
 *
 * Pure and seeded, kept out of the component so it can be tested without React and so
 * the only interesting part of the starfield — a loop generating coordinates — has a
 * check behind it.
 *
 * Seeded rather than random because the landing page is statically rendered once per
 * locale: `Math.random()` would give the English, German and French builds three
 * different skies, and churn the output on every rebuild.
 */

/** One depth of the field. */
export interface StarLayer {
  /** How many stars. */
  count: number;
  /** Dot diameter in pixels. */
  size: number;
  /** Seconds for one full drift cycle. Slower reads as further away. */
  duration: number;
  /** 0–1. Dimmer reads as further away too. */
  opacity: number;
  /** `[x, y]` pairs, x in `vw` over 0–100, y in `vh` over 0–200. */
  stars: readonly (readonly [number, number])[];
  /** The same stars as a ready-to-use `box-shadow` value. */
  boxShadow: string;
}

// Three depths. Near is sparse, large, quick and bright; far is dense, small, slow
// and dim. That gradient is the entire parallax effect — there is no JS driving it,
// only three different animation durations.
// Counts are high because density is what makes this read as a field rather than a
// scatter, and it is nearly free: the stars in a layer are one `box-shadow` on one
// element, so 500 stars still cost three DOM nodes and three composited paints.
const SHAPE = [
  { count: 90, size: 2, duration: 90, opacity: 0.95 },
  { count: 160, size: 1.5, duration: 140, opacity: 0.7 },
  { count: 280, size: 1, duration: 220, opacity: 0.5 },
] as const;

/**
 * A small deterministic PRNG (mulberry32).
 *
 * Decides where dots go, nothing more — not for anything security-related. What
 * matters is only that one seed always yields one field.
 *
 * @param seed - Any 32-bit integer.
 * @returns A function producing successive values in `[0, 1)`.
 */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Build the three layers of the field.
 *
 * Stars are spread over one viewport width and **two** viewport heights, because the
 * drift animation moves each layer up by one full height. The second height is a
 * continuation of the same field rather than a repeat of the first, which is what
 * makes the loop seamless.
 *
 * Positions are expressed in `vw`/`vh` rather than pixels so the field covers the
 * hero at any window size — a pixel grid sized for a laptop leaves a large display
 * with an empty corner.
 *
 * @param seed - Seeds the whole field. The same seed always gives the same sky.
 * @returns Three layers, near to far.
 */
export function starLayers(seed: number): StarLayer[] {
  return SHAPE.map((layer, index) => {
    const random = mulberry32(seed + index * 977);
    const stars: (readonly [number, number])[] = [];

    for (let i = 0; i < layer.count; i++) {
      stars.push([Number((random() * 100).toFixed(2)), Number((random() * 200).toFixed(2))]);
    }

    return {
      ...layer,
      stars,
      // `var(--star)` rather than a literal: the field has to follow the light/dark
      // switch, and no hex belongs outside tokens.css.
      boxShadow: stars.map(([x, y]) => `${x}vw ${y}vh 0 0 var(--star)`).join(", "),
    };
  });
}
