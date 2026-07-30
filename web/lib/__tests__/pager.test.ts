/**
 * Page arithmetic, which is the only logic in the pager.
 *
 * The two cases that go wrong in every hand-rolled pager: an empty list reporting
 * "Page 1 of 0", and an exact multiple gaining a trailing empty page.
 */

import { describe, expect, it } from "vitest";

import { pageCount } from "../pager";

describe("pageCount", () => {
  it("an empty list is one page, not zero", () => {
    // "Page 1 of 0" reads as broken, and there is always a page to show — it is just
    // empty, which the table's own empty state explains.
    expect(pageCount(0, 50)).toBe(1);
  });

  it("a partial page counts", () => {
    expect(pageCount(1, 50)).toBe(1);
    expect(pageCount(51, 50)).toBe(2);
  });

  it("an exact multiple gains no trailing page", () => {
    expect(pageCount(50, 50)).toBe(1);
    expect(pageCount(100, 50)).toBe(2);
  });

  it("a page larger than the total is still one page", () => {
    expect(pageCount(3, 50)).toBe(1);
  });

  it("survives a nonsense size rather than dividing by zero", () => {
    // Guards against a caller passing 0 from an uninitialised state and getting
    // Infinity pages.
    expect(pageCount(10, 0)).toBe(1);
    expect(pageCount(10, -5)).toBe(1);
  });
});
