"use client";

/**
 * One way to turn a thrown value into something a person can read.
 *
 * `error instanceof ApiError ? error.code : "NETWORK_ERROR"` was written out
 * forty-five times across sixteen files, and the result was then rendered through
 * two different conventions — ``t(`error.${code}` as "error.unknown")`` in eight
 * files and `tError(code as "unknown")` in eight others. Between them they carried
 * forty-eight `as` assertions, which were the only type escapes in an otherwise
 * `any`-free codebase.
 *
 * The assertion is unavoidable: next-intl types message keys literally, and an error
 * code is only known at runtime. What it should not be is unavoidable *forty-eight
 * times*. It lives here now, once, next to the reason it is safe —
 * `lib/__tests__/i18n.test.ts` asserts every backend error code has a message in
 * every locale, so the lookup cannot miss.
 */

import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api";

/**
 * The stable code behind a thrown value.
 *
 * @param error - Anything a mutation or query rejected with.
 * @returns The API's error code, or `NETWORK_ERROR` when the request never arrived.
 */
export function errorCode(error: unknown): string {
  return error instanceof ApiError ? error.code : "NETWORK_ERROR";
}

/**
 * Translate a thrown value into the reader's language.
 *
 * @returns A function taking anything thrown and returning a localized sentence.
 *   `null` in, `null` out, so it can be called unconditionally on a nullable error.
 */
export function useApiError(): (error: unknown) => string {
  const t = useTranslations("error");
  return (error: unknown) => t(errorCode(error) as "unknown");
}

/**
 * Translate a bare code that has already been extracted.
 *
 * Some screens hold the code in state rather than the error — the import wizard
 * keeps one across a four-step flow — so they need the second half alone.
 *
 * @returns A function taking a code and returning a localized sentence.
 */
export function useErrorMessage(): (code: string | null | undefined) => string | null {
  const t = useTranslations("error");
  return (code: string | null | undefined) => (code ? t(code as "unknown") : null);
}
