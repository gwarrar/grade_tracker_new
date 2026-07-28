"use client";

/**
 * True once the client has hydrated, false during server rendering.
 *
 * The obvious spelling — `useState(false)` plus an effect that sets it true — is
 * a setState-in-effect, which triggers a second render pass on every mount and is
 * flagged by the React compiler lint. `useSyncExternalStore` expresses the same
 * thing as what it actually is: two different snapshots for two environments.
 *
 * The subscribe callback never fires, because the value transitions exactly once,
 * at hydration, and React re-renders then anyway.
 */

import { useSyncExternalStore } from "react";

const noop = () => () => {};
const onClient = () => true;
const onServer = () => false;

export function useHydrated(): boolean {
  return useSyncExternalStore(noop, onClient, onServer);
}
