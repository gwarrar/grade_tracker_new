/**
 * One student's report — the printable one.
 *
 * Guarded on `viewStudentReport`, which is the rule that lets a student open their
 * own record and nobody else's while staff open anyone's. The API enforces the same
 * thing, so this only avoids rendering a page whose every request would 404.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { StudentReportView } from "./student-report-view";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; studentId: string }>;
}): Promise<Metadata> {
  const { locale, studentId } = await params;
  const t = await getTranslations({ locale });
  return { title: `${t("student.report")} · ${studentId}` };
}

export default async function Page({
  params,
}: {
  params: Promise<{ locale: string; studentId: string }>;
}) {
  const { locale, studentId } = await params;
  setRequestLocale(locale);

  await requireSession(locale, (me) => can.viewStudentReport(me, studentId));

  return <StudentReportView studentId={studentId} locale={locale} />;
}
