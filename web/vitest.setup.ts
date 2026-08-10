/**
 * Shared setup for every test file.
 *
 * `@testing-library/jest-dom` adds the matchers that make a failure readable —
 * `toBeDisabled()` reports which element and what state, where a raw
 * `expect(el.disabled).toBe(true)` reports `false !== true` and leaves you guessing.
 *
 * Safe to load for the node-environment files too: the matchers register against
 * vitest's `expect` and touch no DOM until one is used.
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest does not reset the document between tests in a file. Without this the
// second render finds two copies of everything and `getByRole` throws on the
// ambiguity — a failure that reads like a component bug and is not one.
afterEach(cleanup);

// jsdom implements no layout, so it ships no ResizeObserver. cmdk constructs one
// when its dialog opens, and the resulting ReferenceError surfaces as an uncaught
// exception rather than a test failure, which points nowhere near the cause.
//
// A no-op is honest here: there is nothing to observe without layout, and a test
// that depended on a real measurement would be testing jsdom.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver;
}

// Same gap, same reason: scrolling an element into view is a layout operation, and
// cmdk performs one whenever the highlighted item changes. Absent, it throws inside
// a layout effect, which React reports as a component error rather than a missing
// browser API.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {};
}
