"use client";

/**
 * The signed-in user.
 *
 * One query, cached under a single key, so every component that needs the role
 * shares one request rather than each asking the server independently.
 */

import { useQuery } from "@tanstack/react-query";

import { api, ApiError, type Response } from "./api";

export type Me = Response<"/auth/me", "get">;
export type Role = Me["role"];

/** Ranked low to high; index is the rank. */
const RANK: readonly string[] = ["student", "teacher", "admin", "superadmin"];

/** True when `role` is at least `minimum` in the hierarchy. */
export function atLeast(role: string | undefined, minimum: Role): boolean {
  if (!role) return false;
  return RANK.indexOf(role) >= RANK.indexOf(minimum);
}

export const SESSION_KEY = ["auth", "me"] as const;

export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => api<Me>("/auth/me"),
    // A signed-out visitor is a normal state, not a failure to retry. Returning
    // null rather than throwing keeps `isError` meaningful for real faults.
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/** True when the error means "not signed in". */
export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
