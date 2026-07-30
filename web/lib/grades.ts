/**
 * Grouping and averaging a student's marks.
 *
 * Pure, so the arithmetic can be tested without React — and the arithmetic is the
 * part worth testing, because a weighted mean computed the obvious wrong way (mean of
 * percentages, ignoring weight) is off by an amount nobody notices until a student
 * queries their transcript.
 *
 * The server already returns a `letter` per grade and an `average_percentage` for the
 * report as a whole. These helpers only cover what the server does not: the split by
 * course, and the per-course average within it.
 */

/** The subset of a report's grade line these helpers need. */
export interface Line {
  course_id: string;
  course_name: string;
  percentage: number;
  weight: number;
  is_passing: boolean;
}

/** One course's marks, with its own average. */
export interface CourseGroup<T extends Line> {
  course_id: string;
  course_name: string;
  lines: T[];
  /** Weighted mean percentage, or null when the course has no marks. */
  average: number | null;
  passed: number;
  failed: number;
}

/**
 * Weighted mean of a set of percentages.
 *
 * Weighted, not a plain mean: a final worth 3 and a quiz worth 1 must not count
 * equally, which is the entire reason `weight` exists on a grade.
 *
 * @param lines - The marks to average.
 * @returns The mean, or null when there is nothing to average. Null rather than 0,
 *   because "no marks yet" and "averaged zero" are different facts and rendering the
 *   first as 0% is a false statement about the student.
 */
export function weightedAverage(lines: readonly Line[]): number | null {
  if (lines.length === 0) return null;

  const totalWeight = lines.reduce((sum, line) => sum + line.weight, 0);
  // Every weight being zero would divide to NaN. The API forbids it (weight > 0), so
  // this is a guard against a future shape change rather than a live case.
  if (totalWeight <= 0) return null;

  const weighted = lines.reduce((sum, line) => sum + line.percentage * line.weight, 0);
  return weighted / totalWeight;
}

/**
 * Split a report's marks into one group per course.
 *
 * Order follows first appearance rather than being sorted by name: the caller hands
 * these in the order the server chose (newest first), and re-sorting here would
 * silently override a deliberate ordering.
 *
 * @param lines - Every mark in the report.
 * @returns One group per course, each with its own weighted average.
 */
export function groupByCourse<T extends Line>(lines: readonly T[]): CourseGroup<T>[] {
  const groups = new Map<string, CourseGroup<T>>();

  for (const line of lines) {
    let group = groups.get(line.course_id);
    if (!group) {
      group = {
        course_id: line.course_id,
        course_name: line.course_name,
        lines: [],
        average: null,
        passed: 0,
        failed: 0,
      };
      groups.set(line.course_id, group);
    }
    group.lines.push(line);
    if (line.is_passing) group.passed += 1;
    else group.failed += 1;
  }

  for (const group of groups.values()) {
    group.average = weightedAverage(group.lines);
  }

  return [...groups.values()];
}
