"use client";

/**
 * Language switcher.
 *
 * Navigates rather than setting a cookie, because the locale lives in the path.
 * `usePathname` from next-intl returns the path *without* the locale prefix, so
 * swapping languages preserves the current page instead of dropping the user home.
 */

import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import { locales } from "@/i18n/routing";
import { useTransition } from "react";

const NAMES: Record<string, string> = { en: "EN", de: "DE", fr: "FR" };

export function LocaleSwitcher({ label }: { label: string }) {
  const active = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-lg border border-line bg-surface p-0.5"
      data-pending={pending || undefined}
    >
      {locales.map((locale) => (
        <button
          key={locale}
          type="button"
          role="radio"
          aria-checked={locale === active}
          lang={locale}
          onClick={() =>
            startTransition(() => {
              router.replace(pathname, { locale });
            })
          }
          className={`numeric rounded-md px-2 py-1 text-xs transition-colors ${
            locale === active
              ? "bg-brand text-brand-contrast"
              : "text-muted hover:bg-bg-subtle hover:text-text"
          }`}
        >
          {NAMES[locale] ?? locale.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
