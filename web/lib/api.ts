/**
 * Typed API client.
 *
 * Paths and shapes come from `lib/api-schema.d.ts`, generated from the committed
 * `docs/openapi.json`. A backend field rename therefore becomes a compile error
 * here rather than `undefined` at runtime.
 *
 * Run `pnpm gen:api` after any backend change.
 */

import type { paths } from "./api-schema";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** An error carrying the machine code from an RFC-9457 problem response. */
export class ApiError extends Error {
  constructor(
    /** Stable identifier the UI translates, e.g. `STUDENT_NOT_FOUND`. */
    readonly code: string,
    readonly status: number,
    /** Structured values to interpolate into the translated message. */
    readonly context: Record<string, unknown> = {},
  ) {
    // The message is for the console. Never render it — it is only ever English.
    super(`${code} (${status})`);
    this.name = "ApiError";
  }
}

type Path = keyof paths;

interface RequestOptions {
  // PUT as well as PATCH: the routing and i18n-override endpoints are genuinely
  // idempotent replacements of a whole record, not partial updates.
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

/**
 * Call the API.
 *
 * Always sends credentials: authentication is an HttpOnly session cookie, which
 * the browser omits on cross-origin requests unless asked.
 *
 * @param path - An API path from the generated schema.
 * @param options - Method, body, query parameters.
 * @returns The parsed response body, or undefined for `204 No Content`.
 * @throws ApiError - On any non-2xx response.
 */
export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  const multipart = typeof FormData !== "undefined" && body instanceof FormData;

  const url = new URL(path, API_BASE);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    method,
    credentials: "include",
    signal,
    headers: body !== undefined && !multipart ? { "content-type": "application/json" } : undefined,
    body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
  });

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      payload?.code ?? "NETWORK_ERROR",
      response.status,
      payload?.context ?? {},
    );
  }

  return payload as T;
}

/**
 * Response body of a path and method, from the generated schema.
 *
 * Both 200 and 201 are matched. Only checking 200 silently resolved every
 * created-resource endpoint to `never`, which does not fail where the type is
 * declared — it fails later, at the first property access, with a message that
 * points at the wrong line.
 */
export type Response<P extends Path, M extends keyof paths[P]> = paths[P][M] extends {
  responses: { 200: { content: { "application/json": infer R } } };
}
  ? R
  : paths[P][M] extends {
        responses: { 201: { content: { "application/json": infer R } } };
      }
    ? R
    : never;
