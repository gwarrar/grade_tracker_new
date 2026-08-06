"use client";

/**
 * Bulk import of students, courses and grades.
 *
 * Three local steps in one component — no wizard library, because the three
 * screens share one bit of state (the file, the mapping, the preview) and a
 * library would only hide that. The API does all the parsing and all the writing;
 * this page builds the request:
 *
 * 1. **File** — pick a kind and a file. `.csv` is parsed in the browser so the
 *    mapping table appears without a round trip; `.xlsx` is handed to the preview
 *    endpoint, which returns the headers the browser cannot read.
 * 2. **Mapping** — every column gets a `<select>`, prefilled by `/ai/import-map`
 *    when it answers. If AI is not configured the table is simply empty — the
 *    import must never depend on it.
 * 3. **Preview** — the dry run's per-row report, then a confirm before the commit.
 *
 * Nothing here is a security boundary: every endpoint enforces its own role and
 * row scope, and the page itself is guarded by `can.importData` on the server.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type DragEvent, type FormEvent } from "react";

import { CredentialsCard } from "@/components/app/credentials";

import { Select } from "@/components/app/detail-fields";
import { Confirm } from "@/components/ui/confirm";
import { api, ApiError, type Response } from "@/lib/api";
import { parseCsv } from "@/lib/csv";
import { formatNumber } from "@/lib/format";

type ImportKind = "students" | "courses" | "grades";
type Preview = Response<"/import/{kind}/preview", "post">;
type Report = Response<"/import/{kind}", "post">;
type ImportMap = Response<"/ai/import-map", "post">;
/** Field name to source column name, the shape the API expects. */
type Mapping = Record<string, string>;

const KINDS: ImportKind[] = ["students", "courses", "grades"];

// The gradebook fields each kind accepts, mirroring the import service. The
// server is the authority; this list only fills the <select> options.
const FIELDS: Record<ImportKind, readonly string[]> = {
  students: [
    "student_id", "first_name", "last_name", "email", "is_active",
    "phone", "date_of_birth", "cohort",
  ],
  courses: [
    "course_id", "name", "max_grade", "passing_grade", "max_students", "term",
    "credits", "description", "room", "schedule", "department", "start_date", "end_date",
  ],
  grades: ["student_id", "course_id", "title", "score", "date", "weight", "notes"],
};

/** field → column ⇒ column → field, for the per-column selects. */
function invert(mapping: Mapping): Mapping {
  const byColumn: Mapping = {};
  for (const [field, column] of Object.entries(mapping)) byColumn[column] = field;
  return byColumn;
}

function confidenceClass(value: string): string {
  if (value === "high") return "badge-pass";
  if (value === "low") return "badge-fail";
  return "badge-warn";
}

