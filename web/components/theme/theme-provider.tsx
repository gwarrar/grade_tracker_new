"use client";

/**
 * Light / dark / auto, with auto as the default.
 *
 * `next-themes` rather than a hand-rolled toggle, for the pre-hydration inline
 * script it injects. Without one, a user whose system is dark sees a flash of the
 * light theme on every page load — the server cannot know the preference, so the
 * first paint is always wrong until a script corrects it. Getting that script right
 * (and the SSR/client hydration mismatch, and reacting to an OS theme change while
 * the tab is open) is the entire reason to take the dependency.
 */

import { ThemeProvider as NextThemes } from "next-themes";
import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** The organisation's default, used for anyone with no stored preference. */
  defaultTheme?: string;
}

export function ThemeProvider({ children, defaultTheme = "system" }: Props) {
  return (
    <NextThemes
      attribute="class"
      defaultTheme={defaultTheme}
      enableSystem
      // The transition would otherwise animate every colour on the page at once
      // when switching, which reads as a slow smear rather than a mode change.
      disableTransitionOnChange
    >
      {children}
    </NextThemes>
  );
}
