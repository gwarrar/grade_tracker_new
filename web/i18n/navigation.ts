/**
 * Locale-aware navigation helpers.
 *
 * These wrappers keep the active locale in the path automatically. Using the bare
 * `next/link` and `next/navigation` equivalents would drop the prefix and bounce a
 * German user to the English page on every internal link.
 */

import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
