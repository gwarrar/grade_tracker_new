/**
 * Marketing landing page.
 *
 * A server component. The only client JavaScript here is the navigation (which
 * needs a scroll listener), the palette demo, and the reveal wrappers — everything
 * else is rendered on the server and shipped as HTML.
 *
 * The grading scale advertised in the band strip is read from the organisation
 * record rather than hardcoded, so the page always shows the scale actually in
 * force rather than the one that happened to be true when it was written.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { getBranding } from "@/components/branding/branding";
import { Reveal } from "@/components/landing/reveal";
import { SiteNav } from "@/components/landing/site-nav";
import { TypingDemo } from "@/components/landing/typing-demo";
import { Link } from "@/i18n/navigation";
import { API_BASE } from "@/lib/api";
import { locales } from "@/i18n/routing";

interface Props {
  params: Promise<{ locale: string }>;
}

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return {
    title: `${t("app.name")} — ${t("landing.hero.eyebrow")}`,
    description: t("landing.hero.subtitle"),
    // hreflang, so a French search result points at /fr rather than /en. Free
    // here because the locale is already a path segment.
    alternates: {
      languages: Object.fromEntries(locales.map((l) => [l, `/${l}`])),
    },
  };
}

export default async function Landing({ params }: Props) {
  // Next 16: params is a Promise, and setRequestLocale is what allows this page to
  // stay statically rendered despite reading the request locale.
  const { locale } = await params;
  setRequestLocale(locale);

  const [t, branding] = await Promise.all([getTranslations(), getBranding()]);

  // Keyed by the same names as the message catalogue, so adding a fourth demo is a
  // catalogue edit plus one entry here — no component change.
  const demos = (["average", "risk", "trend"] as const).map((key) => ({
    query: t(`landing.demos.${key}.query`),
    result: t(`landing.demos.${key}.result`),
  }));

  const features = (["scoped", "fast", "ai"] as const).map((key) => ({
    key,
    title: t(`landing.features.${key}.title`),
    body: t(`landing.features.${key}.body`),
  }));

  const steps = (["one", "two", "three"] as const).map((key, position) => ({
    key,
    number: position + 1,
    title: t(`landing.how.${key}.title`),
    body: t(`landing.how.${key}.body`),
  }));

  return (
    <div className="relative min-h-dvh bg-bg">
      {/* Film grain. An inline SVG turbulence filter rather than an image: it costs
          no request, tiles at any size, and `pointer-events-none` keeps it from ever
          intercepting a click. Hidden from assistive technology entirely. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.035] mix-blend-overlay dark:opacity-[0.06]"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />

      <div className="relative z-10">
        <SiteNav appName={t("app.name")} />

        <main>
          {/* ── Hero ─────────────────────────────────────────────────────────── */}
          <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-24 pt-16 lg:grid-cols-2 lg:gap-16 lg:pt-24">
            <div>
              <Reveal>
                <p className="numeric text-xs uppercase tracking-[0.18em] text-subtle">
                  {t("landing.hero.eyebrow")}
                </p>
              </Reveal>

              <Reveal delay={0.06}>
                <h1 className="mt-4 text-balance text-4xl font-semibold leading-[1.08] tracking-tight text-text sm:text-5xl lg:text-6xl">
                  {t("landing.hero.title")}
                </h1>
              </Reveal>

              <Reveal delay={0.12}>
                <p className="mt-5 max-w-lg text-pretty text-base leading-relaxed text-muted sm:text-lg">
                  {t("landing.hero.subtitle")}
                </p>
              </Reveal>

              <Reveal delay={0.18}>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <Link
                    href="/students"
                    className="rounded-lg bg-brand px-5 py-2.5 text-sm font-medium text-brand-contrast transition-opacity hover:opacity-90"
                  >
                    {t("landing.hero.cta")}
                  </Link>
                  <a
                    href="#how"
                    className="rounded-lg border border-line px-5 py-2.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-text"
                  >
                    {t("landing.hero.secondary")}
                  </a>
                </div>
              </Reveal>
            </div>

            <Reveal delay={0.24}>
              <TypingDemo demos={demos} hint={t("landing.palette.hint")} />
            </Reveal>
          </section>

          {/* ── The grading scale actually in force ──────────────────────────── */}
          <section className="border-y border-line bg-bg-subtle">
            <div className="mx-auto flex max-w-6xl flex-wrap justify-center gap-x-10 gap-y-3 px-6 py-6">
              {branding.grading_scale.map((band) => (
                <span key={band.label} className="numeric text-sm text-muted">
                  <span className="font-medium text-text">{band.label}</span>
                  <span className="ms-2 text-subtle">≥ {band.min_percentage}%</span>
                </span>
              ))}
            </div>
          </section>

          {/* ── Features ─────────────────────────────────────────────────────── */}
          <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24">
            <Reveal>
              <h2 className="max-w-2xl text-balance text-3xl font-semibold tracking-tight text-text sm:text-4xl">
                {t("landing.features.title")}
              </h2>
            </Reveal>

            <div className="mt-12 grid gap-8 md:grid-cols-3">
              {features.map((feature, position) => (
                <Reveal key={feature.key} delay={position * 0.08}>
                  <article className="h-full rounded-xl border border-line bg-surface p-6">
                    <h3 className="text-base font-medium text-text">{feature.title}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-muted">{feature.body}</p>
                  </article>
                </Reveal>
              ))}
            </div>
          </section>

          {/* ── How it works ─────────────────────────────────────────────────── */}
          <section id="how" className="border-t border-line bg-bg-subtle">
            <div className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24">
              <Reveal>
                <h2 className="max-w-2xl text-balance text-3xl font-semibold tracking-tight text-text sm:text-4xl">
                  {t("landing.how.title")}
                </h2>
              </Reveal>

              <ol className="mt-12 grid list-none gap-10 md:grid-cols-3">
                {steps.map((step, position) => (
                  <li key={step.key}>
                    <Reveal delay={position * 0.08}>
                      <span className="numeric flex size-8 items-center justify-center rounded-full border border-line-strong text-sm text-muted">
                        {step.number}
                      </span>
                      <h3 className="mt-4 text-base font-medium text-text">{step.title}</h3>
                      <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
                    </Reveal>
                  </li>
                ))}
              </ol>
            </div>
          </section>
        </main>

        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-subtle">
            <p>{t("landing.footer.built")}</p>
            {/* FastAPI serves its own Swagger UI, which lives on the API origin —
                a different host in development. Built from API_BASE rather than
                written as "/docs", which would resolve against the frontend and
                404. */}
            <a
              href={`${API_BASE}/docs`}
              rel="noreferrer"
              className="transition-colors hover:text-text"
            >
              {t("landing.footer.docs")}
            </a>
          </div>
        </footer>
      </div>
    </div>
  );
}
