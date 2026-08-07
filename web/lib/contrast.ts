/**
 * WCAG contrast maths, for the branding colour picker.
 *
 * The admin picks a brand colour and the app re-themes live. Without a check, an
 * administrator can pick something that reads beautifully on the white page they
 * are looking at and is invisible to every user in dark mode — a failure they will
 * never see themselves.
 *
 * So every candidate is validated against **both** backgrounds, and both must pass.
 * That is the whole reason `tokens.css` defines each colour twice.
 */

/** A colour's contrast against one background. */
export interface ContrastResult {
  /** Contrast ratio, 1–21. */
  ratio: number;
  /** Meets WCAG AA for normal text (4.5:1). */
  passesAA: boolean;
  /** Meets WCAG AA for large text (3:1) — headings and 18pt+. */
  passesAALarge: boolean;
  /** Meets WCAG AAA for normal text (7:1). */
  passesAAA: boolean;
}

/** A colour checked against both themes. */
export interface DualModeResult {
  light: ContrastResult;
  dark: ContrastResult;
  /** True only when both modes pass AA. A colour failing either is rejected. */
  usable: boolean;
}

/** A value chosen once per theme. */
export interface ModePair {
  light: string;
  dark: string;
}

/**
 * The shipped `--bg` values, used when no background has been configured.
 *
 * Duplicated from `app/tokens.css` rather than read from it: this maths runs in
 * Node and during render, where no CSS custom property can be resolved. They must
 * stay in step, and `tokens.test.ts` pins the CSS side.
 */
export const DEFAULT_BACKGROUND: ModePair = { light: "#fbfbfa", dark: "#08080a" };

/**
 * The text that has to stay legible on whatever background is chosen.
 *
 * `--text` and `--text-muted` for each theme. `--text-subtle` is deliberately
 * absent: at ~3.0:1 on the shipped background it would reject the product's own
 * default, and a gate that fails its own defaults is a gate nobody trusts.
 */
const TEXT_ON_LIGHT = ["#14140f", "#5c5c54"];
const TEXT_ON_DARK = ["#f2f2ef", "#a3a39c"];

/**
 * Parse a hex colour into RGB components.
 *
 * @param hex - `#rgb` or `#rrggbb`, with or without the hash.
 * @returns Components in 0–255, or null if unparseable.
 */
