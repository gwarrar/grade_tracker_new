/**
 * Server-side session lookup.
 *
 * The guard runs on the server rather than in the browser so a signed-out visitor
 * never sees the application shell at all. A client-side guard renders the nav,
 * discovers there is no session, and only then redirects — a flash of an interface
 * the visitor is not entitled to.
 *
 * The session cookie is HttpOnly, so it has to be forwarded by hand: server-side
 * `fetch` carries no cookie jar.
 */

import { cookies } from "next/headers";

import { API_BASE } from "./api";
import type { Me } from "./session";

/**
 * Fetch the signed-in user, or null when there is no valid session.
 *
 * @returns The principal, or null for anonymous or expired sessions.
 */
export async function getServerSession(): Promise<Me | null> {
  const jar = await cookies();
  const header = jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  if (!header) return null;

  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      headers: { cookie: header },
      // Never cached: a stale hit here would hand one visitor another's identity.
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as Me;
  } catch {
    // The API being unreachable is not the same as being signed out, but from the
    // page's point of view the outcome is identical — it cannot render.
    return null;
  }
}
