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
import { useTranslations } from "next-intl";

import { useHydrated } from "@/lib/use-hydrated";

const OPTIONS = [
  { value: "light", glyph: "☀" },
  { value: "dark", glyph: "☾" },
  { value: "system", glyph: "◐" },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("theme");

  // The server cannot know the stored preference, so the first render must not
  // depend on it. Rendering the real state before hydration is the classic
  // next-themes mismatch.
  const hydrated = useHydrated();

  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="inline-flex rounded-lg border border-line bg-surface p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = hydrated && theme === option.value;
        const label = t(option.value);
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setTheme(option.value)}
            title={label}
            className={`rounded-md px-2.5 py-1 text-sm transition-colors ${
              active
                ? "bg-brand text-brand-contrast"
                : "text-muted hover:bg-bg-subtle hover:text-text"
            }`}
          >
            <span aria-hidden>{option.glyph}</span>
            <span className="sr-only">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
