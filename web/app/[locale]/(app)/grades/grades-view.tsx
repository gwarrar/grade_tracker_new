"use client";

/**
 * Grades list with the sliding detail panel.
 *
 * This is the page where locale number handling stops being cosmetic. A German
 * user types `88,5`; parsed with `Number()` that is `NaN`, and parsed by stripping
 * the comma it is `885`. Both are wrong, and only one of them is obviously wrong.
 * Every figure goes through `parseLocaleNumber`, which returns null rather than
 * guessing.
 *
 * The edit is optimistic: the score updates on screen immediately and rolls back
 * if the server rejects it. Correcting a mistyped grade is the single most common
 * action here, and a round trip per keystroke-worth of correction is what makes an
 * interface feel slow.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { AssistantPanel } from "@/components/app/assistant";
import { AuditEntryLine } from "@/components/app/audit";
import { Field, FormError, Input, PanelHeader, Select, Textarea } from "@/components/app/detail-fields";
import { MasterDetail } from "@/components/app/master-detail";
import { Pager } from "@/components/app/pager";
import { Confirm } from "@/components/ui/confirm";
import { Modal } from "@/components/ui/modal";
import { api, ApiError, type Response } from "@/lib/api";
import type { paths } from "@/lib/api-schema";
import { formatDate, formatNumber, formatPercent, parseLocaleNumber } from "@/lib/format";
import { can } from "@/lib/permissions";
import type { Me } from "@/lib/session";
import { useDebounced, useSelection, useUrlParam } from "@/lib/use-selection";

type Grade = Response<"/grades/{grade_id}", "get">;
type Page = Response<"/grades", "get">;
type Courses = Response<"/courses", "get">;
type Register = Response<"/courses/{course_id}/enrollments", "get">;
type History = Response<"/grades/{grade_id}/history", "get">;
type GradeCreate = paths["/grades"]["post"]["requestBody"]["content"]["application/json"];

const PAGE_SIZE = 50;

/** Sortable columns, mapped to the API's sort keys. */
const SORTABLE = {
  student: "student",
  title: "title",
  course: "course",
  date: "date",
  percentage: "percentage",
} as const;

