"use server";

import { updateTag } from "next/cache";

import { BRANDING_TAG } from "@/components/branding/branding";

/**
 * Drop the cached branding read after a save.
 *
 * The layout reads branding on the critical path of every page, so it is cached.
 * Without this the administrator who just changed a colour keeps seeing the old
 * one, and the form repopulates from the stale read — which looks exactly like the
 * save having failed.
 *
 * `updateTag` rather than `revalidateTag`: this runs inside a server action right
 * after the write, which is the read-your-own-writes case it exists for.
 * `revalidateTag` would also need a cache profile it has no reason to choose.
 */
export async function refreshBranding(): Promise<void> {
  updateTag(BRANDING_TAG);
}
