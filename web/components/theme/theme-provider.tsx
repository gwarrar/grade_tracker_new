"use client";

/**
 * Light / dark / auto, with auto as the default.
 *
 * Hand-rolled rather than `next-themes`, for one reason: that library renders its
 * pre-hydration script from inside a client component, which React 19 warns about
 * on every page load and — the part that actually matters — puts the script in
 * `<body>` instead of `<head>`. Ours is a server component in the head, where it
 * runs before the browser paints anything.
 *
 * The state is read with `useSyncExternalStore`, because that is what it is: two
 * external stores, `localStorage` and the OS colour-scheme query. Reading them
 * into `useState` from an effect would mean a second render on every mount and a
 * flash of the wrong toggle state — and it is the pattern React 19's lint objects
 * to, correctly.
 */

import { useCallback, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { createContext, useContext } from "react";

import { STORAGE_KEY } from "./theme-script";

export type Theme = "light" | "dark" | "system";

interface ThemeContextValue {
  /** What the user chose. `system` means "follow the OS". */
  theme: Theme;
  /** What that currently resolves to. Never `system`. */
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// ── The external store ───────────────────────────────────────────────────────

const listeners = new Set<() => void>();

/** Tell React the snapshot changed. */
function emit(): void {
  for (const listener of listeners) listener();
}

/**
 * Subscribe to everything that can change the theme underneath us.
 *
 * Two sources beyond our own setter: the OS switching scheme while the tab is
 * open (someone whose machine changes at sunset should not have to reload), and
 * another tab writing a new preference (`storage` fires only in *other* tabs,
 * which are exactly the ones that would otherwise drift).
 */
function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) emit();
  };

  query.addEventListener("change", emit);
  window.addEventListener("storage", onStorage);

  return () => {
    listeners.delete(onChange);
    query.removeEventListener("change", emit);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * The snapshot, as a string.
 *
 * A primitive rather than an object on purpose: `useSyncExternalStore` compares
 * snapshots by identity, and a fresh object every call is an infinite render loop.
 */
function getSnapshot(): string {
  return `${readStored() ?? ""}|${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;
}

/** On the server there is no storage and no OS query — only the default. */
function getServerSnapshot(): string {
  return "|light";
}

// ── The provider ─────────────────────────────────────────────────────────────

export function ThemeProvider({
  children,
  defaultTheme = "system",
}: {
  children: ReactNode;
  /** The organisation's default, for anyone with no stored preference. */
  defaultTheme?: string;
}) {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [stored, systemResolved] = snapshot.split("|");

  const theme = stored ? normalise(stored) : normalise(defaultTheme);
  const resolvedTheme: "light" | "dark" =
    theme === "system" ? (systemResolved === "dark" ? "dark" : "light") : theme;

  // Writing to the DOM is a genuine effect — synchronising an external system with
  // React state, which is what effects are for. The inline script has already done
  // this for the first paint; this keeps it true afterwards.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
    // Tells the browser which built-in controls and scrollbars to draw, so they
    // match the page rather than staying stubbornly light.
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked. Nothing is persisted, but `emit` below still applies the
      // choice for this page — better than the click appearing to do nothing.
    }
    emit();
  }, []);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
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

/** Coerce an arbitrary stored or configured string to a known theme. */
export function normalise(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

/** Read the stored preference, tolerating a browser that blocks storage. */
function readStored(): Theme | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === null ? null : normalise(raw);
  } catch {
    return null;
  }
}
