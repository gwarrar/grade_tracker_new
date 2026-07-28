"use client";

/**
 * Light / dark / auto switcher.
 *
 * Three states, not two. A binary toggle cannot express "follow my system", which
 * is the only setting that is correct both at midday and at midnight — and it is
 * the default, so a two-way switch would silently discard it the first time anyone
 * touched it.
 */

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

const OPTIONS = [
  { value: "light", label: "Light", glyph: "☀" },
  { value: "dark", label: "Dark", glyph: "☾" },
  { value: "system", label: "Auto", glyph: "◐" },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // The server cannot know the stored preference, so the first render must not
  // depend on it. Rendering the real state before mount is the classic next-themes
  // hydration mismatch.
  useEffect(() => setMounted(true), []);

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex rounded-lg border border-line bg-surface p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = mounted && theme === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setTheme(option.value)}
            title={option.label}
            className={`rounded-md px-2.5 py-1 text-sm transition-colors ${
              active
                ? "bg-brand text-brand-contrast"
                : "text-muted hover:bg-bg-subtle hover:text-text"
            }`}
          >
            <span aria-hidden>{option.glyph}</span>
            <span className="sr-only">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
