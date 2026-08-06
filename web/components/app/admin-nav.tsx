"use client";

/**
 * Sub-navigation for the administrative area.
 *
 * Five settings pages had five header tabs, which pushed the tabs a normal user
 * cares about — students, courses, grades — into the corner of the bar. They live
 * under one Admin tab now, and this is the second row.
 *
 * Derived from {@link APP_ROUTES} rather than a list of its own: a page added to
 * /admin/ appears here by existing, which is harder to forget than an edit in two
 * places. Filtered by role for the same reason the header is — branding and the AI
 * providers are superadmin-only, and an admin should not be shown a door that
 * answers with a redirect.
 */

import { useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";
import { APP_ROUTES } from "@/lib/app-routes";
import { atLeast, type Me } from "@/lib/session";

const SECTIONS = APP_ROUTES.filter((route) => route.href.startsWith("/admin/"));

export function AdminNav({ me }: { me: Me }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const visible = SECTIONS.filter((section) => atLeast(me.role, section.min));

  return (
    <nav className="mb-8 flex flex-wrap gap-1 border-b border-line pb-3 text-sm" aria-label={t("admin")}>
      {visible.map((section) => {
        const active = pathname === section.href || pathname.startsWith(`${section.href}/`);
        return (
          <Link
            key={section.href}
            href={section.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 transition-colors ${
              active ? "bg-bg-subtle font-medium text-text" : "text-muted hover:text-text"
            }`}
          >
            {t(section.key)}
          </Link>
        );
      })}
    </nav>
  );
}
