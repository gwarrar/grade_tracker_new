/**
 * Theme values shared by the server and the client.
 *
 * A separate module with no `"use client"` directive, because the server layout
 * reads the cookie and the client provider writes it. Exporting these from the
 * provider made them client-only, and calling one from the server is an error
 * rather than a subtle bug — which is how this file came to exist.
 */

export type Theme = "light" | "dark" | "system";

/** Cookie name. Read by the server layout, written by the provider. */
export const COOKIE = "theme";

/** A year. A theme preference is how someone likes to read, not a session detail. */
export const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

/**
 * Coerce an arbitrary cookie or configured value to a known theme.
 *
 * @param value - Whatever was stored or configured.
 * @returns One of the three themes; anything unrecognised becomes `system`.
 */
export function normalise(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}
