/**
 * The project overview: six scenes, twenty-four seconds.
 *
 * It shows what the system *is* — the layering, the scope model, the AI boundary,
 * the gates — rather than pretending to be a screen recording. There are no
 * screenshots of the running application here, and that is deliberate: a fake
 * screenshot is worse than none, and the honest alternative is to say what the
 * software does and how it is built.
 */

import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

import { Arrow, Bar, Card, Eyebrow, Node, Reveal, Stat } from "./parts";
import { font, theme } from "./theme";

const FPS = 30;
const SCENE = 4 * FPS;

/** Common frame: the page background, and a hairline that tracks progress. */
function Frame({ children }: { children: React.ReactNode }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      {children}
      <div
        style={{
          position: "absolute",
          left: 0,
          bottom: 0,
          height: 4,
          width: `${(frame / durationInFrames) * 100}%`,
          background: theme.brand,
          opacity: 0.7,
        }}
      />
    </AbsoluteFill>
  );
}

/** Every scene sits in the same padded column. */
function Scene({ children }: { children: React.ReactNode }) {
  const frame = useCurrentFrame();
  // Fade the last 8 frames so scenes hand over rather than cut.
  const out = interpolate(frame, [SCENE - 8, SCENE], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      style={{
        padding: 90,
        justifyContent: "center",
        gap: 34,
        opacity: out,
      }}
    >
      {children}
    </AbsoluteFill>
  );
}

function Title() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>Notenverwaltung</Eyebrow>
      </Reveal>
      <Reveal delay={6}>
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 104,
            fontWeight: 700,
            color: theme.text,
            letterSpacing: -3,
            lineHeight: 1.05,
          }}
        >
          Grade Tracker
        </div>
      </Reveal>
      <Reveal delay={14}>
        <div style={{ fontFamily: font.sans, fontSize: 34, color: theme.muted, maxWidth: 1180 }}>
          Academic records, reporting and AI-assisted workflows — for the people who
          actually have to enter the marks.
        </div>
      </Reveal>
      <Reveal delay={22}>
        <div style={{ display: "flex", gap: 14, marginTop: 10 }}>
          {["FastAPI", "SQLite / WAL", "Next.js 16", "React 19", "TypeScript"].map((tag) => (
            <div
              key={tag}
              style={{
                fontFamily: font.mono,
                fontSize: 22,
                color: theme.muted,
                border: `1px solid ${theme.line}`,
                borderRadius: 999,
                padding: "8px 20px",
              }}
            >
              {tag}
            </div>
          ))}
        </div>
      </Reveal>
    </Scene>
  );
}

function Dashboard() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>At a glance</Eyebrow>
      </Reveal>
      <div style={{ display: "flex", gap: 22 }}>
        <Stat label="Students" value={248} delay={6} />
        <Stat label="Courses" value={31} delay={12} />
        <Stat label="Marks recorded" value={4187} delay={18} />
        <Stat label="At risk" value={12} delay={24} accent={theme.warn} />
      </div>
      <Reveal delay={30}>
        <Card style={{ marginTop: 8 }}>
          <div style={{ fontFamily: font.sans, fontSize: 22, color: theme.muted, marginBottom: 20 }}>
            Grade distribution
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Bar label="A" value={54} max={96} delay={34} color={theme.accent} />
            <Bar label="B" value={96} max={96} delay={38} color={theme.accent} />
            <Bar label="C" value={71} max={96} delay={42} color={theme.brand} />
            <Bar label="D" value={38} max={96} delay={46} color={theme.warn} />
            <Bar label="F" value={17} max={96} delay={50} color={theme.fail} />
          </div>
        </Card>
      </Reveal>
    </Scene>
  );
}

function Layers() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>Layers that only depend downward</Eyebrow>
      </Reveal>
      <Reveal delay={5}>
        <div style={{ fontFamily: font.sans, fontSize: 34, color: theme.muted }}>
          The rule is tested, not documented.
        </div>
      </Reveal>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 26,
        }}
      >
        <Node title="api/routers" subtitle="HTTP only" delay={12} color={theme.brand} />
        <Arrow delay={20} />
        <Node title="services" subtitle="use cases" delay={24} color={theme.brand} />
        <Arrow delay={32} />
        <Node title="storage" subtitle="SQL only" delay={36} color={theme.accent} />
        <Arrow delay={44} />
        <Node title="models" subtitle="domain types" delay={48} color={theme.accent} />
      </div>
      <Reveal delay={56}>
        <div
          style={{
            fontFamily: font.mono,
            fontSize: 24,
            color: theme.subtle,
            marginTop: 20,
            borderLeft: `2px solid ${theme.line}`,
            paddingLeft: 22,
          }}
        >
          tests/unit/test_architecture.py — an upward import fails the build
        </div>
      </Reveal>
    </Scene>
  );
}

