/**
 * The per-course arithmetic behind a student's record.
 *
 * The case that matters is weighting: a mean of percentages that ignores `weight`
 * looks right on evenly weighted data and is quietly wrong the moment a final counts
 * for more than a quiz. So every average test uses uneven weights — on equal weights
 * a broken implementation and a correct one agree, and the test would prove nothing.
 */

import { describe, expect, it } from "vitest";

import { groupByCourse, weightedAverage, type Line } from "../grades";

const line = (over: Partial<Line> = {}): Line => ({
  course_id: "CS101",
  course_name: "Intro",
  percentage: 80,
  weight: 1,
  is_passing: true,
  ...over,
});

describe("weightedAverage", () => {
  it("weights each mark by its weight", () => {
    // 90*3 + 50*1 = 320, over weight 4 => 80. An unweighted mean would say 70.
    const result = weightedAverage([
      line({ percentage: 90, weight: 3 }),
      line({ percentage: 50, weight: 1 }),
    ]);

    expect(result).toBe(80);
  });

  it("is null with no marks, not zero", () => {
    // "Not assessed yet" and "scored nothing" are different facts, and rendering the
    // first as 0% is a false statement about a student.
    expect(weightedAverage([])).toBeNull();
  });

  it("handles a single mark", () => {
    expect(weightedAverage([line({ percentage: 73, weight: 5 })])).toBe(73);
  });

  it("returns null rather than NaN if the weights sum to zero", () => {
    expect(weightedAverage([line({ percentage: 90, weight: 0 })])).toBeNull();
  });
});

describe("groupByCourse", () => {
  const lines = [
    line({ course_id: "CS101", course_name: "Intro", percentage: 90, weight: 3 }),
    line({ course_id: "MA110", course_name: "Maths", percentage: 40, is_passing: false }),
    line({ course_id: "CS101", course_name: "Intro", percentage: 50, weight: 1 }),
  ];

  it("puts each course's marks together", () => {
    const groups = groupByCourse(lines);

    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.course_id)).toEqual(["CS101", "MA110"]);
    expect(groups[0]?.lines).toHaveLength(2);
  });

  it("averages a course's marks the way the server does", () => {
    // The per-course average moved to the server when the GPA needed one, so the
    // component no longer computes it. This still pins the definition the server's
    // number has to match — a divergence in either direction fails here.
    const [intro] = groupByCourse(lines);
    if (!intro) throw new Error("groupByCourse must produce the intro course");

    expect(weightedAverage(intro.lines)).toBe(80);
  });

  it("counts passes and failures per course", () => {
    const [intro, maths] = groupByCourse(lines);
    if (!intro || !maths) throw new Error("groupByCourse must produce both courses");

    expect([intro.passed, intro.failed]).toEqual([2, 0]);
    expect([maths.passed, maths.failed]).toEqual([0, 1]);
  });

  it("keeps the order the server chose", () => {
    // The server sorts newest first; re-sorting by name here would silently override
    // a deliberate ordering.
    expect(groupByCourse(lines).map((g) => g.course_id)).toEqual(["CS101", "MA110"]);
    expect(groupByCourse([...lines].reverse()).map((g) => g.course_id)).toEqual([
      "CS101",
      "MA110",
    ]);
  });

  it("is empty for a student with no marks", () => {
    expect(groupByCourse([])).toEqual([]);
  });
});
