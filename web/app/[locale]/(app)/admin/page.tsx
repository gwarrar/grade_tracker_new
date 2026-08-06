/**
 * The Admin tab has no page of its own — it opens the first section.
 *
 * Accounts, because every role that reaches /admin can see it; branding and the AI
 * providers are superadmin-only and would redirect an ordinary admin straight back
 * out. The target guards itself, so no check is needed here.
 */

import { redirect } from "next/navigation";

export default async function AdminPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect(`/${locale}/admin/users`);
}
