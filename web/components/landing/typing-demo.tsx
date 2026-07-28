"use client";

/**
 * A command palette that types itself.
 *
 * The highest-signal element on the landing page, because it demonstrates the
 * actual product rather than describing it. Every query shown here maps to a real
 * endpoint.
 *
 * Driven by a timeline rather than CSS: the sequence is type → pause → resolve →
 * hold → clear, with different easing per stage, and expressing that in keyframes
 * would mean recalculating percentages every time a line changes.
 */

import { animate, createTimeline, utils } from "animejs";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

interface Demo {
  /** What the user "types". */
  query: string;
  /** What the assistant resolves it to. */
  result: string;
  /** The figure the result carries, rendered in mono. */
  figure?: string;
}

interface Props {
  demos: Demo[];
  /** Label for the palette's hint row. */
  hint: string;
}

const TYPE_MS = 42;
const HOLD_MS = 2200;

export function TypingDemo({ demos, hint }: Props) {
  const [index, setIndex] = useState(0);
  const [typed, setTyped] = useState("");
  const [resolved, setResolved] = useState(false);
  const caretRef = useRef<HTMLSpanElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  // Honoured explicitly rather than left to the CSS media query: this animation is
  // a loop that never settles, which is precisely what vestibular disorders react
  // to. Reduced motion gets the finished state, not a faster version of the motion.
  //
  // Motion already subscribes to the media query and re-renders on change, so there
  // is nothing to hand-roll. It returns null before hydration; that reads as "not
  // reduced", which matches the server-rendered markup.
  const reducedMotion = useReducedMotion() ?? false;

  useEffect(() => {
    // No state is set here under reduced motion — the finished state is derived
    // during render instead, so the effect has nothing to do.
    if (reducedMotion) return;

    const demo = demos[index];
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const step = (position: number) => {
      if (cancelled) return;

      if (position <= demo.query.length) {
        setTyped(demo.query.slice(0, position));
        // A touch of jitter, because a perfectly even cadence reads as a progress
        // bar rather than as typing.
        timer = setTimeout(() => step(position + 1), TYPE_MS + Math.random() * 34);
        return;
      }

      setResolved(true);
      timer = setTimeout(() => {
        if (cancelled) return;
        setResolved(false);
        setTyped("");
        setIndex((current) => (current + 1) % demos.length);
      }, HOLD_MS);
    };

    step(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [index, demos, reducedMotion]);

  // The caret blinks on its own timeline so it keeps its rhythm across the type,
  // resolve and clear stages rather than restarting with each.
  useEffect(() => {
    if (reducedMotion || !caretRef.current) return;
    const blink = animate(caretRef.current, {
      opacity: [1, 1, 0, 0],
      duration: 1060,
      ease: "steps(1)",
      loop: true,
    });
    // Braces matter: `pause()` returns the animation, and an effect cleanup that
    // returns anything but a function is a type error.
    return () => {
      blink.pause();
    };
  }, [reducedMotion]);

  // The result animates in on a short timeline: lift, fade, then the figure counts
  // up. Sequenced, so the number lands after the row has arrived rather than
  // competing with it.
  useEffect(() => {
    if (reducedMotion || !resolved || !resultRef.current) return;

    const timeline = createTimeline({ defaults: { ease: "outQuart" } });
    timeline.add(resultRef.current, { opacity: [0, 1], y: [8, 0], duration: 420 });

    const figure = resultRef.current.querySelector<HTMLElement>("[data-figure]");
    const target = Number(figure?.dataset.figure ?? NaN);
    if (figure && Number.isFinite(target)) {
      timeline.add(
        { value: 0 },
        {
          value: target,
          duration: 620,
          ease: "outExpo",
          onUpdate: (self) => {
            const value = (self.targets[0] as { value: number }).value;
            figure.textContent = utils.round(value, 1).toFixed(1);
          },
        },
        "-=240",
      );
    }

    return () => {
      timeline.pause();
    };
  }, [resolved, reducedMotion, index]);

  // Under reduced motion the component shows the first demo already resolved.
  // Derived rather than stored: state that is a pure function of a prop is a second
  // source of truth waiting to disagree with the first.
  const demo = reducedMotion ? demos[0] : demos[index];
  const shownText = reducedMotion ? demo.query : typed;
  const shownResult = reducedMotion || resolved;

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <kbd className="numeric rounded border border-line bg-bg-subtle px-1.5 py-0.5 text-[11px] text-subtle">
          ⌘K
        </kbd>
        <span className="text-xs text-subtle">{hint}</span>
      </div>

      <div className="px-4 py-5">
        <p className="min-h-6 text-[15px] text-text">
          {shownText}
          <span ref={caretRef} className="ml-px inline-block w-px bg-brand align-middle">
            {/* A one-pixel span, not a character: a literal caret glyph shifts the
                text as it blinks. */}
            &#8203;
          </span>
        </p>

        <div
          ref={resultRef}
          // aria-live so the result is announced. Without it a screen-reader user
          // gets a static, empty box where sighted users see the whole demonstration.
          aria-live="polite"
          className="mt-4 min-h-[52px]"
          style={{ opacity: shownResult ? 1 : 0 }}
        >
          {shownResult && (
            <div className="flex items-baseline justify-between gap-4 rounded-lg bg-bg-subtle px-3 py-2.5">
              <span className="text-sm text-muted">{demo.result}</span>
              {demo.figure && (
                <span className="numeric text-lg text-text">
                  <span data-figure={demo.figure}>{demo.figure}</span>
                  <span className="text-subtle">%</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* The progress strip tracks a loop that does not run under reduced motion. */}
      {!reducedMotion && (
        <div className="flex gap-1 border-t border-line px-4 py-2">
          {demos.map((item, position) => (
            <span
              key={item.query}
              className={`h-0.5 flex-1 rounded-full transition-colors ${
                position === index ? "bg-brand" : "bg-line"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
