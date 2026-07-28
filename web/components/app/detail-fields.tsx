"use client";

/**
 * The read and edit primitives every detail panel is built from.
 *
 * Small on purpose. They exist so the three panels agree on spacing, label
 * association and focus rings — not to abstract the panels themselves, which
 * differ enough that a shared one would be mostly conditionals.
 */

import type { ReactNode } from "react";

/** One read-only row inside a panel's `<dl>`. */
export function Field({
  label,
  value,
  numeric,
}: {
  label: string;
  value: ReactNode;
  /** Render the value with tabular figures, so columns of numbers line up. */
  numeric?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-subtle">{label}</dt>
      <dd className={`min-w-0 truncate text-end text-text ${numeric ? "numeric" : ""}`}>
        {value}
      </dd>
    </div>
  );
}

/**
 * One labelled input inside a panel's edit form.
 *
 * Uncontrolled with a `defaultValue`: the panel is remounted per record by its
 * `key`, so there is no stale value to guard against and no re-render per
 * keystroke.
 *
 * `inputMode="decimal"` rather than `type="number"` for figures — a number input
 * rejects the comma a German user types for `88,5`, and silently discards it
 * rather than reporting it.
 */
export function Input({
  name,
  label,
  value,
  type = "text",
  required = true,
  inputMode,
  hint,
}: {
  name: string;
  label: string;
  value: string;
  type?: string;
  required?: boolean;
  inputMode?: "decimal" | "numeric" | "text";
  hint?: string;
}) {
  const describedBy = hint ? `${name}-hint` : undefined;
  return (
    <div>
      <label htmlFor={name} className="block text-sm text-muted">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        inputMode={inputMode}
        defaultValue={value}
        required={required}
        aria-describedby={describedBy}
        className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
      />
      {hint && (
        <p id={describedBy} className="mt-1 text-xs text-subtle">
          {hint}
        </p>
      )}
    </div>
  );
}

/** A panel's header: title, subtitle and the close control. */
export function PanelHeader({
  title,
  subtitle,
  closeLabel,
  onClose,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  closeLabel: string;
  onClose: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="truncate text-lg font-medium text-text">{title}</h2>
        {subtitle && <p className="numeric mt-0.5 text-sm text-subtle">{subtitle}</p>}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label={closeLabel}
        className="rounded-md px-2 py-1 text-lg leading-none text-subtle transition-colors hover:text-text"
      >
        ×
      </button>
    </div>
  );
}
