/**
 * The starfield must be the same field every time.
 *
 * The landing page is statically rendered once per locale. With `Math.random()` the
 * English, German and French builds would each get a different sky — three pages
 * claiming to be one design — and every rebuild would churn the output. So the
 * positions come from a seeded generator, and this file is what stops someone
 * "simplifying" it back to `Math.random()`.
 *
 * The generator is the only non-trivial logic in the component: a loop producing
 * coordinates. Everything else is CSS.
 */

import { describe, expect, it } from "vitest";

import { starLayers } from "../starfield";

describe("starLayers", () => {
  it("is deterministic for a given seed", () => {
    expect(starLayers(1234)).toEqual(starLayers(1234));
  });

  it("gives different seeds different skies", () => {
    // Guards the test above: two identical calls would also be "deterministic" if
    // the function ignored its seed entirely.
    expect(starLayers(1234)).not.toEqual(starLayers(5678));
  });

  it("produces three layers, near to far", () => {
    const layers = starLayers(1);

    expect(layers).toHaveLength(3);
    // Denser, smaller and slower with distance — that ordering is the parallax.
    expect(layers.map((l) => l.count)).toEqual([...layers.map((l) => l.count)].sort((a, b) => a - b));
    expect(layers[0]!.size).toBeGreaterThan(layers[2]!.size);
    expect(layers[0]!.duration).toBeLessThan(layers[2]!.duration);
    expect(layers[0]!.opacity).toBeGreaterThan(layers[2]!.opacity);
  });

  it("keeps every star inside the field", () => {
    // x over one viewport width, y over two viewport heights — the second height is
    // what the drift scrolls into, so a star beyond it would pop in mid-loop.
    for (const layer of starLayers(99)) {
      expect(layer.stars).toHaveLength(layer.count);
      for (const [x, y] of layer.stars) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThan(100);
        expect(y).toBeGreaterThanOrEqual(0);
        expect(y).toBeLessThan(200);
      }
    }
  });

  it("emits a box-shadow entry per star, referencing the token", () => {
    const [near] = starLayers(7);
    if (!near) throw new Error("starLayers must produce a near layer");

    // No hex literal outside tokens.css — the star colour has to stay a variable, or
    // the field would not follow the light/dark switch.
    expect(near.boxShadow.split(",")).toHaveLength(near.count);
    expect(near.boxShadow).toContain("var(--star)");
    expect(near.boxShadow).not.toMatch(/#[0-9a-f]{3,6}/i);
  });
});
