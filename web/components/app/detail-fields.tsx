"use client";

/**
 * The read and edit primitives every detail panel is built from.
 *
 * Small on purpose. They exist so the three panels agree on spacing, label
 * association and focus rings — not to abstract the panels themselves, which
 * differ enough that a shared one would be mostly conditionals.
 */

import { useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";

/**
 * An explanation available on demand, beside a field's label.
 *
 * Distinct from `hint`, which renders a permanent line: that is right for a
 * warning everybody must read and wrong for a definition somebody needs once.
 *
 * Revealed on hover **and** on focus. Focus is not optional — hover-only help is
 * unreachable by keyboard and invisible on a touchscreen, and this exists
 * precisely for the person who does not already know.
 *
 * Hidden by opacity rather than `hidden`, which matters more than it looks: a
 * `display: none` element is absent from the accessibility tree, so an
 * `aria-describedby` pointing into one resolves to nothing and the button ends
 * up with no description at all. The tip stays rendered; only its paint changes.
 */
export function FieldHelp({ help }: { help: string }) {
  const t = useTranslations();
  const tipId = useId();
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={t("action.help")}
        aria-describedby={tipId}
        className="flex size-4 items-center justify-center rounded-full border border-line text-[10px] text-subtle hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        ?
      </button>
      <span
        id={tipId}
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-64 -translate-x-1/2 rounded-md border border-line bg-surface-overlay px-3 py-2 text-xs font-normal text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {help}
      </span>
    </span>
  );
}

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
  help,
}: {
  name: string;
  label: string;
  value: string;
  type?: string;
  required?: boolean;
  inputMode?: "decimal" | "numeric" | "text";
  hint?: string;
  help?: string;
}) {
  const describedBy = hint ? `${name}-hint` : undefined;
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <label htmlFor={name} className="block text-sm text-muted">
          {label}
        </label>
        {help && <FieldHelp help={help} />}
      </div>
      <input
        id={name}
        name={name}
        type={type}
        inputMode={inputMode}
        defaultValue={value}
        required={required}
        aria-describedby={describedBy}
        className="field-input"
      />
      {hint && (
        <p id={describedBy} className="mt-1 text-xs text-subtle">
          {hint}
        </p>
      )}
    </div>
  );
}

/** One labelled native select inside a panel's uncontrolled edit form. */
export function Select({
  name,
  label,
  value,
  required = true,
  children,
  help,
}: {
  name: string;
  label: string;
  value: string;
  required?: boolean;
  children: ReactNode;
  help?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <label htmlFor={name} className="block text-sm text-muted">
          {label}
        </label>
        {help && <FieldHelp help={help} />}
      </div>
      <select id={name} name={name} defaultValue={value} required={required} className="field-input">
        {children}
      </select>
    </div>
  );
}

/** One labelled native textarea inside a panel's uncontrolled edit form. */
export function Textarea({
  name,
  label,
  value,
  required = true,
  rows = 4,
}: {
  name: string;
  label: string;
  value: string;
  required?: boolean;
  rows?: number;
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-sm text-muted">
        {label}
      </label>
      <textarea
        id={name}
        name={name}
        defaultValue={value}
        required={required}
        rows={rows}
        className="field-input"
      />
    </div>
  );
}

/** Submission feedback from a panel form. */
export function FormError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="mt-3 text-sm text-fail">
      {children}
    </p>
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
