"use client";

/**
 * The read and edit primitives every detail panel is built from.
 *
 * Small on purpose. They exist so the three panels agree on spacing, label
 * association and focus rings — not to abstract the panels themselves, which
 * differ enough that a shared one would be mostly conditionals.
 */

import { useTranslations } from "next-intl";
import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";

/** Tip width and the gap it keeps from the trigger and the viewport edges, in px. */
const TIP_WIDTH = 256;
const TIP_GAP = 8;

/**
 * An explanation available on demand, beside a field's label.
 *
 * Distinct from `hint`, which renders a permanent line: that is right for a
 * warning everybody must read and wrong for a definition somebody needs once.
 *
 * Three properties look like styling and are not:
 *
 * **Revealed on hover *and* on focus.** Hover-only help is unreachable by
 * keyboard and invisible on a touchscreen, which would exclude precisely the
 * person this exists for.
 *
 * **Hidden by opacity, never by `display`.** A `display: none` element is absent
 * from the accessibility tree, so `aria-describedby` would resolve to nothing and
 * the description would vanish while looking identical on screen.
 *
 * **Positioned `fixed`, not `absolute`.** Every caller sits inside a `<dialog>`,
 * which the UA stylesheet gives `overflow: auto` — and some sit inside a second
 * scroller within it. An absolutely positioned tip is clipped by the nearest such
 * ancestor, and a 16rem tip centred on a button in a 9rem grid column starts
 * outside the dialog before any vertical question arises. A fixed element's
 * containing block is the viewport, so no ancestor `overflow` can reach it, and
 * it stays a DOM descendant of the dialog so it still paints in the top layer.
 * Fixing it here rather than per container is what stops the next scroller from
 * reintroducing it.
 */
export function FieldHelp({ help }: { help: string }) {
  const t = useTranslations();
  const tipId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  // Empty until first revealed, not `{top: 0, left: 0}`: the tip is invisible
  // either way, and a placeholder coordinate would let a test that never fires the
  // handler still read a position back.
  const [place, setPlace] = useState<CSSProperties>({});

  /**
   * Put the tip under the trigger, flipping above when that would leave the
   * viewport and clamping sideways so neither edge is cut off.
   *
   * ponytail: measured at reveal only, so scrolling with a tip open leaves it
   * behind. The tip is `pointer-events-none`, so moving the pointer dismisses it
   * and the case barely arises. CSS anchor positioning deletes this function
   * outright once Firefox ships it.
   */
  function position() {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const height = tipRef.current?.offsetHeight ?? 0;
    const below = rect.bottom + TIP_GAP;
    setPlace({
      top: below + height > window.innerHeight ? rect.top - height - TIP_GAP : below,
      left: Math.min(
        Math.max(rect.left + rect.width / 2 - TIP_WIDTH / 2, TIP_GAP),
        window.innerWidth - TIP_WIDTH - TIP_GAP,
      ),
    });
  }

  return (
    <span className="group inline-flex" onMouseEnter={position} onFocus={position}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={t("action.help")}
        aria-describedby={tipId}
        className="flex size-4 items-center justify-center rounded-full border border-line text-[10px] text-subtle hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        ?
      </button>
      <span
        ref={tipRef}
        id={tipId}
        role="tooltip"
        style={{ ...place, width: TIP_WIDTH }}
        className="pointer-events-none fixed z-20 rounded-md border border-line bg-surface-overlay px-3 py-2 text-xs font-normal text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
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
  labelHidden = false,
}: {
  name: string;
  label: string;
  value: string;
  required?: boolean;
  children: ReactNode;
  help?: string;
  /**
   * Render the label to assistive technology only.
   *
   * For a control in a table whose row already names it on screen. The label still
   * exists and is still associated — hiding it is a visual decision, not a licence
   * to give every control in the column the same name.
   */
  labelHidden?: boolean;
}) {
  return (
    <div>
      <div className={labelHidden ? "" : "flex items-center gap-1.5"}>
        <label
          htmlFor={name}
          className={labelHidden ? "sr-only" : "block text-sm text-muted"}
        >
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
