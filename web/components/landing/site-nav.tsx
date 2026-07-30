"use client";

/**
 * Landing-page navigation that condenses once the hero is behind you.
 *
 * The scroll listener is passive and writes a boolean, not a style — the actual
 * change is a CSS transition on a data attribute. Setting height or padding from
 * the scroll handler would lay out the page on every frame.
 */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { LocaleSwitcher } from "@/components/ui/locale-switcher";
import { ThemeToggle } from "@/components/theme/theme-toggle";

export function SiteNav({ appName }: { appName: string }) {
  const t = useTranslations("landing.nav");
  const tLocale = useTranslations("locale");
  const [condensed, setCondensed] = useState(false);

  useEffect(() => {
    const onScroll = () => setCondensed(window.scrollY > 24);
    onScroll(); // Runs once: a reload part-way down the page should start condensed.
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      data-condensed={condensed || undefined}
      className="sticky top-0 z-50 border-b border-transparent transition-[background-color,border-color,padding] duration-300 data-condensed:border-line data-condensed:bg-bg/80 data-condensed:backdrop-blur-md"
    >
      {/* The attribute is repeated here deliberately: Tailwind's `data-*` variant
          compiles to `[data-condensed]` on the *same* element, so the header's copy
          does not reach this child. */}
      <nav
        data-condensed={condensed || undefined}
        className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-5 transition-[padding] duration-300 data-condensed:py-3"
      >
        <Link href="/" className="text-sm font-medium tracking-tight text-text">
          {appName}
        </Link>

        {/* Hidden below `sm` rather than wrapped: two anchor links are not worth a
            mobile menu, and the sections are reachable by scrolling anyway. */}
        <div className="hidden gap-5 text-sm text-muted sm:flex">
          <a href="#features" className="transition-colors hover:text-text">
            {t("features")}
          </a>
          <a href="#how" className="transition-colors hover:text-text">
            {t("how")}
          </a>
        </div>

        <div className="ms-auto flex items-center gap-2">
          <LocaleSwitcher label={tLocale("label")} />
          <ThemeToggle />
          <Link
            href="/dashboard"
            className="rounded-lg bg-brand px-3 py-1.5 text-sm text-brand-contrast transition-opacity hover:opacity-90"
          >
            {t("signIn")}
          </Link>
        </div>
      </nav>
    </header>
  );
}
