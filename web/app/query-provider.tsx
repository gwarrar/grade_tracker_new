"use client";

/**
 * TanStack Query provider.
 *
 * The client is created inside `useState` rather than at module scope. A
 * module-level client is shared by every request the server process handles,
 * which on a server-rendered app means one user's cached grades can be served
 * into another user's page.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
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
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
