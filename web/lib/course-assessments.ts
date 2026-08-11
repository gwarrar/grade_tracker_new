import { parseLocaleNumber } from "./format";

export interface CourseAssessment {
  name: string;
  weight: number;
}

/** Read the ordered assessment rows rendered by a course form. */
export function readCourseAssessments(
  data: FormData,
  locale: string,
): CourseAssessment[] | null {
  const names = data.getAll("assessment_names").map(String);
  const weights = data.getAll("assessment_weights").map(String);
  if (names.length !== weights.length) return null;

  const assessments: CourseAssessment[] = [];
  for (let index = 0; index < names.length; index += 1) {
    const weight = parseLocaleNumber(weights[index] ?? "", locale);
    if (weight === null) return null;
    assessments.push({ name: (names[index] ?? "").trim(), weight });
  }
  return assessments;
}
