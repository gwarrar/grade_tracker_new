/**
 * The signed-in user's shape, and the role hierarchy.
 *
 * Deliberately **not** a client module and deliberately **not** a hook. `me` is
 * fetched once per request by the server layout (`lib/server-session.ts`) and passed
 * down as a prop; there is exactly one way to learn the current role.
 *
 * There used to be a `useSession()` here as well, fetching `/auth/me` again from the
 * browser. Nothing imported it — which was lucky, because two independent sources for
 * the same fact is how a server guard and a client gate drift apart: the page decides
 * you may not be here, the component decides you may edit, and only one of them is
 * right. Keeping this file free of React also lets a server component import
 * {@link atLeast} without pulling a client boundary along with it.
 */

import type { Response } from "./api";

export type Me = Response<"/auth/me", "get">;
export type Role = Me["role"];

/** Ranked low to high; index is the rank. */
const RANK: readonly string[] = ["student", "teacher", "admin", "superadmin"];

/**
 * True when `role` is at least `minimum` in the hierarchy.
 *
 * Mirrors `Principal.can()` in `services/scoping.py`. The backend remains the
 * enforcement point; this only decides what is worth rendering.
 *
 * @param role - The signed-in user's role, or undefined when there is no session.
 * @param minimum - The rank required.
 */
export function atLeast(role: string | undefined, minimum: Role): boolean {
  if (!role) return false;
  return RANK.indexOf(role) >= RANK.indexOf(minimum);
}
