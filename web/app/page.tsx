/**
 * Temporary root page — replaced by the marketing landing page in the next phase.
 *
 * Present so the design system can be seen and the build verified.
 */

import { getBranding } from "@/components/branding/branding";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { ThemeProbe } from "@/components/ui/theme-probe";
import { formatNumber, formatPercent } from "@/lib/format";

export default async function Home() {
  const branding = await getBranding();
  const bands = branding.grading_scale;

  return (
    <main className="mx-auto max-w-3xl px-6 py-20">
      <div className="flex items-start justify-between gap-4">
        <p className="numeric text-xs uppercase tracking-widest text-subtle">
          design system · {branding.enabled_locales.join(" / ")}
        </p>
        <ThemeToggle />
      </div>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight text-text">{branding.name}</h1>
      <p className="mt-2 max-w-prose text-muted">
        Tokens resolve from the organisation record. Every colour below is a custom
        property, which is what lets an administrator re-theme the interface without a
        rebuild.
      </p>

      <div className="mt-10 grid gap-3 sm:grid-cols-3">
        {[
          { label: "Students", value: formatNumber(40, branding.default_locale) },
          { label: "Average", value: formatPercent(70.5, branding.default_locale) },
          { label: "Pass rate", value: formatPercent(64.2, branding.default_locale) },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-lg border border-line bg-surface p-4"
          >
            <div className="text-xs uppercase tracking-wide text-subtle">{stat.label}</div>
            <div className="numeric mt-1 text-2xl text-text">{stat.value}</div>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        {bands.map((band) => (
          <span
            key={band.label}
            className="numeric rounded border border-line bg-bg-subtle px-3 py-1 text-sm text-muted"
          >
            {band.label} ≥ {band.min_percentage}%
          </span>
        ))}
      </div>

      <button
        type="button"
        className="mt-8 rounded bg-brand px-4 py-2 font-medium text-brand-contrast"
      >
        Brand colour, contrast-checked in both themes
      </button>

      <ThemeProbe />
    </main>
  );
}
