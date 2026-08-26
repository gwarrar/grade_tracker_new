/**
 * The reusable pieces the overview is assembled from.
 *
 * Everything animates off `useCurrentFrame()` rather than CSS transitions, because
 * a renderer draws frame N directly and never plays frames 0..N-1 — a CSS
 * animation would come out as a still frame of its starting state.
 */

import type { CSSProperties, ReactNode } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

import { font, theme } from "./theme";

/** Fade and lift in, with an optional delay in frames. */
export function Reveal({
  delay = 0,
  children,
  style,
}: {
  delay?: number;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({ frame: frame - delay, fps, config: { damping: 200 } });

  return (
    <div
      style={{
        ...style,
        opacity: progress,
        transform: `translateY(${interpolate(progress, [0, 1], [18, 0])}px)`,
      }}
    >
      {children}
    </div>
  );
}

/** A slab of surface colour with the app's border treatment. */
export function Card({
  children,
  style,
  padding = 34,
}: {
  children: ReactNode;
  style?: CSSProperties;
  padding?: number;
}) {
  return (
    <div
      style={{
        background: theme.surface,
        border: `1px solid ${theme.line}`,
        borderRadius: 18,
        padding,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** The small uppercase label the app uses above a group of figures. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontFamily: font.sans,
        fontSize: 28,
        letterSpacing: 3,
        textTransform: "uppercase",
        color: theme.subtle,
        fontWeight: 500,
      }}
    >
      {children}
    </div>
  );
}

/** A number that counts up to its value as the scene plays. */
export function Counter({
  to,
  delay = 0,
  suffix = "",
  decimals = 0,
}: {
  to: number;
  delay?: number;
  suffix?: string;
  decimals?: number;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200, mass: 0.6 },
  });
  return (
    <span style={{ fontVariantNumeric: "tabular-nums" }}>
      {(to * progress).toFixed(decimals)}
      {suffix}
    </span>
  );
}

/** One statistic, as the dashboard renders it. */
export function Stat({
  label,
  value,
  delay,
  accent = theme.text,
  suffix = "",
  decimals = 0,
}: {
  label: string;
  value: number;
  delay: number;
  accent?: string;
  suffix?: string;
  decimals?: number;
}) {
  return (
    <Reveal delay={delay} style={{ flex: 1 }}>
      <Card style={{ minWidth: 240 }}>
        <div style={{ fontFamily: font.sans, fontSize: 30, color: theme.muted }}>{label}</div>
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 84,
            fontWeight: 600,
            color: accent,
            marginTop: 6,
            letterSpacing: -1,
          }}
        >
          <Counter to={value} delay={delay + 4} suffix={suffix} decimals={decimals} />
        </div>
      </Card>
    </Reveal>
  );
}

/** A bar in the grade distribution. */
export function Bar({
  label,
  value,
  max,
  delay,
  color,
}: {
  label: string;
  value: number;
  max: number;
  delay: number;
  color: string;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const grow = spring({ frame: frame - delay, fps, config: { damping: 200 } });

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
      <div
        style={{
          fontFamily: font.mono,
          fontSize: 34,
          color: theme.muted,
          width: 42,
          textAlign: "right",
        }}
      >
        {label}
      </div>
      <div
        style={{
          flex: 1,
          height: 40,
          background: theme.surfaceRaised,
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${(value / max) * 100 * grow}%`,
            height: "100%",
            background: color,
            borderRadius: 8,
          }}
        />
      </div>
      <div
        style={{
          fontFamily: font.mono,
          fontSize: 32,
          color: theme.subtle,
          width: 58,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {Math.round(value * grow)}
      </div>
    </div>
  );
}

/** A labelled box in the architecture diagram. */
export function Node({
  title,
  subtitle,
  delay,
  color,
}: {
  title: string;
  subtitle: string;
  delay: number;
  color: string;
}) {
  return (
    <Reveal delay={delay}>
      <div
        style={{
          background: theme.surface,
          border: `1px solid ${color}`,
          borderRadius: 14,
          padding: "24px 30px",
          minWidth: 300,
          textAlign: "center",
        }}
      >
        <div style={{ fontFamily: font.mono, fontSize: 34, color, fontWeight: 600 }}>{title}</div>
        <div style={{ fontFamily: font.sans, fontSize: 26, color: theme.subtle, marginTop: 8 }}>
          {subtitle}
        </div>
      </div>
    </Reveal>
  );
}

/** The arrow between two diagram nodes, drawn as it appears. */
export function Arrow({ delay }: { delay: number }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const grow = spring({ frame: frame - delay, fps, config: { damping: 200 } });

  return (
    <div style={{ width: 70, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: `${grow * 100}%`, height: 2, background: theme.line, opacity: grow }} />
      <div
        style={{
          width: 0,
          height: 0,
          borderTop: "7px solid transparent",
          borderBottom: "7px solid transparent",
          borderLeft: `9px solid ${theme.line}`,
          opacity: grow,
        }}
      />
    </div>
  );
}
