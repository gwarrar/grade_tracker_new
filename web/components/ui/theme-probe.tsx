"use client";

/**
 * Reports the resolved theme and the live value of a token.
 *
 * A development aid, and the answer to "is the theme actually inverting, or does it
 * only look like it?" — it reads the computed custom property rather than trusting
 * the class on <html>.
 */

import { useEffect, useState } from "react";

export function ThemeProbe() {
  const [state, setState] = useState<{ cls: string; bg: string; brand: string } | null>(null);

  useEffect(() => {
    const read = () => {
      const root = getComputedStyle(document.documentElement);
      setState({
        cls: document.documentElement.className.includes("dark") ? "dark" : "light",
        bg: root.getPropertyValue("--bg").trim(),
        brand: root.getPropertyValue("--brand-primary").trim(),
      });
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  if (!state) return null;

  return (
    <dl className="numeric mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-subtle">
      <div>
        <dt className="inline">mode </dt>
        <dd className="inline text-text">{state.cls}</dd>
      </div>
      <div>
        <dt className="inline">--bg </dt>
        <dd className="inline text-text">{state.bg}</dd>
      </div>
      <div>
        <dt className="inline">--brand-primary </dt>
        <dd className="inline text-text">{state.brand}</dd>
      </div>
    </dl>
  );
}
