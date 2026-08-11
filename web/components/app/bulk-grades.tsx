"use client";

/**
 * Marking one assessment for a whole class.
 *
 * The single-grade dialog asks for a course, a student, a title, a date and a weight
 * per mark — which for a midterm means typing the same four things thirty times and
 * searching for each student by name. Here the assessment is stated once and the
 * roster is the form.
 *
 * **A blank box is a student who was not marked, not a zero.** It is left out of the
 * request entirely. Marking half a class today and half tomorrow is ordinary, and a
 * blank silently becoming a zero is the worst thing this screen could do.
 *
 * One bad mark does not cost the others: the API records what it can and returns the
 * rejections, which is the same contract the import wizard already reports against.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { FieldHelp, FormError, Input } from "@/components/app/detail-fields";
import { Modal } from "@/components/ui/modal";
import { api, ApiError, type Response } from "@/lib/api";
import type { paths } from "@/lib/api-schema";
import { formatNumber, parseLocaleNumber } from "@/lib/format";

type Register = Response<"/courses/{course_id}/enrollments", "get">;
type BulkRequest = paths["/grades/bulk"]["post"]["requestBody"]["content"]["application/json"];
type BulkReport = Response<"/grades/bulk", "post">;

interface Course {
  course_id: string;
  name: string;
  max_grade: number;
  assessments: { name: string; weight: number }[];
}

export function BulkGrades({
  courses,
  initialCourseId,
  locale,
  onClose,
  onSaved,
}: {
  courses: Course[];
  initialCourseId: string;
  locale: string;
  onClose: () => void;
  /** Runs after a commit so the caller can invalidate its caches. */
  onSaved: () => void;
}) {
  const t = useTranslations();
  const [courseId, setCourseId] = useState(initialCourseId || courses[0]?.course_id || "");
  const [code, setCode] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<string[]>([]);
  const [report, setReport] = useState<BulkReport | null>(null);
  const [assessment, setAssessment] = useState("");
  const [weight, setWeight] = useState(formatNumber(1, locale));

  const course = courses.find((candidate) => candidate.course_id === courseId);

  const register = useQuery({
    // The same key the single-grade dialog uses, so the two share a cache entry.
    queryKey: ["course", courseId, "enrollments"],
    queryFn: () => api<Register>(`/courses/${courseId}/enrollments`),
    enabled: courseId !== "",
  });

  // Withdrawn and completed rows come back too. Offering a score box for somebody
  // who left the course invites a mark that nobody meant to record.
  const roster = (register.data ?? []).filter((entry) => entry.status === "active");

  const save = useMutation({
    mutationFn: (body: BulkRequest) => api<BulkReport>("/grades/bulk", { method: "POST", body }),
    onSuccess: (result) => {
      setReport(result);
      setCode(null);
      onSaved();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const weight = parseLocaleNumber(String(data.get("weight") ?? ""), locale);

    const scores: BulkRequest["scores"] = [];
    const rejected: string[] = [];
    for (const entry of roster) {
      const raw = String(data.get(`score-${entry.student_id}`) ?? "").trim();
      if (raw === "") continue; // Not marked. Not zero.
      const score = parseLocaleNumber(raw, locale);
      if (score === null || score < 0 || (course && score > course.max_grade)) {
        rejected.push(entry.student_id);
      } else {
        scores.push({ student_id: entry.student_id, score });
      }
    }

    setInvalid(rejected);
    if (weight === null || rejected.length > 0 || scores.length === 0) {
      setCode("VALIDATION_ERROR");
      return;
    }

    setCode(null);
    save.mutate({
      course_id: courseId,
      title: String(data.get("title") ?? "").trim(),
      date: String(data.get("date") ?? ""),
      weight,
      scores,
    });
  }

  return (
    <Modal
      open
      title={t("grade.bulkTitle")}
      onClose={() => {
        if (!save.isPending) onClose();
      }}
    >
      {report ? (
        <BulkReportView report={report} onClose={onClose} />
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm text-muted">{t("grade.bulkIntro")}</p>

          {/* Controlled, unlike the shared `Select` primitive: changing the course
              refetches the roster, so this one has to know when it changes. */}
          <div>
            <label htmlFor="bulk-course" className="block text-sm text-muted">
              {t("course.one")}
            </label>
            <select
              id="bulk-course"
              value={courseId}
              className="field-input"
              onChange={(event) => {
                setCourseId(event.target.value);
                setAssessment("");
                setWeight(formatNumber(1, locale));
                setInvalid([]);
                setCode(null);
              }}
            >
              {courses.map((option) => (
                <option key={option.course_id} value={option.course_id}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {course && course.assessments.length > 0 ? (
              <div>
                <div className="flex items-center gap-1.5">
                  <label htmlFor="title" className="block text-sm text-muted">
                    {t("grade.title")}
                  </label>
                  <FieldHelp help={t("grade.titleHelp")} />
                </div>
                <select
                  id="title"
                  name="title"
                  value={assessment}
                  className="field-input"
                  onChange={(event) => {
                    const name = event.target.value;
                    setAssessment(name);
                    const selected = course.assessments.find((item) => item.name === name);
                    setWeight(formatNumber(selected?.weight ?? 1, locale));
                  }}
                >
                  <option value="">{t("grade.chooseAssessment")}</option>
                  {course.assessments.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <Input
                key={courseId}
                name="title"
                label={t("grade.title")}
                value=""
                required={false}
                help={t("grade.titleHelp")}
              />
            )}
            <Input name="date" label={t("grade.date")} value="" type="date" />
            <Input
              key={`${courseId}-${assessment}`}
              name="weight"
              label={t("grade.weight")}
              value={weight}
              inputMode="decimal"
              help={t("grade.weightHelp")}
            />
          </div>

          {register.isFetching && <p className="text-sm text-subtle">{t("stats.loading")}</p>}
          {roster.length === 0 && !register.isFetching && (
            <p className="text-sm text-subtle">{t("grade.noStudents")}</p>
          )}

          {/* The roster has no scroller of its own. The UA stylesheet already gives
              <dialog> `max-height: calc(100% - 6px - 2em)` and `overflow: auto`, so
              a second one here only nests a scrollbar inside a scrollbar. */}
          {roster.length > 0 && (
            <div className="rounded-xl border border-line">
              <table className="data-table w-full text-sm">
                <caption className="sr-only">{t("grade.bulkTitle")}</caption>
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-subtle">
                    <th scope="col">{t("student.one")}</th>
                    <th scope="col" className="text-end">
                      {t("grade.score")}
                      {course && (
                        <span className="ms-1 font-normal normal-case text-subtle">
                          /{formatNumber(course.max_grade, locale)}
                        </span>
                      )}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {roster.map((entry) => (
                    <tr key={entry.student_id}>
                      <td>
                        <label htmlFor={`score-${entry.student_id}`}>
                          {entry.first_name} {entry.last_name}
                        </label>
                        <span className="numeric ms-2 text-xs text-subtle">
                          {entry.student_id}
                        </span>
                      </td>
                      <td className="text-end">
                        <input
                          id={`score-${entry.student_id}`}
                          name={`score-${entry.student_id}`}
                          inputMode="decimal"
                          aria-invalid={invalid.includes(entry.student_id)}
                          className={`numeric w-24 rounded-lg border bg-bg px-2 py-1 text-end text-text outline-none focus-visible:border-brand ${
                            invalid.includes(entry.student_id) ? "border-fail" : "border-line"
                          }`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {invalid.length > 0 && <FormError>{t("grade.invalidScore")}</FormError>}
          {code && invalid.length === 0 && (
            <FormError>{t(`error.${code}` as "error.unknown")}</FormError>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              {t("action.cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={save.isPending || register.isFetching || roster.length === 0}
            >
              {save.isPending ? t("grade.saving") : t("action.save")}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

/**
 * What landed and what did not.
 *
 * Shown instead of closing on success, because a partial commit is the interesting
 * case: twenty-nine marks recorded and one rejected is a result the teacher has to
 * read, not a dialog that should vanish.
 */
function BulkReportView({
  report,
  onClose,
}: {
  report: BulkReport;
  onClose: () => void;
}) {
  const t = useTranslations();

  return (
    <div className="space-y-4">
      <p role="status" className="rounded-lg bg-pass-bg px-3 py-2 text-sm text-pass">
        {t("grade.bulkSaved", { count: report.imported })}
      </p>

      {report.errors.length > 0 && (
        <div className="rounded-xl border border-fail/40 bg-fail-bg p-4">
          <p className="text-sm font-medium text-fail">
            {t("grade.bulkRejected", { count: report.skipped })}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-fail">
            {report.errors.map((error) => (
              <li key={error.student_id} className="numeric">
                {error.student_id} — {t(`error.${error.code}` as "error.unknown")}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex justify-end pt-2">
        <button type="button" className="btn btn-primary" onClick={onClose}>
          {t("action.close")}
        </button>
      </div>
    </div>
  );
}
