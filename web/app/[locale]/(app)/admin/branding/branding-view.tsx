"use client";

import { useTranslations } from "next-intl";
import { useState, type CSSProperties, type FormEvent } from "react";

import { useRouter } from "next/navigation";

import { refreshBranding } from "./actions";
import { assetUrl, type Branding } from "@/components/branding/branding";
import { FormError, Input, Select } from "@/components/app/detail-fields";
import { Confirm } from "@/components/ui/confirm";
import { api, ApiError } from "@/lib/api";
import {
  checkBackground,
  checkBothModes,
  readableTextOn,
  suggestDarkVariant,
} from "@/lib/contrast";
import {
  validateGradingScale,
  type GradeBand,
  type GradingScaleError,
} from "@/lib/grading-scale";

const LOCALES = ["en", "de", "fr"] as const;
const THEMES = ["light", "dark", "system"] as const;

type AssetKind = "logo" | "favicon";
type ColorKind = keyof Branding["colors"];
type ColorMode = keyof Branding["colors"][ColorKind];
type PreviewStyle = CSSProperties & {
  "--preview-primary": string;
  "--preview-accent": string;
};

export function BrandingView({
  initialBranding,
  timeZones,
}: {
  initialBranding: Branding;
  /**
   * The zone list, built on the server and passed down rather than read here.
   *
   * `Intl.supportedValuesOf("timeZone")` answers from the host's ICU data, and
   * Node's differs from the browser's — a few zones apart, enough that the
   * `<option>` set in the server-rendered HTML did not match the one the client
   * produced, and React reported a hydration mismatch on every load. Taking the
   * list as a prop means the client renders the array that is already in the
   * HTML, so there is nothing to disagree about.
   */
  timeZones: string[];
}) {
  const t = useTranslations("admin.branding");
  const [branding, setBranding] = useState(initialBranding);

  return (
    <div className="space-y-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("intro")}</p>
      </div>

      <AssetEditor branding={branding} onChange={setBranding} />
      <BrandingForm branding={branding} onChange={setBranding} timeZones={timeZones} />
      <GradingScaleEditor branding={branding} onChange={setBranding} />
    </div>
  );
}

