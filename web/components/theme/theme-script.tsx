/**
 * The pre-hydration theme script.
 *
 * A **server** component, rendered into `<head>`. That placement is the whole
 * point: the class has to be on `<html>` before the browser paints the body, or a
 * user whose system is dark sees a flash of the light theme on every navigation.
 * The server cannot know the stored preference, so the first paint is always wrong
 * until a script corrects it — and the script has to run first.
 *
 * Rendering it from the server also means React never renders a `<script>` on the
 * client, which it warns about and, more importantly, would not execute.
 */

/** Where the preference is stored. Shared with the provider. */
export const STORAGE_KEY = "theme";

/**
 * The script body, stringified into the page.
 *
 * Written as a string rather than a function passed through `toString()` because
 * a bundler is free to rename identifiers inside a real function, and this has to
 * survive minification unchanged.
 *
 * Wrapped in try/catch: `localStorage` throws outright in a browser configured to
 * block storage, and an exception here would leave the page unstyled rather than
 * merely un-themed.
 */
function script(fallback: string): string {
  return `
try {
  var stored = localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
  var theme = stored || ${JSON.stringify(fallback)};
  if (theme === "system") {
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.classList.toggle("dark", theme === "dark");
  // Tells the browser which built-in form controls and scrollbars to draw, so
  // they match the page instead of staying stubbornly light.
  document.documentElement.style.colorScheme = theme;
} catch (error) {}
`.trim();
}

/**
 * Render the theme script.
 *
 * @param defaultTheme - The organisation's default, for anyone with no stored
 *   preference. One of `light`, `dark` or `system`.
 */
export function ThemeScript({ defaultTheme = "system" }: { defaultTheme?: string }) {
  return (
    <script
      // The class this writes is what makes the server and client markup differ,
      // and that difference is the mechanism preventing the flash — not a bug.
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: script(defaultTheme) }}
    />
  );
}
