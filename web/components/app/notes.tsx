"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { FormError, Select, Textarea } from "@/components/app/detail-fields";
import { Confirm } from "@/components/ui/confirm";
import { api, ApiError, type Response } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { paths } from "@/lib/api-schema";
import { formatDate } from "@/lib/format";
import { can } from "@/lib/permissions";
import type { Me } from "@/lib/session";

type NoteList = Response<"/students/{student_id}/notes", "get">;
type Note = NoteList[number];
type NoteCreate = paths["/students/{student_id}/notes"]["post"]["requestBody"]["content"]["application/json"];

const VISIBILITIES = ["private", "staff", "shared", "course"] as const;

export function NotesBlock({
  entityType,
  entityId,
  me,
  locale,
}: {
  entityType: "course" | "student";
  entityId: string;
  me: Me;
  locale: string;
}) {
  const t = useTranslations("notes");
  const tAction = useTranslations("action");
  const tStats = useTranslations("stats");
  const tError = useTranslations("error");
  const queryClient = useQueryClient();
  const [code, setCode] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [deleting, setDeleting] = useState<Note | null>(null);

  const notesPath =
    entityType === "student" ? `/students/${entityId}/notes` : `/courses/${entityId}/notes`;
  const writable = entityType === "student" ? can.writeStudentNote(me) : can.writeCourseNote();

  const notes = useQuery({
    queryKey: queryKeys.notes.forEntity(entityType, entityId),
    queryFn: () => api<NoteList>(notesPath),
  });

  const refresh = () => queryClient.invalidateQueries({
      queryKey: queryKeys.notes.forEntity(entityType, entityId),
    });

  const create = useMutation({
    mutationFn: (body: NoteCreate) => api<Note>(notesPath, { method: "POST", body }),
    onSuccess: () => {
      setCode(null);
      setFormKey((key) => key + 1);
      void refresh();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  const remove = useMutation({
    mutationFn: (noteId: number) => api(`/notes/${noteId}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(null);
      setCode(null);
      void refresh();
    },
    onError: (error) => {
      setDeleting(null);
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const visibility = String(data.get("visibility") ?? "");
    setCode(null);
    create.mutate({
      body: String(data.get("body") ?? "").trim(),
      ...(visibility ? { visibility: visibility as NonNullable<NoteCreate["visibility"]> } : {}),
    });
  }

  return (
    <section className="mt-8 border-t border-line pt-6">
      <h3 className="text-sm font-medium text-text">{t("title")}</h3>

      {writable && (
        <form key={formKey} onSubmit={submit} className="mt-4 space-y-4">
          <Textarea name="body" label={t("body")} value="" />
          <div className="flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <Select name="visibility" label={t("visibility")} value="">
                <option value="">{t("visibilityValue.default")}</option>
                {VISIBILITIES.map((visibility) => (
                  <option key={visibility} value={visibility}>
                    {t(`visibilityValue.${visibility}` as "visibilityValue.private")}
                  </option>
                ))}
              </Select>
            </div>
            <button type="submit" className="btn btn-primary" disabled={create.isPending}>
              {t("add")}
            </button>
          </div>
        </form>
      )}

      {notes.isPending && <p className="mt-3 text-sm text-subtle">{tStats("loading")}</p>}
      {notes.error && (
        <FormError>
          {tError(`${notes.error instanceof ApiError ? notes.error.code : "NETWORK_ERROR"}` as "unknown")}
        </FormError>
      )}
      {notes.isSuccess && notes.data.length === 0 && (
        <p className="mt-3 text-sm text-subtle">{tStats("noData")}</p>
      )}
      {notes.isSuccess && notes.data.length > 0 && (
        <ul className="mt-4 space-y-4">
          {notes.data.map((note) => (
            <li key={note.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-text">{note.author_name}</span>
                  <span className="numeric text-xs text-subtle">
                    {formatDate(note.created_at, locale, { dateStyle: "medium", timeStyle: "short" })}
                  </span>
                  <span className="badge">
                    {t(`visibilityValue.${note.visibility}` as "visibilityValue.private")}
                  </span>
                </div>
                {can.deleteNote(me, note) && (
                  <button type="button" className="btn btn-ghost" onClick={() => setDeleting(note)}>
                    {tAction("delete")}
                  </button>
                )}
              </div>
              <p className="mt-2 whitespace-pre-wrap text-muted">{note.body}</p>
            </li>
          ))}
        </ul>
      )}
      {code && <FormError>{tError(code as "unknown")}</FormError>}

      <Confirm
        open={deleting !== null}
        title={t("deleteTitle")}
        description={t("deleteDescription")}
        confirmLabel={tAction("delete")}
        cancelLabel={tAction("cancel")}
        onConfirm={() =>
          deleting ? remove.mutateAsync(deleting.id).then(() => undefined).catch(() => undefined) : undefined
        }
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}