export function ImportView({ locale }: { locale: string }) {
  const t = useTranslations("admin.import");
  const tAction = useTranslations("action");
  const tError = useTranslations("error");

  const [step, setStep] = useState<"file" | "map" | "preview" | "done">("file");
  const [kind, setKind] = useState<ImportKind>("students");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [samples, setSamples] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [committed, setCommitted] = useState<Report | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [noHeader, setNoHeader] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [createAccounts, setCreateAccounts] = useState(true);

  const propose = useQuery({
    queryKey: ["import", "map", kind, headers],
    queryFn: () =>
      api<ImportMap>("/ai/import-map", { method: "POST", body: { headers, samples } }),
    enabled: step === "map" && headers.length > 0,
    // A proposal is a one-shot suggestion for this file; refetching it later can
    // only change the user's mapping underneath them.
    staleTime: Infinity,
  });

  const previewMutation = useMutation({
    mutationFn: (request: Mapping) => {
      const form = new FormData();
      form.set("file", file as File);
      form.set("mapping", JSON.stringify(request));
      form.set("create_accounts", String(createAccounts));
      return api<Preview>(`/import/${kind}/preview`, { method: "POST", body: form });
    },
    onSuccess: (result) => {
      setPreview(result);
      setStep("preview");
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  const commitMutation = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.set("file", file as File);
      form.set("mapping", JSON.stringify(mapping ?? {}));
      form.set("create_accounts", String(createAccounts));
      return api<Report>(`/import/${kind}`, { method: "POST", body: form });
    },
    onSuccess: (result) => {
      setCommitted(result);
      setConfirmOpen(false);
      setStep("done");
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  async function pick(selected: File) {
    setCode(null);
    setNoHeader(false);
    setFile(selected);
    setMapping(null);
    setPreview(null);
    setCommitted(null);

    if (selected.name.toLowerCase().endsWith(".csv")) {
      try {
        const parsed = parseCsv(await selected.text());
        if (parsed.headers.length === 0) {
          setNoHeader(true);
          return;
        }
        setHeaders(parsed.headers);
        setSamples(parsed.rows.slice(0, 5));
        setStep("map");
      } catch {
        setCode("NETWORK_ERROR");
      }
    } else {
      // .xlsx (and any other server-readable format): the browser cannot parse
      // it, so the preview endpoint inspects it and returns the headers.
      setInspecting(true);
      try {
        const form = new FormData();
        form.set("file", selected);
        const inspected = await api<Preview>(`/import/${kind}/preview`, {
          method: "POST",
          body: form,
        });
        setHeaders(inspected.headers);
        setSamples(inspected.sample_rows);
        setStep("map");
      } catch (error) {
        setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
      } finally {
        setInspecting(false);
      }
    }
  }

  function onMappingSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const byColumn: Mapping = {};
    for (let i = 0; i < headers.length; i++) {
      const field = String(data.get(`column-${i}`) ?? "");
      if (field) byColumn[headers[i]] = field;
    }
    const request: Mapping = {};
    for (const [column, field] of Object.entries(byColumn)) request[field] = column;
    setMapping(request);
    setCode(null);
    previewMutation.mutate(request);
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    setDragging(true);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const selected = event.dataTransfer.files?.[0];
    if (selected) void pick(selected);
  }

  function restart() {
    setStep("file");
    setFile(null);
    setHeaders([]);
    setSamples([]);
    setMapping(null);
    setPreview(null);
    setCommitted(null);
    setCode(null);
    setNoHeader(false);
  }

  // What the mapping selects default to: the user's previous choices when they
  // came back from the preview, otherwise the AI proposal for this file.
  const proposalByColumn = propose.data ? invert(propose.data.column_mapping) : {};
  const initial = mapping ?? proposalByColumn;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("intro")}</p>
      </div>

      {step === "file" && (
        <section className="space-y-6">
          <label className="block max-w-xs">
            <span className="block text-sm text-muted">{t("kind")}</span>
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as ImportKind)}
              className="field-input"
            >
              {KINDS.map((option) => (
                <option key={option} value={option}>
                  {t(`kindValue.${option}`)}
                </option>
              ))}
            </select>
          </label>

          {/* Students only — the other two kinds have nobody to sign in. On by
              default: a cohort imported without accounts is a cohort that cannot
              see its own grades. */}
          {kind === "students" && (
            <label className="flex max-w-lg items-start gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={createAccounts}
                onChange={(event) => setCreateAccounts(event.target.checked)}
                className="mt-0.5 accent-[var(--brand-primary)]"
              />
              <span>
                {t("createAccounts")}
                <span className="block text-xs text-subtle">{t("createAccountsHint")}</span>
              </span>
            </label>
          )}

          <div
            onDragOver={onDragOver}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`rounded-xl border-2 border-dashed px-8 py-10 text-center transition-colors ${
              dragging ? "border-brand bg-bg-subtle" : "border-line"
            }`}
          >
            <p className="text-sm font-medium text-text">{t("drop")}</p>
            <p className="mt-1 text-xs text-subtle">{t("dropHint")}</p>
            <label className="btn mt-5 cursor-pointer">
              {inspecting ? t("inspect") : t("chooseFile")}
              <input
                type="file"
                accept=".csv,.tsv,.xlsx,.xlsm"
                className="sr-only"
                disabled={inspecting}
                onChange={(event) => {
                  const selected = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (selected) void pick(selected);
                }}
              />
            </label>
          </div>

          {noHeader && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {t("noHeader")}
            </p>
          )}
          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {tError(code as "unknown")}
            </p>
          )}
        </section>
      )}

      {step === "map" && (
        <section className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-medium text-text">{t("mapTitle")}</h2>
              <p className="mt-0.5 text-sm text-subtle">{t("mapIntro")}</p>
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => setStep("file")}>
              {t("back")}
            </button>
          </div>

          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {tError(code as "unknown")}
            </p>
          )}

          {propose.isPending && (
            <p className="rounded-xl border border-line bg-surface px-4 py-8 text-center text-sm text-subtle">
              {t("proposing")}
            </p>
          )}

          {propose.isSuccess && propose.data && (
            <div className="rounded-xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-text">{t("proposal")}</p>
                <span className={`badge ${confidenceClass(propose.data.confidence)}`}>
                  {t(`confidence.${propose.data.confidence}` as "confidence.high")}
                </span>
              </div>
              {propose.data.issues.length > 0 && (
                <ul className="mt-2 list-inside list-disc space-y-0.5 text-sm text-muted">
                  {propose.data.issues.map((issue, index) => (
                    <li key={index}>{issue}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {propose.isError && (
            <p
              role="note"
              className="rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-sm text-warn"
            >
              {t("aiUnavailable")}
            </p>
          )}

          {(propose.isSuccess || propose.isError) && (
            <form onSubmit={onMappingSubmit}>
              <div className="overflow-x-auto rounded-xl border border-line bg-surface">
                <table className="data-table">
                  <caption className="sr-only">{t("mapTitle")}</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="w-44">{t("column")}</th>
                      <th scope="col">{t("sample")}</th>
                      <th scope="col" className="w-64">
                        <span className="sr-only">{t("field")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {headers.map((header, index) => (
                      <tr key={index}>
                        <td className="font-medium text-text">{header || "—"}</td>
                        <td className="text-subtle">{samples[0]?.[index] ?? "—"}</td>
                        <td>
                          <Select
                            name={`column-${index}`}
                            label={t("field")}
                            value={initial[header] ?? ""}
                            required={false}
                          >
                            <option value="">{t("unmapped")}</option>
                            {FIELDS[kind].map((field) => (
                              <option key={field} value={field}>
                                {t(`fields.${field}` as "fields.student_id")}
                              </option>
                            ))}
                          </Select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 flex justify-end gap-2">
                <button type="button" className="btn btn-ghost" onClick={() => setStep("file")}>
                  {t("back")}
                </button>
                <button type="submit" className="btn btn-primary" disabled={previewMutation.isPending}>
                  {previewMutation.isPending ? t("previewing") : t("preview")}
                </button>
              </div>
            </form>
          )}
        </section>
      )}

      {step === "preview" && preview && (
        <section className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-medium text-text">{t("previewTitle")}</h2>
              <p className="mt-0.5 text-sm text-subtle">{t("previewIntro")}</p>
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => setStep("map")}>
              {t("back")}
            </button>
          </div>

          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {tError(code as "unknown")}
            </p>
          )}

          <div className="flex flex-wrap gap-4">
            <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-text">
              {t("rowsImported", { count: preview.report.imported })}
            </p>
            <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-text">
              {t("rowsSkipped", { count: preview.report.skipped })}
            </p>
          </div>

          <div className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="data-table">
              <caption className="sr-only">{t("previewTitle")}</caption>
              <thead>
                <tr>
                  <th scope="col" className="w-24">{t("line")}</th>
                  <th scope="col">{t("errorColumn")}</th>
                </tr>
              </thead>
              <tbody>
                {preview.report.errors.map((row) => (
                  <tr key={row.line}>
                    <td className="numeric text-muted">{formatNumber(row.line, locale)}</td>
                    <td>
                      <span className="badge badge-fail">
                        {tError(row.code as "unknown")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {preview.report.errors.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-subtle">{t("noErrors")}</p>
            )}
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              className="btn btn-danger"
              disabled={preview.report.imported === 0 || commitMutation.isPending}
              onClick={() => setConfirmOpen(true)}
            >
              {commitMutation.isPending ? t("committing") : t("commit")}
            </button>
          </div>

          <Confirm
            open={confirmOpen}
            title={t("commitTitle")}
            description={t("commitDescription", { count: preview.report.imported })}
            confirmLabel={t("commit")}
            cancelLabel={tAction("cancel")}
            onConfirm={() =>
              commitMutation.mutateAsync().then(() => undefined).catch(() => undefined)
            }
            onCancel={() => setConfirmOpen(false)}
          />
        </section>
      )}

      {step === "done" && committed && (
        <section className="space-y-6">
          <div role="status" className="rounded-xl border border-pass/40 bg-pass-bg p-5">
            <p className="text-sm font-medium text-pass">{t("committed")}</p>
            <p className="mt-1 text-sm text-pass">
              {t("committedReport", {
                imported: committed.imported,
                skipped: committed.skipped,
              })}
            </p>
          </div>
          {/* Before the restart button, not after: restarting is what somebody
              does the instant they read "imported", and these are gone for good. */}
          <CredentialsCard
            title={t("accountsCreated", { count: (committed.credentials ?? []).length })}
            rows={(committed.credentials ?? []).map((row) => ({
              email: row.email,
              password: row.initial_password,
              name: `${row.full_name} · ${row.student_id}`,
            }))}
            onDismiss={() => setCommitted({ ...committed, credentials: [] })}
          />
          <button type="button" className="btn" onClick={restart}>
            {t("restart")}
          </button>
        </section>
      )}
    </div>
  );
}