export function GradesView({
  me,
  locale,
  bands,
}: {
  me: Me;
  locale: string;
  /** Band labels from the organisation's scale — configurable, so never hard-coded. */
  bands: string[];
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const [selectedId, select] = useSelection();
  const [search, setSearch] = useState("");
  const [asking, setAsking] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createCode, setCreateCode] = useState<string | null>(null);
  const [invalidScore, setInvalidScore] = useState(false);
  const [invalidWeight, setInvalidWeight] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [studentSearch, setStudentSearch] = useState("");
  const query = useDebounced(search.trim());
  const studentQuery = useDebounced(studentSearch.trim());
  const studentSearchUnsettled = studentQuery !== studentSearch.trim();

  // Filters live in the URL, not in state: a filtered list is then linkable, Back
  // steps through filter changes, and a refresh keeps what you were looking at.
  // Every setter preserves the other parameters — see lib/use-selection.ts, where
  // getting that wrong once already reset the whole bar on every row click.
  const [courseId, setCourseId] = useUrlParam("course_id");
  const [letter, setLetter] = useUrlParam("letter");
  const [dateFrom, setDateFrom] = useUrlParam("date_from");
  const [dateTo, setDateTo] = useUrlParam("date_to");
  const [sort, setSort] = useUrlParam("sort", "-date");
  const [pageParam, setPage] = useUrlParam("page", "1");
  const page = Math.max(1, Number(pageParam) || 1);

  const filtered = Boolean(courseId || letter || dateFrom || dateTo || query);

  // For the course filter. Only staff see more than their own courses anyway, and
  // the API scopes this exactly as it scopes the grades themselves.
  const courses = useQuery({
    queryKey: ["courses", "grade-picker"],
    queryFn: () => api<Courses>("/courses", { query: { size: 200, sort: "name" } }),
    staleTime: 5 * 60_000,
  });

  const list = useQuery({
    queryKey: ["grades", { query, courseId, letter, dateFrom, dateTo, sort, page }],
    queryFn: () =>
      api<Page>("/grades", {
        query: {
          q: query,
          size: PAGE_SIZE,
          page,
          sort,
          // Empty strings would become `?course_id=` and filter on nothing.
          ...(courseId ? { course_id: courseId } : {}),
          ...(letter ? { letter } : {}),
          ...(dateFrom ? { date_from: dateFrom } : {}),
          ...(dateTo ? { date_to: dateTo } : {}),
        },
      }),
    placeholderData: (previous) => previous,
  });

  /** Toggle a column between ascending and descending. */
  const toggleSort = (key: string) => setSort(sort === key ? `-${key}` : key);

  /** `aria-sort` for a header, so the order is announced and not only drawn. */
  const sortState = (key: string): "ascending" | "descending" | "none" =>
    sort === key ? "ascending" : sort === `-${key}` ? "descending" : "none";

  const detail = useQuery({
    queryKey: ["grade", selectedId],
    queryFn: () => api<Grade>(`/grades/${selectedId}`),
    enabled: selectedId !== null,
  });

  const register = useQuery({
    queryKey: ["course", selectedCourseId, "enrollments"],
    queryFn: () => api<Register>(`/courses/${selectedCourseId}/enrollments`),
    enabled: creating && selectedCourseId !== "" && can.writeGrade(me),
    staleTime: 0,
  });

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["grades"] }),
      queryClient.invalidateQueries({ queryKey: ["grade"] }),
      queryClient.invalidateQueries({ queryKey: ["grade-history"] }),
      queryClient.invalidateQueries({ queryKey: ["reports"] }),
      queryClient.invalidateQueries({ queryKey: ["report"] }),
      queryClient.invalidateQueries({ queryKey: ["students"] }),
      queryClient.invalidateQueries({ queryKey: ["student"] }),
      queryClient.invalidateQueries({ queryKey: ["courses"] }),
      queryClient.invalidateQueries({ queryKey: ["course"] }),
      queryClient.invalidateQueries({ queryKey: ["analytics"] }),
      queryClient.invalidateQueries({ queryKey: ["palette"] }),
    ]);

  const create = useMutation({
    mutationFn: (body: GradeCreate) => api<Grade>("/grades", { method: "POST", body }),
    onSuccess: (grade) => {
      setCreating(false);
      setCreateCode(null);
      setInvalidScore(false);
      setInvalidWeight(false);
      setStudentSearch("");
      setNotice(t("grade.created"));
      select(String(grade.grade_id));
      void refresh();
    },
    onError: (error) =>
      setCreateCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  function createGrade(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const score = parseLocaleNumber(String(data.get("score") ?? ""), locale);
    const weight = parseLocaleNumber(String(data.get("weight") ?? ""), locale);
    const studentId = String(data.get("student_id") ?? "");
    const validStudent = register.data?.some(
      (entry) => entry.student_id === studentId && entry.status === "active",
    );

    setInvalidScore(score === null);
    setInvalidWeight(weight === null);
    if (score === null || weight === null || studentSearchUnsettled || !validStudent) {
      setCreateCode("VALIDATION_ERROR");
      return;
    }

    setCreateCode(null);
    setNotice(null);
    create.mutate({
      course_id: String(data.get("course_id") ?? ""),
      student_id: studentId,
      title: String(data.get("title") ?? "").trim(),
      score,
      weight,
      notes: String(data.get("notes") ?? "").trim(),
      date: String(data.get("date") ?? ""),
    });
  }

  const rows = list.data?.items ?? [];
  const selectedCourse = courses.data?.items.find(
    (course) => course.course_id === selectedCourseId,
  );
  const matchingStudents =
    !studentSearchUnsettled && studentQuery.length >= 2
      ? (register.data ?? []).filter((entry) => {
          const haystack = `${entry.student_id} ${entry.first_name ?? ""} ${entry.last_name ?? ""} ${entry.email ?? ""}`.toLocaleLowerCase(
            locale,
          );
          return entry.status === "active" && haystack.includes(studentQuery.toLocaleLowerCase(locale));
        })
      : [];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("grade.other")}
          {list.data && (
            <span className="numeric ms-3 text-base font-normal text-subtle">
              {formatNumber(list.data.total, locale)}
            </span>
          )}
        </h1>

        <div className="flex flex-wrap items-center gap-2">
          {can.writeGrade(me) && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setCreateCode(null);
                setInvalidScore(false);
                setInvalidWeight(false);
                setStudentSearch("");
                setNotice(null);
                setSelectedCourseId(
                  courses.data?.items.some((course) => course.course_id === courseId)
                    ? courseId
                    : courses.data?.items[0]?.course_id || "",
                );
                setCreating(true);
              }}
            >
              {t("grade.add")}
            </button>
          )}
          <button
            type="button"
            onClick={() => setAsking((current) => !current)}
            aria-expanded={asking}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("assistant.ask")}
          </button>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("action.search")}
            aria-label={t("action.search")}
            className="w-56 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </div>
      </div>

      {asking && (
        <div className="mb-6">
          <AssistantPanel onClose={() => setAsking(false)} />
        </div>
      )}

      {notice && (
        <p role="status" className="mb-4 rounded-lg bg-pass-bg px-3 py-2 text-sm text-pass">
          {notice}
        </p>
      )}

      {creating && (
        <Modal
          open
          title={t("grade.createTitle")}
          onClose={() => {
            if (!create.isPending) {
              setCreating(false);
              setCreateCode(null);
              setInvalidScore(false);
              setInvalidWeight(false);
            }
          }}
        >
          {courses.isPending && <p className="text-sm text-subtle">{t("stats.loading")}</p>}
          {courses.error && (
            <FormError>
              {t(
                `error.${courses.error instanceof ApiError ? courses.error.code : "NETWORK_ERROR"}` as "error.unknown",
              )}
            </FormError>
          )}
          {courses.isSuccess && courses.data.items.length === 0 && (
            <p role="status" className="text-sm text-subtle">
              {t("grade.noCourses")}
            </p>
          )}
          {courses.isSuccess && courses.data.items.length > 0 && (
            <form onSubmit={createGrade} className="max-h-[70vh] space-y-4 overflow-y-auto pe-1">
              <div>
                <label htmlFor="grade-course" className="block text-sm text-muted">
                  {t("course.one")}
                </label>
                <select
                  id="grade-course"
                  name="course_id"
                  required
                  className="field-input"
                  defaultValue={selectedCourseId}
                  onChange={(event) => {
                    setSelectedCourseId(event.target.value);
                    setStudentSearch("");
                    setCreateCode(null);
                  }}
                >
                  <option value="" disabled>
                    {t("grade.chooseCourse")}
                  </option>
                  {courses.data.items.map((course) => (
                    <option key={course.course_id} value={course.course_id}>
                      {course.name}
                    </option>
                  ))}
                </select>
              </div>
              {selectedCourseId && register.isFetching && (
                <p className="text-sm text-subtle">{t("stats.loading")}</p>
              )}
              {register.error && (
                <FormError>
                  {t(
                    `error.${register.error instanceof ApiError ? register.error.code : "NETWORK_ERROR"}` as "error.unknown",
                  )}
                </FormError>
              )}
              {register.isSuccess && !register.isFetching && (
                <div>
                  <label htmlFor="grade-student-search" className="block text-sm text-muted">
                    {t("grade.searchStudents")}
                  </label>
                  <input
                    id="grade-student-search"
                    type="search"
                    value={studentSearch}
                    onChange={(event) => setStudentSearch(event.target.value)}
                    className="field-input"
                    aria-describedby="grade-student-search-hint"
                  />
                  <p id="grade-student-search-hint" className="mt-1 text-xs text-subtle">
                    {t("grade.searchHint")}
                  </p>
                  {studentQuery.length >= 2 && matchingStudents.length > 0 && (
                    <Select
                      key={`${selectedCourseId}-${studentQuery}`}
                      name="student_id"
                      label={t("student.one")}
                      value={matchingStudents[0].student_id}
                    >
                      {matchingStudents.map((student) => (
                        <option key={student.student_id} value={student.student_id}>
                          {student.student_id} — {student.first_name} {student.last_name}
                        </option>
                      ))}
                    </Select>
                  )}
                  {!studentSearchUnsettled &&
                    studentQuery.length >= 2 &&
                    matchingStudents.length === 0 && (
                    <p role="status" className="mt-3 text-sm text-subtle">
                      {t("grade.noStudents")}
                    </p>
                  )}
                </div>
              )}

              <Input name="title" label={t("grade.title")} value="" />
              <div>
                <Input
                  name="score"
                  label={t("grade.score")}
                  value=""
                  inputMode="decimal"
                  hint={
                    selectedCourse
                      ? `${t("grade.max")}: ${formatNumber(selectedCourse.max_grade, locale)}`
                      : undefined
                  }
                />
                {invalidScore && <FormError>{t("grade.invalidScore")}</FormError>}
              </div>
              <div>
                <Input
                  name="weight"
                  label={t("grade.weight")}
                  value={formatNumber(1, locale)}
                  inputMode="decimal"
                />
                {invalidWeight && <FormError>{t("grade.invalidWeight")}</FormError>}
              </div>
              <Textarea name="notes" label={t("grade.notes")} value="" required={false} />
              <Input name="date" label={t("grade.date")} value="" type="date" />
              {createCode &&
                (createCode !== "VALIDATION_ERROR" || (!invalidScore && !invalidWeight)) && (
                <FormError>{t(`error.${createCode}` as "error.unknown")}</FormError>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={create.isPending}
                  onClick={() => {
                    setCreating(false);
                    setCreateCode(null);
                    setInvalidScore(false);
                    setInvalidWeight(false);
                  }}
                >
                  {t("action.cancel")}
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={
                    create.isPending ||
                    register.isFetching ||
                    !register.isSuccess ||
                    studentSearchUnsettled ||
                    matchingStudents.length === 0
                  }
                >
                  {t("action.save")}
                </button>
              </div>
            </form>
          )}
        </Modal>
      )}

      {/* One row above the table rather than a collapsible drawer: with thousands of
          rows the filters are the primary control, and hiding them behind a toggle
          makes the table look like the only thing on the page. */}
      <fieldset className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-surface px-4 py-3">
        <legend className="sr-only">{t("filter.label")}</legend>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("course.one")}
          <select
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
            className="w-48 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <option value="">{t("filter.all")}</option>
            {(courses.data?.items ?? []).map((course) => (
              <option key={course.course_id} value={course.course_id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("grade.letter")}
          <select
            value={letter}
            onChange={(event) => setLetter(event.target.value)}
            className="w-28 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <option value="">{t("filter.all")}</option>
            {/* From the organisation's scale, not a hard-coded A–F: an institution
                that renamed its bands would otherwise get a filter listing bands it
                does not use. */}
            {bands.map((band) => (
              <option key={band} value={band}>
                {band}
              </option>
            ))}
          </select>
        </label>

        {/* Native date inputs: they bring the locale's own format and calendar, and a
            picker component would ship a dependency to reproduce that badly. */}
        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("filter.from")}
          <input
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            className="rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("filter.to")}
          <input
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </label>

        {filtered && (
          <button
            type="button"
            onClick={() => {
              setCourseId(null);
              setLetter(null);
              setDateFrom(null);
              setDateTo(null);
              setSearch("");
            }}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("filter.clear")}
          </button>
        )}
      </fieldset>

      <MasterDetail
        detailKey={creating ? null : selectedId}
        detail={
          !creating && selectedId && (
            <GradeDetail
              key={selectedId}
              gradeId={selectedId}
              grade={detail.data}
              loading={detail.isPending}
              error={detail.error}
              editable={can.writeGrade(me)}
              locale={locale}
              onClose={() => select(null)}
              onSaved={() => {
                void refresh();
              }}
              onDeleted={() => {
                setNotice(t("grade.retired"));
                select(null);
                void refresh();
              }}
            />
          )
        }
      >
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("grade.other")}</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
                {(
                  [
                    [SORTABLE.student, t("student.one"), "start"],
                    [SORTABLE.title, t("grade.title"), "start"],
                    // The course column: without it "Anna — Midterm — 78%" does not
                    // say *which* midterm, which is the whole problem once a listing
                    // spans more than one course.
                    [SORTABLE.course, t("course.one"), "start"],
                    [SORTABLE.date, t("grade.date"), "start"],
                    [SORTABLE.percentage, t("grade.percentage"), "end"],
                  ] as const
                ).map(([key, label, align]) => (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={sortState(key)}
                    className={`px-4 py-2.5 font-medium ${align === "end" ? "text-end" : ""}`}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(key)}
                      aria-label={t("filter.sortBy", { field: label })}
                      className="inline-flex items-center gap-1 uppercase tracking-wide outline-none transition-colors hover:text-text focus-visible:ring-2 focus-visible:ring-brand/40"
                    >
                      {label}
                      {/* A caret only on the active column, so the header row does not
                          read as five interactive arrows competing for attention. */}
                      <span aria-hidden className="text-[0.65rem]">
                        {sortState(key) === "ascending"
                          ? "▲"
                          : sortState(key) === "descending"
                            ? "▼"
                            : ""}
                      </span>
                    </button>
                  </th>
                ))}
                <th scope="col" className="px-4 py-2.5 text-end font-medium">
                  {t("grade.letter")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((grade) => {
                const active = String(grade.grade_id) === selectedId;
                return (
                  <tr
                    key={grade.grade_id}
                    className={`border-b border-line last:border-0 transition-colors ${
                      active ? "bg-bg-subtle" : "hover:bg-bg-subtle"
                    }`}
                  >
                    <td className="px-4 py-0">
                      <button
                        type="button"
                        onClick={() => select(String(grade.grade_id))}
                        aria-current={active ? "true" : undefined}
                        className="-mx-4 w-[calc(100%+2rem)] px-4 py-2.5 text-start text-text outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
                      >
                        {grade.student_name}
                      </button>
                    </td>
                    <td className="truncate px-4 py-2.5 text-muted">{grade.title}</td>
                    <td className="truncate px-4 py-2.5 text-muted">{grade.course_name}</td>
                    <td className="numeric px-4 py-2.5 text-muted">
                      {formatDate(grade.date, locale)}
                    </td>
                    <td className="numeric px-4 py-2.5 text-end">
                      {/* Colour is not the only signal — the pass/fail word is in the
                          panel, and the figure itself carries the meaning. A red
                          number alone excludes anyone who cannot distinguish it. */}
                      <span className={grade.is_passing ? "text-text" : "text-fail"}>
                        {formatPercent(grade.percentage, locale)}
                      </span>
                    </td>
                    <td className="numeric px-4 py-2.5 text-end font-medium text-text">
                      {/* The band, computed server-side against the organisation's
                          scale — so this column and the report can never disagree. */}
                      {grade.letter}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {list.isPending && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.loading")}</p>
          )}
          {!list.isPending && rows.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
          )}

          <Pager
            page={page}
            size={PAGE_SIZE}
            total={list.data?.total ?? 0}
            locale={locale}
            labels={{
              previous: t("pager.previous"),
              next: t("pager.next"),
              status: (current, pages) => t("pager.page", { page: current, pages }),
            }}
            onPage={(next) => setPage(String(next))}
          />
        </div>
      </MasterDetail>
    </>
  );
}