export function parseHex(hex: string): [number, number, number] | null {
  const cleaned = hex.trim().replace(/^#/, "");
  const expanded =
    cleaned.length === 3
      ? cleaned
          .split("")
          .map((c) => c + c)
          .join("")
      : cleaned;

  if (!/^[0-9a-f]{6}$/i.test(expanded)) return null;

  return [
    parseInt(expanded.slice(0, 2), 16),
    parseInt(expanded.slice(2, 4), 16),
    parseInt(expanded.slice(4, 6), 16),
  ];
}

/**
 * Relative luminance per WCAG 2.1.
 *
 * The channel-wise gamma expansion is what makes this different from a naive
 * average — the eye is far more sensitive to green than to blue, and averaging RGB
 * would rate a saturated blue as far brighter than it appears.
 *
 * @param rgb - Components in 0–255.
 * @returns Luminance in 0–1.
 */
export function luminance([r, g, b]: [number, number, number]): number {
  const channel = (value: number): number => {
    const v = value / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * Contrast ratio between two colours.
 *
 * @param foreground - Hex colour.
 * @param background - Hex colour.
 * @returns The ratio 1–21, or 1 if either colour is unparseable.
 */
export function contrastRatio(foreground: string, background: string): number {
  const fg = parseHex(foreground);
  const bg = parseHex(background);
  if (!fg || !bg) return 1;

  const [lighter, darker] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Check a colour against one background.
 *
 * @param foreground - Hex colour.
 * @param background - Hex colour.
 * @returns Ratio and which WCAG levels it meets.
 */
export function checkContrast(foreground: string, background: string): ContrastResult {
  const ratio = contrastRatio(foreground, background);
  return {
    ratio: Math.round(ratio * 100) / 100,
    passesAA: ratio >= 4.5,
    passesAALarge: ratio >= 3,
    passesAAA: ratio >= 7,
  };
}

/**
 * Check a colour pair against both themes.
 *
 * @param light - The colour used in light mode.
 * @param dark - The colour used in dark mode.
 * @param background - The backgrounds to judge against. Defaults to the shipped
 *   ones; the branding editor passes the organisation's, because a gate that
 *   validates against a background nobody is using is not a gate.
 * @returns Both results, and whether the pair is usable at all.
 */
export function checkBothModes(
  light: string,
  dark: string,
  background: ModePair = DEFAULT_BACKGROUND,
): DualModeResult {
  const lightResult = checkContrast(light, background.light);
  const darkResult = checkContrast(dark, background.dark);
  return {
    light: lightResult,
    dark: darkResult,
    // Large-text AA, because brand colour is used for buttons, links and headings
    // rather than body copy. Requiring 4.5:1 would reject most usable brand
    // palettes; requiring nothing would admit unreadable ones.
    usable: lightResult.passesAALarge && darkResult.passesAALarge,
  };
}

/**
 * Suggest a dark-mode counterpart for a light-mode brand colour.
 *
 * A starting point for the picker, not a substitute for it. Most brand colours are
 * chosen against white and are too dark to read on near-black, so this lightens
 * towards the point where it passes — and the admin still sees, and can override,
 * the result.
 *
 * @param lightHex - The light-mode colour.
 * @param background - The dark-mode background to aim at. Defaults to the shipped
 *   one; the branding editor passes the organisation's.
 * @returns A hex colour that passes large-text AA on the dark background where
 *   possible, or the lightest attempt if none does.
 */
export function suggestDarkVariant(
  lightHex: string,
  background: string = DEFAULT_BACKGROUND.dark,
): string {
  const rgb = parseHex(lightHex);
  if (!rgb) return lightHex;

  let best = lightHex;
  for (let step = 0; step <= 10; step++) {
    const factor = step / 10;
    const lightened = rgb.map((c) => Math.round(c + (255 - c) * factor * 0.7)) as [
      number,
      number,
      number,
    ];
    const hex = `#${lightened.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
    best = hex;
    if (checkContrast(hex, background).passesAALarge) return hex;
  }
  return best;
}

/**
 * Check a candidate page background against the text that must sit on it.
 *
 * The mirror image of {@link checkBothModes}, and the reason it needs its own
 * function: a brand colour has to be legible *on* the background, whereas the
 * background has to keep the text legible on *itself* — and that text is not
 * configurable, so the background is what yields. Without this, an admin could set
 * a mid-grey page, `--text` would render on it, and the brand gate would notice
 * nothing, because a dark brand colour on a dark background can still pass.
 *
 * AA at 4.5:1 rather than the AA-large 3:1 used for brand colours. Brand colours
 * are buttons and headings; `--text` on `--bg` is running text.
 *
 * Only `--text` and `--text-muted` are checked, and the worse of the two decides.
 * Driving the text colour from the background instead would rescue `--text` and
 * abandon the muted, subtle, border and semantic tokens, which are tuned as a ramp.
 *
 * @param light - The light-mode background.
 * @param dark - The dark-mode background.
 * @returns Both results, and whether the pair keeps body copy readable.
 */
export function checkBackground(light: string, dark: string): DualModeResult {
  const worst = (background: string, texts: string[]): ContrastResult =>
    texts
      .map((text) => checkContrast(text, background))
      .reduce((a, b) => (a.ratio <= b.ratio ? a : b));

  const lightResult = worst(light, TEXT_ON_LIGHT);
  const darkResult = worst(dark, TEXT_ON_DARK);
  return {
    light: lightResult,
    dark: darkResult,
    usable: lightResult.passesAA && darkResult.passesAA,
  };
}

/**
 * Pick black or white text for a given background.
 *
 * @param background - Hex colour the text sits on.
 * @returns Whichever of near-black or near-white contrasts better.
 */
export function readableTextOn(background: string): string {
  return contrastRatio("#ffffff", background) >= contrastRatio("#08080a", background)
    ? "#ffffff"
    : "#08080a";
}