function AssetEditor({
  branding,
  onChange,
}: {
  branding: Branding;
  onChange: (branding: Branding) => void;
}) {
  const t = useTranslations("admin.branding");
  const tAction = useTranslations("action");
  const tError = useTranslations("error");
  const [previews, setPreviews] = useState<Record<AssetKind, string | null>>({
    logo: null,
    favicon: null,
  });
  const [pending, setPending] = useState<AssetKind | null>(null);
  const [code, setCode] = useState<string | null>(null);

  async function upload(kind: AssetKind, file: File) {
    const preview = URL.createObjectURL(file);
    setPreviews((current) => ({ ...current, [kind]: preview }));
    setPending(kind);
    setCode(null);

    const form = new FormData();
    form.set("file", file);
    try {
      const stored = await api<Branding>(`/org/assets/${kind}`, {
        method: "POST",
        body: form,
      });
      onChange(stored);
    } catch (error) {
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
    } finally {
      URL.revokeObjectURL(preview);
      setPreviews((current) => ({ ...current, [kind]: null }));
      setPending(null);
    }
  }

  async function remove(kind: AssetKind) {
    setPending(kind);
    setCode(null);
    try {
      onChange(await api<Branding>(`/org/assets/${kind}`, { method: "DELETE" }));
    } catch (error) {
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
    } finally {
      setPending(null);
    }
  }

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("assets")}</h2>
      <p className="mt-1 text-sm text-muted">{t("assetHint")}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {(["logo", "favicon"] as const).map((kind) => {
          const path = branding[`${kind}_path`];
          const preview = previews[kind] ?? (path ? assetUrl(path) : null);
          return (
            <div key={kind} className="rounded-xl border border-line bg-surface p-5">
              <h3 className="text-sm font-medium text-text">{t(kind)}</h3>
              <div
                role="img"
                aria-label={t(kind)}
                className={`mt-3 flex items-center justify-center rounded-lg border border-line bg-bg bg-contain bg-center bg-no-repeat ${
                  kind === "logo" ? "h-28" : "h-20"
                }`}
                style={preview ? { backgroundImage: `url(${preview})` } : undefined}
              >
                {!preview && (
                  <span className="text-sm font-semibold text-text">
                    {branding.short_name || branding.name}
                  </span>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <label className="btn cursor-pointer">
                  {pending === kind ? t("uploading") : t("chooseFile")}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/x-icon"
                    disabled={pending !== null}
                    className="sr-only"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      event.currentTarget.value = "";
                      if (file) void upload(kind, file);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={!path || pending !== null}
                  onClick={() => void remove(kind)}
                >
                  {tAction("remove")}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {code && <FormError>{tError(code as "unknown")}</FormError>}
    </section>
  );
}

function BrandingForm({
  branding,
  onChange,
  timeZones,
}: {
  branding: Branding;
  onChange: (branding: Branding) => void;
  timeZones: string[];
}) {
  const t = useTranslations("admin.branding");
  const tAction = useTranslations("action");
  const tError = useTranslations("error");
  const tLocale = useTranslations("locale");
  const tTheme = useTranslations("theme");
  const [colors, setColors] = useState(branding.colors);
  const [enabledLocales, setEnabledLocales] = useState(branding.enabled_locales);
  const [defaultLocale, setDefaultLocale] = useState(branding.default_locale);
  const [pending, setPending] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const router = useRouter();
  // Judged against the background being edited, not the shipped one, so the ratios
  // move as the backdrop does. Checking a brand colour against a background the
  // organisation is not using is not a check.
  const primary = checkBothModes(colors.primary.light, colors.primary.dark, colors.background);
  const accent = checkBothModes(colors.accent.light, colors.accent.dark, colors.background);
  // The other direction: the background has to keep body text readable, and that
  // text is not configurable, so the background is what yields.
  const background = checkBackground(colors.background.light, colors.background.dark);
  const usable = primary.usable && accent.usable && background.usable;

  function setColor(kind: ColorKind, mode: ColorMode, value: string) {
    setColors((current) => ({
      ...current,
      [kind]: { ...current[kind], [mode]: value },
    }));
    setSaved(false);
  }

  function toggleLocale(locale: string) {
    const next = enabledLocales.includes(locale)
      ? enabledLocales.filter((item) => item !== locale)
      : [...enabledLocales, locale];
    if (next.length === 0) return;
    setEnabledLocales(next);
    if (!next.includes(defaultLocale)) setDefaultLocale(next[0]!);
    setSaved(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Refuse the write rather than disabling the button. A disabled Save cannot
    // explain itself, and because one unreadable colour would block the name, the
    // logo and the locales too, the whole page looked broken to anyone who nudged
    // a swatch past the threshold.
    if (!usable) {
      setSaved(false);
      setCode("CONTRAST_TOO_LOW");
      return;
    }
    const form = new FormData(event.currentTarget);
    setPending(true);
    setCode(null);
    setSaved(false);
    try {
      const stored = await api<Branding>("/org/branding", {
        method: "PATCH",
        body: {
          name: String(form.get("name") ?? ""),
          short_name: String(form.get("short_name") ?? ""),
          color_primary_light: colors.primary.light,
          color_primary_dark: colors.primary.dark,
          color_accent_light: colors.accent.light,
          color_accent_dark: colors.accent.dark,
          color_background_light: colors.background.light,
          color_background_dark: colors.background.dark,
          enabled_locales: enabledLocales,
          default_locale: defaultLocale,
          default_theme: String(form.get("default_theme") ?? "system"),
          timezone: String(form.get("timezone") ?? "UTC"),
        },
      });
      onChange(stored);
      // The layout's branding read is cached, so without dropping the tag and
      // re-rendering the server components the page keeps showing the old values
      // and this form repopulates from them.
      await refreshBranding();
      router.refresh();
      setSaved(true);
    } catch (error) {
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-10">
      <section>
        <h2 className="text-lg font-medium text-text">{t("identity")}</h2>
        <div className="mt-4 grid gap-4 rounded-xl border border-line bg-surface p-6 sm:grid-cols-2">
          <Input name="name" label={t("name")} value={branding.name} />
          <Input name="short_name" label={t("shortName")} value={branding.short_name} />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium text-text">{t("colors")}</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <ColorPair
            label={t("primary")}
            colors={colors.primary}
            result={primary}
            onChange={(mode, value) => setColor("primary", mode, value)}
            onSuggest={() =>
              setColor("primary", "dark", suggestDarkVariant(colors.primary.light, colors.background.dark))
            }
          />
          <ColorPair
            label={t("accent")}
            colors={colors.accent}
            result={accent}
            onChange={(mode, value) => setColor("accent", mode, value)}
            onSuggest={() =>
              setColor("accent", "dark", suggestDarkVariant(colors.accent.light, colors.background.dark))
            }
          />
          {/* No suggestion button: `suggestDarkVariant` lightens towards legibility
              on a dark backdrop, which is the opposite of what a dark background
              wants. A second heuristic costs more than it is worth. */}
          <ColorPair
            label={t("background")}
            colors={colors.background}
            result={background}
            onChange={(mode, value) => setColor("background", mode, value)}
          />
        </div>
        <ColorPreview colors={colors} />
      </section>

      <section>
        <h2 className="text-lg font-medium text-text">{t("locales")}</h2>
        <div className="mt-4 grid gap-5 rounded-xl border border-line bg-surface p-6 sm:grid-cols-2">
          <fieldset>
            <legend className="text-sm text-muted">{t("enabledLocales")}</legend>
            <div className="mt-2 flex flex-wrap gap-4">
              {LOCALES.map((locale) => (
                <label key={locale} className="flex items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={enabledLocales.includes(locale)}
                    disabled={enabledLocales.length === 1 && enabledLocales[0] === locale}
                    className="accent-[var(--brand-primary)]"
                    onChange={() => toggleLocale(locale)}
                  />
                  {tLocale(locale)}
                </label>
              ))}
            </div>
          </fieldset>

          <div>
            <label htmlFor="default_locale" className="block text-sm text-muted">
              {t("defaultLocale")}
            </label>
            <select
              id="default_locale"
              value={defaultLocale}
              className="field-input"
              onChange={(event) => {
                setDefaultLocale(event.target.value);
                setSaved(false);
              }}
            >
              {enabledLocales.map((locale) => (
                <option key={locale} value={locale}>
                  {tLocale(locale as "en")}
                </option>
              ))}
            </select>
          </div>

          <Select
            name="default_theme"
            label={t("defaultTheme")}
            value={branding.default_theme}
          >
            {THEMES.map((theme) => (
              <option key={theme} value={theme}>
                {tTheme(theme)}
              </option>
            ))}
          </Select>

          <Select name="timezone" label={t("timezone")} value={branding.timezone}>
            {timeZones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </Select>
        </div>
      </section>

      {code && <FormError>{tError(code as "unknown")}</FormError>}
      {saved && <p role="status" className="text-sm text-pass">{t("saved")}</p>}
      <button type="submit" className="btn btn-primary" disabled={pending}>
        {tAction("save")}
      </button>
    </form>
  );
}

function ColorPair({
  label,
  colors,
  result,
  onChange,
  onSuggest,
}: {
  label: string;
  colors: { light: string; dark: string };
  result: ReturnType<typeof checkBothModes>;
  onChange: (mode: ColorMode, value: string) => void;
  /** Offered only where a mechanical suggestion makes sense — see the callers. */
  onSuggest?: () => void;
}) {
  const t = useTranslations("admin.branding");

  return (
    <fieldset className="rounded-xl border border-line bg-surface p-5">
      <legend className="px-1 text-sm font-medium text-text">{label}</legend>
      <div className="grid grid-cols-2 gap-4">
        {(["light", "dark"] as const).map((mode) => (
          <label key={mode} className="text-sm text-muted">
            {t(mode)}
            <input
              type="color"
              value={colors[mode]}
              className="mt-2 block h-11 w-full cursor-pointer rounded-lg border border-line bg-bg p-1"
              onChange={(event) => onChange(mode, event.target.value)}
            />
          </label>
        ))}
      </div>
      <p
        role="status"
        className={`numeric mt-3 text-xs ${result.usable ? "text-pass" : "text-fail"}`}
      >
        {t("contrast", {
          light: result.light.ratio.toFixed(2),
          dark: result.dark.ratio.toFixed(2),
        })}
      </p>
      {onSuggest && !result.dark.passesAALarge && (
        <button
          type="button"
          className="mt-3 text-xs font-medium text-brand hover:underline"
          onClick={onSuggest}
        >
          {t("suggestDark")}
        </button>
      )}
    </fieldset>
  );
}

function ColorPreview({ colors }: { colors: Branding["colors"] }) {
  const t = useTranslations("admin.branding");

  return (
    <div className="mt-4 grid gap-4 sm:grid-cols-2" aria-label={t("preview")}>
      {(["light", "dark"] as const).map((mode) => {
        // Taken from the form rather than hardcoded to the shipped values. With
        // the background configurable, a fixed preview would show a page nobody is
        // going to see — and this is where the decision that cards keep their own
        // colour becomes visible before saving rather than after.
        const style: PreviewStyle = {
          "--preview-primary": colors.primary[mode],
          "--preview-accent": colors.accent[mode],
          backgroundColor: colors.background[mode],
          color: readableTextOn(colors.background[mode]),
        };
        return (
          <div key={mode} className="rounded-xl border border-line p-5" style={style}>
            <p className="text-xs uppercase tracking-wide opacity-60">{t(mode)}</p>
            <p className="mt-3 text-lg font-semibold">{t("previewHeading")}</p>
            <div className="mt-4 flex gap-2">
              <span
                className="rounded-lg px-3 py-2 text-sm font-medium"
                style={{
                  backgroundColor: "var(--preview-primary)",
                  color: readableTextOn(colors.primary[mode]),
                }}
              >
                {t("previewAction")}
              </span>
              <span
                className="rounded-lg border px-3 py-2 text-sm font-medium"
                style={{ borderColor: "var(--preview-accent)", color: "var(--preview-accent)" }}
              >
                {t("previewAccent")}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function GradingScaleEditor({
  branding,
  onChange,
}: {
  branding: Branding;
  onChange: (branding: Branding) => void;
}) {
  const t = useTranslations("admin.branding");
  const tAction = useTranslations("action");
  const tError = useTranslations("error");
  const [bands, setBands] = useState<GradeBand[]>(branding.grading_scale);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const validation = validateGradingScale(bands);

  function change(index: number, patch: Partial<GradeBand>) {
    setBands((current) =>
      current.map((band, bandIndex) => (bandIndex === index ? { ...band, ...patch } : band)),
    );
    setSaved(false);
  }

  function move(index: number, offset: -1 | 1) {
    setBands((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target]!, next[index]!];
      return next;
    });
    setSaved(false);
  }

  async function save() {
    setPending(true);
    setCode(null);
    try {
      const stored = await api<Branding>("/org/grading-scale", {
        method: "PUT",
        body: bands,
      });
      setBands(stored.grading_scale);
      onChange(stored);
      setSaved(true);
    } catch (error) {
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
    } finally {
      setPending(false);
      setConfirming(false);
    }
  }

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("gradingScale")}</h2>
      <p className="mt-1 text-sm text-muted">{t("gradingIntro")}</p>

      <div className="mt-4 space-y-3">
        {bands.map((band, index) => (
          <div
            key={index}
            className="grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          >
            <label className="text-sm text-muted">
              {t("threshold")}
              <input
                type="number"
                value={band.min_percentage}
                className="field-input numeric"
                onChange={(event) => change(index, { min_percentage: Number(event.target.value) })}
              />
            </label>
            <label className="text-sm text-muted">
              {t("bandLabel")}
              <input
                value={band.label}
                className="field-input"
                onChange={(event) => change(index, { label: event.target.value })}
              />
            </label>
            <div className="flex gap-1">
              <button
                type="button"
                className="btn btn-ghost px-2"
                aria-label={t("moveUp")}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                className="btn btn-ghost px-2"
                aria-label={t("moveDown")}
                disabled={index === bands.length - 1}
                onClick={() => move(index, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className="btn btn-ghost px-2 text-fail"
                aria-label={tAction("remove")}
                onClick={() => {
                  setBands((current) => current.filter((_, bandIndex) => bandIndex !== index));
                  setSaved(false);
                }}
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        className="btn mt-3"
        onClick={() => {
          setBands((current) => [
            { min_percentage: (current[0]?.min_percentage ?? -10) + 10, label: "" },
            ...current,
          ]);
          setSaved(false);
        }}
      >
        {tAction("add")}
      </button>

      {validation && (
        <FormError>{t(`scaleError.${validation}` as `scaleError.${GradingScaleError}`)}</FormError>
      )}
      {code && <FormError>{tError(code as "unknown")}</FormError>}
      {saved && <p role="status" className="mt-3 text-sm text-pass">{t("saved")}</p>}

      <button
        type="button"
        className="btn btn-primary mt-4"
        disabled={validation !== null || pending}
        onClick={() => setConfirming(true)}
      >
        {tAction("save")}
      </button>

      <Confirm
        open={confirming}
        title={t("confirmTitle")}
        description={t("confirmDescription")}
        confirmLabel={tAction("save")}
        cancelLabel={tAction("cancel")}
        onConfirm={save}
        onCancel={() => setConfirming(false)}
      />
    </section>
  );
}