function Scope() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>Authorization is a value, not a branch</Eyebrow>
      </Reveal>
      <Reveal delay={6}>
        <Card padding={38}>
          <div style={{ fontFamily: font.mono, fontSize: 34, lineHeight: 1.85 }}>
            <div style={{ color: theme.subtle }}># the default</div>
            <div style={{ color: theme.text }}>
              DENY_ALL = Scope(<span style={{ color: theme.accent }}>&quot;1=0&quot;</span>)
            </div>
          </div>
        </Card>
      </Reveal>
      <Reveal delay={20}>
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 32,
            color: theme.muted,
            maxWidth: 1180,
            lineHeight: 1.5,
            marginTop: 10,
          }}
        >
          A query handed no scope returns <span style={{ color: theme.text }}>nothing</span>. A
          forgotten filter shows up as an empty table, which someone reports — the opposite
          default shows up as one student reading another&apos;s grades, which nobody reports.
        </div>
      </Reveal>
    </Scene>
  );
}

function Assistant() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>The model never writes</Eyebrow>
      </Reveal>
      <Reveal delay={6}>
        <Card padding={34}>
          <div style={{ fontFamily: font.sans, fontSize: 30, color: theme.text }}>
            &ldquo;Which students are failing Databases?&rdquo;
          </div>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 23,
              color: theme.accent,
              marginTop: 20,
              paddingTop: 20,
              borderTop: `1px solid ${theme.line}`,
            }}
          >
            query_grades(course_id=&quot;CS201&quot;, passing=false)
          </div>
          <div style={{ fontFamily: font.mono, fontSize: 22, color: theme.subtle, marginTop: 10 }}>
            → 3 rows, composed with the caller&apos;s own scope
          </div>
        </Card>
      </Reveal>
      <Reveal delay={24}>
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 30,
            color: theme.muted,
            maxWidth: 1180,
            lineHeight: 1.5,
          }}
        >
          It picks filters from a fixed schema; Python composes the SQL. Write tools have
          schemas and <span style={{ color: theme.text }}>no handlers</span> — a proposal
          cannot execute. The answer arrives above the rows it came from.
        </div>
      </Reveal>
    </Scene>
  );
}

function Gates() {
  return (
    <Scene>
      <Reveal>
        <Eyebrow>What has to pass before anything merges</Eyebrow>
      </Reveal>
      <div style={{ display: "flex", gap: 22, marginTop: 14 }}>
        <Stat label="Backend coverage" value={93.4} delay={6} suffix="%" decimals={1} accent={theme.accent} />
        <Stat label="Backend tests" value={865} delay={12} />
        <Stat label="Frontend tests" value={213} delay={18} />
        <Stat label="Type errors" value={0} delay={24} accent={theme.accent} />
      </div>
      <Reveal delay={32}>
        <Card style={{ marginTop: 10 }}>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 25,
              color: theme.muted,
              display: "flex",
              flexWrap: "wrap",
              gap: "14px 34px",
            }}
          >
            {[
              "ruff (bandit, bugbear)",
              "pyright --strict",
              "eslint + jsx-a11y",
              "tsc --noEmit",
              "openapi drift gate",
              "api-schema drift gate",
            ].map((gate) => (
              <span key={gate}>
                <span style={{ color: theme.accent }}>✓</span> {gate}
              </span>
            ))}
          </div>
        </Card>
      </Reveal>
      <Reveal delay={44}>
        <div style={{ fontFamily: font.sans, fontSize: 28, color: theme.subtle, marginTop: 12 }}>
          Three locales · WCAG contrast enforced at save time · append-only audit trail
        </div>
      </Reveal>
    </Scene>
  );
}

export function Overview() {
  const scenes = [Title, Dashboard, Layers, Scope, Assistant, Gates];
  return (
    <Frame>
      {scenes.map((Component, index) => (
        <Sequence key={Component.name} from={index * SCENE} durationInFrames={SCENE}>
          <Component />
        </Sequence>
      ))}
    </Frame>
  );
}

export const OVERVIEW_DURATION = 6 * SCENE;
export const OVERVIEW_FPS = FPS;
