import { describe, expect, it } from "vitest";

import { readCourseAssessments } from "../course-assessments";

describe("readCourseAssessments", () => {
  it("pairs repeated fields in order and parses weights in the user's locale", () => {
    const data = new FormData();
    data.append("assessment_names", " Zwischenprüfung ");
    data.append("assessment_weights", "1,5");
    data.append("assessment_names", "Abschlussprüfung");
    data.append("assessment_weights", "3");

    expect(readCourseAssessments(data, "de")).toEqual([
      { name: "Zwischenprüfung", weight: 1.5 },
      { name: "Abschlussprüfung", weight: 3 },
    ]);
  });

  it("allows a course to have no assessment scheme", () => {
    expect(readCourseAssessments(new FormData(), "en")).toEqual([]);
  });

  it("returns null when any weight is not a locale-formatted number", () => {
    const data = new FormData();
    data.append("assessment_names", "Midterm");
    data.append("assessment_weights", "not a number");

    expect(readCourseAssessments(data, "en")).toBeNull();
  });
});
