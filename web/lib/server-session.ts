/**
 * Server-side session lookup, and the one guard every protected page uses.
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
import { redirect } from "next/navigation";
import { cache } from "react";

import { API_BASE } from "./api";
import type { Me } from "./session";

/**
 * Fetch the signed-in user, or null when there is no valid session.
 *
 * Wrapped in React's `cache()`, which memoises per request — not across requests.
 * That distinction matters: the `no-store` below is still correct and still load
 * bearing, because a cached *response* would hand one visitor another's identity,
 * whereas a memoised call within one render pass cannot. Without it, the layout and
 * the page each ask the API independently, so every protected page cost two
 * round-trips to learn one fact.
 *
 * @returns The principal, or null for anonymous or expired sessions.
 */
export const getServerSession = cache(async (): Promise<Me | null> => {
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
});

/**
 * Require a session, and optionally a capability, or redirect.
 *
 * Two destinations, and the difference is deliberate: no session sends you to the
 * sign-in page, because signing in fixes it; an insufficient role sends you to the
 * dashboard, because signing in again will not. Every role has a dashboard.
 *
 * This exists because the three guarded pages had each spelled the check themselves
 * and had drifted — one sent a rejected admin to `/students`, another to
 * `/dashboard`, and a third only checked for a single role by string comparison.
 *
 * @param locale - The active locale, for building the redirect target.
 * @param allowed - Optional capability check, normally a predicate from
 *   `lib/permissions.ts` such as `can.viewReports`.
 * @returns The principal, once both checks pass.
 */
export async function requireSession(
  locale: string,
  allowed?: (me: Me) => boolean,
): Promise<Me> {
  const me = await getServerSession();
  if (!me) redirect(`/${locale}/login`);
  if (allowed && !allowed(me)) redirect(`/${locale}/dashboard`);
  return me;
}
