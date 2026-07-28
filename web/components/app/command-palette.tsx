"use client";

/**
 * The ⌘K command palette.
 *
 * Two tiers, deliberately in this order:
 *
 * 1. **Navigation**, matched locally against a fixed list. Instant, works offline,
 *    and covers the majority of openings — most people press ⌘K to go somewhere.
 * 2. **Records**, fetched from the API once the query is long enough to be worth a
 *    request. Server-side, because the client has at most one page of rows cached
 *    and "search" that only finds the visible fifty is worse than no search.
 *
 * cmdk's own filtering is switched off (`shouldFilter={false}`). It would re-filter
 * the server's results against the same string the server already matched on, and
 * a fuzzy mismatch would hide rows the API deliberately returned.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { ConfirmCard } from "@/components/app/assistant";
import { api, ApiError, type Response } from "@/lib/api";
import { atLeast, type Me } from "@/lib/session";
import { useDebounced } from "@/lib/use-selection";

type Students = Response<"/students", "get">;
type Courses = Response<"/courses", "get">;
type Proposal = Response<"/ai/command", "post">;

/** Below this, a query matches too much to be worth a round trip. */
const MIN_QUERY = 2;
const LIMIT = 5;

// Only routes that exist. A nav that lists /reports before /reports is built is a
// link straight to a 404 — worse than the feature being absent, because it reads
// as broken rather than as not-yet-there. Restored as each page lands.
const ROUTES = [
  { href: "/dashboard", key: "dashboard", min: "student" },
  { href: "/students", key: "students", min: "student" },
  { href: "/courses", key: "courses", min: "student" },
  { href: "/grades", key: "grades", min: "student" },
  { href: "/profile", key: "profile", min: "student" },
  { href: "/admin/ai", key: "admin", min: "superadmin" },
] as const;

export function CommandPalette({ me }: { me: Me }) {
  const t = useTranslations();
  const tAssistant = useTranslations("assistant");
  const tError = useTranslations("error");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const query = useDebounced(search.trim());

  // The AI tier, reached only when the local and record tiers found nothing —
  // and only on an explicit choice. Sending every keystroke to a provider would
  // be both expensive and a steady leak of half-typed student names.
  const propose = useMutation({
    mutationFn: (instruction: string) =>
      api<Proposal>("/ai/command", { method: "POST", body: { instruction } }),
    onSuccess: (result) => {
      setProposal(result);
      setCode(null);
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  function reset() {
    setProposal(null);
    setCode(null);
    setSearch("");
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      // metaKey for macOS, ctrlKey elsewhere. Checking only one strands half the
      // users with a shortcut the interface advertises.
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const enabled = open && query.length >= MIN_QUERY;

  const students = useQuery({
    queryKey: ["palette", "students", query],
    queryFn: () => api<Students>("/students", { query: { q: query, size: LIMIT } }),
    enabled,
  });

  const courses = useQuery({
    queryKey: ["palette", "courses", query],
    queryFn: () => api<Courses>("/courses", { query: { q: query, size: LIMIT } }),
    enabled,
  });

  function go(href: string) {
    setOpen(false);
    reset();
    router.push(href);
  }

  const routes = ROUTES.filter((route) => atLeast(me.role, route.min));
  const lower = query.toLowerCase();
  const matchedRoutes = query
    ? routes.filter((route) => t(`nav.${route.key}`).toLowerCase().includes(lower))
    : routes;

  const studentRows = students.data?.items ?? [];
  const courseRows = courses.data?.items ?? [];
  const empty =
    matchedRoutes.length === 0 && studentRows.length === 0 && courseRows.length === 0;

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label={t("action.search")}
      shouldFilter={false}
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-2xl">
        {proposal ? (
          <ConfirmCard
            proposal={proposal}
            onDone={() => {
              setOpen(false);
              reset();
            }}
            onCancel={reset}
          />
        ) : (
        <>
        <Command.Input
          value={search}
          onValueChange={setSearch}
          placeholder={t("action.search")}
          className="w-full border-b border-line bg-transparent px-4 py-3 text-text outline-none placeholder:text-subtle"
        />

        <Command.List className="max-h-80 overflow-y-auto p-2">
          {empty && (
            <Command.Empty className="px-3 py-8 text-center text-sm text-subtle">
              {t("stats.noData")}
            </Command.Empty>
          )}

          {matchedRoutes.length > 0 && (
            <Command.Group
              heading={t("nav.dashboard")}
              className="px-1 text-xs uppercase tracking-wide text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {matchedRoutes.map((route) => (
                <Item key={route.href} onSelect={() => go(route.href)}>
                  {t(`nav.${route.key}`)}
                </Item>
              ))}
            </Command.Group>
          )}

          {studentRows.length > 0 && (
            <Command.Group
              heading={t("student.other")}
              className="px-1 text-xs uppercase tracking-wide text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {studentRows.map((student) => (
                <Item
                  key={student.student_id}
                  // The id is part of the value so two students with the same name
                  // remain distinct items rather than collapsing into one.
                  value={`student-${student.student_id}`}
                  onSelect={() => go(`/students?id=${student.student_id}`)}
                  trailing={student.student_id}
                >
                  {student.first_name} {student.last_name}
                </Item>
              ))}
            </Command.Group>
          )}

          {courseRows.length > 0 && (
            <Command.Group
              heading={t("course.other")}
              className="px-1 text-xs uppercase tracking-wide text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {courseRows.map((course) => (
                <Item
                  key={course.course_id}
                  value={`course-${course.course_id}`}
                  onSelect={() => go(`/courses?id=${course.course_id}`)}
                  trailing={course.course_id}
                >
                  {course.name}
                </Item>
              ))}
            </Command.Group>
          )}
          {/* Offered last and always, not only when nothing matched: a question
              like "who is failing" legitimately also matches a nav entry, and
              hiding the assistant behind an empty result would make it
              unreachable for exactly those queries. */}
          {query.length >= MIN_QUERY && (
            <Command.Group
              heading={tAssistant("title")}
              className="px-1 text-xs uppercase tracking-wide text-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              <Item
                value="__ask_ai"
                onSelect={() => propose.mutate(query)}
                trailing={propose.isPending ? tAssistant("thinking") : undefined}
              >
                {tAssistant("ask")}: {query}
              </Item>
            </Command.Group>
          )}

          {code && (
            <p role="alert" className="mx-2 mt-2 rounded-lg bg-fail-bg px-3 py-2 text-xs text-fail">
              {tError(code as "unknown")}
            </p>
          )}
        </Command.List>
        </>
        )}
      </div>
    </Command.Dialog>
  );
}

function Item({
  children,
  value,
  trailing,
  onSelect,
}: {
  children: React.ReactNode;
  value?: string;
  trailing?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-sm text-text data-[selected=true]:bg-bg-subtle"
    >
      <span className="min-w-0 truncate normal-case tracking-normal">{children}</span>
      {trailing && <span className="numeric shrink-0 text-xs text-subtle">{trailing}</span>}
    </Command.Item>
  );
}
