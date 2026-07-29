"use client";

/**
 * Light / dark / auto, with auto as the default — and no script.
 *
 * The usual pre-hydration script exists because the server cannot know the
 * visitor's theme. Two changes remove the need for it:
 *
 * - **An explicit choice lives in a cookie**, which the server reads, so the class
 *   is on `<html>` in the first byte of the response.
 * - **"Follow the system" is answered by CSS.** `tokens.css` carries the dark
 *   values under `@media (prefers-color-scheme: dark)` for a document with no
 *   explicit class, so the OS preference applies before any JavaScript runs.
 *
 * The result is no flash, no `<script>` for React to warn about, and a theme that
 * still works with JavaScript switched off entirely.
 *
 * This component now only handles *changing* the theme, and reading back what is
 * currently in force.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { COOKIE, COOKIE_MAX_AGE, type Theme } from "./theme";

export type { Theme };

interface ThemeContextValue {
  /** What the user chose. `system` means "let CSS follow the OS". */
  theme: Theme;
  /** What that currently resolves to. Never `system`. */
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// ── The external store ───────────────────────────────────────────────────────
//
// The class on <html> is the source of truth, because the server wrote it and CSS
// may be overriding it. Reading the DOM rather than mirroring it in state is what
// keeps the toggle honest about what is actually on screen.

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // The OS switching while the tab is open changes what "system" resolves to.
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  query.addEventListener("change", emit);
  return () => {
    listeners.delete(onChange);
    query.removeEventListener("change", emit);
  };
}

/**
 * The snapshot: the explicit choice and what is currently rendered.
 *
 * A string rather than an object — `useSyncExternalStore` compares by identity,
 * and a fresh object per call is an infinite render loop.
 */
function getSnapshot(): string {
  const root = document.documentElement;
  const explicit = root.classList.contains("dark")
    ? "dark"
    : root.classList.contains("light")
      ? "light"
      : "";
  const resolved =
    explicit || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  return `${explicit}|${resolved}`;
}

/** On the server there is no DOM and no OS query. */
function getServerSnapshot(): string {
  return "|light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [explicit, resolved] = snapshot.split("|");

  const setTheme = useCallback((next: Theme) => {
    // SameSite=Lax so it survives ordinary navigation without riding along on
    // cross-site requests. Not HttpOnly — this one is deliberately readable, and
    // it carries nothing worth protecting.
    document.cookie = `${COOKIE}=${next}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;

    // Applied immediately rather than waiting for a navigation to pick the cookie
    // up. Removing both classes hands the decision back to the media query, which
    // is exactly what "system" means.
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    if (next !== "system") root.classList.add(next);

    emit();
  }, []);

  const value = useMemo(
    () => ({
      theme: (explicit || "system") as Theme,
      resolvedTheme: (resolved === "dark" ? "dark" : "light") as "light" | "dark",
      setTheme,
    }),
    [explicit, resolved, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/**
 * Read the current theme and change it.
 *
 * @returns The chosen theme, what it resolves to, and a setter.
 * @throws Error - When called outside a provider. That is a wiring mistake, not a
 *   state the interface should try to render around.
 */
export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}

