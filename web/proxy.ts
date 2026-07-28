/**
 * Locale negotiation.
 *
 * Next 16 renamed the `middleware` convention to `proxy`; the edge runtime is not
 * supported here, and the runtime is `nodejs` and not configurable. See
 * `node_modules/next/dist/docs/01-app/02-guides/upgrading/version-16.md`.
 */

import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Everything except API routes, Next internals and anything with a file
  // extension. Without the extension exclusion, /logo.svg becomes /en/logo.svg and
  // every static asset 404s.
  matcher: ["/((?!api|_next|_vercel|.*\..*).*)"],
};
