"use client";

/**
 * TanStack Query provider.
 *
 * The client is created inside `useState` rather than at module scope. A
 * module-level client is shared by every request the server process handles,
 * which on a server-rendered app means one user's cached grades can be served
 * into another user's page.
 */

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "@/i18n/navigation";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";

export function QueryProvider({ children }: { children: ReactNode }) {
  const router = useRouter();

  const [client] = useState(() => {
    // A session that expires mid-visit used to leave the page broken rather than
    // sending anyone anywhere: the retry rule below already said it "delays the
    // redirect to the sign-in page", but no redirect existed. The detail panel
    // showed an error, the list beside it went blank, and the reports screen —
    // which renders nothing on failure — became indistinguishable from an
    // institution with no data. The only way out was knowing to reload.
    //
    // Handled on the caches rather than in each view so that a query added later
    // is covered by construction. `replace` rather than `push`: the expired page
    // is not somewhere the back button should return to.
    const toSignIn = (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        // Locale-aware: the bare `next/navigation` router drops the prefix and
        // would land a German user on the English sign-in page.
        router.replace("/login");
      }
    };

    return new QueryClient({
      queryCache: new QueryCache({ onError: toSignIn }),
      mutationCache: new MutationCache({ onError: toSignIn }),
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          // Retrying a 401 or a 403 cannot succeed — the session is not going to
          // become valid on the second attempt — and it delays the redirect to
          // the sign-in page by the length of the backoff.
          retry: (failureCount, error) => {
            if (error instanceof ApiError && error.status < 500) return false;
            return failureCount < 2;
          },
        },
      },
    });
  });

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