function GradeDetail({
  gradeId,
  grade,
  loading,
  error,
  editable,
  locale,
  onClose,
  onSaved,
  onDeleted,
}: {
  gradeId: string;
  grade: Grade | undefined;
  loading: boolean;
  error: unknown;
  /** Teacher and above. A student reading their own marks gets no edit control. */
  editable: boolean;
  locale: string;
  onClose: () => void;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [retiring, setRetiring] = useState(false);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/grades/${gradeId}`, { method: "PATCH", body }),

    // Optimistic: write the new figures into the cache before the request lands.
    onMutate: async (body) => {
      const key = ["grade", gradeId];
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Grade>(key);

      if (previous && typeof body.score === "number") {
        const percentage = (body.score / previous.max_grade) * 100;
        queryClient.setQueryData<Grade>(key, {
          ...previous,
          score: body.score,
          percentage,
          title: String(body.title ?? previous.title),
        });
      }
      return { previous };
    },

    onError: (err, _body, context) => {
      // Roll back to exactly what was there, rather than refetching — the server
      // never accepted the change, so the old value is still correct.
      if (context?.previous) {
        queryClient.setQueryData(["grade", gradeId], context.previous);
      }
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },

    onSuccess: () => {
      setEditing(false);
      setCode(null);
      onSaved();
    },
  });

  const retire = useMutation({
    mutationFn: () => api(`/grades/${gradeId}`, { method: "DELETE" }),
    onSuccess: () => {
      setRetiring(false);
      setCode(null);
      onDeleted();
    },
    onError: (err) => {
      setRetiring(false);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  // The trail for this grade. Read-only by construction: an append-only log gets
  // no write controls, only the record of what happened to this mark.
  const history = useQuery({
    queryKey: ["grade-history", gradeId],
    queryFn: () => api<History>(`/grades/${gradeId}/history`),
    enabled: Boolean(grade),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);

    const score = parseLocaleNumber(String(data.get("score") ?? ""), locale);
    const weight = parseLocaleNumber(String(data.get("weight") ?? ""), locale);

    // Reported, not coerced. `Number("88,5")` is NaN and would have been sent as
    // null; stripping the separator would have sent 885.
    if (score === null || weight === null) {
      setCode("VALIDATION_ERROR");
      return;
    }

    save.mutate({
      score,
      weight,
      title: String(data.get("title") ?? ""),
      notes: String(data.get("notes") ?? ""),
    });
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <PanelHeader
        title={grade?.student_name ?? t("stats.loading")}
        subtitle={grade && `${grade.course_id} · ${grade.title}`}
        closeLabel={t("action.close")}
        onClose={onClose}
      />

      {loading && <p className="mt-4 text-sm text-subtle">{t("stats.loading")}</p>}
      {error instanceof ApiError && (
        <p role="alert" className="mt-4 text-sm text-fail">
          {t(`error.${error.code}` as "error.unknown")}
        </p>
      )}
      {code && !editing && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}

      {grade && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field
              label={t("grade.score")}
              value={`${formatNumber(grade.score, locale)} / ${formatNumber(grade.max_grade, locale)}`}
              numeric
            />
            <Field
              label={t("grade.percentage")}
              value={formatPercent(grade.percentage, locale)}
              numeric
            />
            <Field
              label={t("grade.status")}
              value={
                <span className={grade.is_passing ? "text-pass" : "text-fail"}>
                  {grade.is_passing ? t("grade.passing") : t("grade.failing")}
                </span>
              }
            />
            <Field label={t("grade.weight")} value={formatNumber(grade.weight, locale)} numeric />
            <Field label={t("grade.date")} value={formatDate(grade.date, locale)} numeric />
            <Field label={t("course.one")} value={grade.course_name} />
          </dl>

          {grade.notes && <p className="mt-4 text-sm text-muted">{grade.notes}</p>}

          {editable && (
            <div className="mt-6 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setCode(null);
                  setEditing(true);
                }}
                className="btn btn-ghost"
              >
                {t("action.edit")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setCode(null);
                  setRetiring(true);
                }}
                className="btn btn-danger"
              >
                {t("action.retire")}
              </button>
            </div>
          )}

          <details className="mt-6 rounded-lg border border-line bg-bg px-4 py-2">
            <summary className="cursor-pointer py-1 text-sm font-medium text-text outline-none focus-visible:ring-2 focus-visible:ring-brand/40">
              {t("audit.history")}
            </summary>
            {history.isPending && <p className="pb-2 text-sm text-subtle">{t("stats.loading")}</p>}
            {history.error instanceof ApiError && (
              <p role="alert" className="pb-2 text-sm text-fail">
                {t(`error.${history.error.code}` as "error.unknown")}
              </p>
            )}
            {history.isSuccess && history.data.length === 0 && (
              <p className="pb-2 text-sm text-subtle">{t("audit.empty")}</p>
            )}
            {history.isSuccess && history.data.length > 0 && (
              <ul className="pb-2">
                {history.data.map((entry) => (
                  <AuditEntryLine key={entry.id} entry={entry} locale={locale} />
                ))}
              </ul>
            )}
          </details>
        </>
      )}

      {grade && editing && (
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Input name="title" label={t("grade.title")} value={grade.title} />
          <Input
            name="score"
            label={t("grade.score")}
            value={formatNumber(grade.score, locale)}
            inputMode="decimal"
            // Spells out the maximum, so "88,5" is entered against a known scale
            // rather than guessed at.
            hint={`${t("grade.max")}: ${formatNumber(grade.max_grade, locale)}`}
          />
          <Input
            name="weight"
            label={t("grade.weight")}
            value={formatNumber(grade.weight, locale)}
            inputMode="decimal"
          />
          <Input
            name="notes"
            label={t("grade.notes")}
            value={grade.notes}
            required={false}
          />

          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {t(`error.${code}` as "error.unknown")}
            </p>
          )}

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-lg bg-brand px-3 py-1.5 text-sm text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {t("action.save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setCode(null);
              }}
              className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
            >
              {t("action.cancel")}
            </button>
          </div>
        </form>
      )}

      <Confirm
        open={retiring}
        title={t("grade.retireTitle")}
        description={t("grade.retireDescription")}
        confirmLabel={t("action.retire")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => retire.mutateAsync().then(() => undefined).catch(() => undefined)}
        onCancel={() => setRetiring(false)}
      />
    </div>
  );
}
