"use client";

/**
 * Keeps an account whose password was handed to it on the password form.
 *
 * A generated password is known to whoever generated it, so until it is replaced
 * the account has two owners. Suggesting the change would leave most of them
 * unchanged forever; this insists.
 *
 * A redirect rather than a modal: the profile page already holds the form, the
 * validation and the error codes, and a second copy inside a dialog is a second
 * one to keep correct. Mounted in the application layout, so it fires again on
 * every navigation — leaving the page is what it exists to prevent.
 *
 * Not the enforcement. The API refuses nothing on this basis; this is a nudge
 * with a locked door, and a determined user with a REST client is outside its
 * remit by design — the account is theirs.
 */

import { useEffect } from "react";

import { usePathname, useRouter } from "@/i18n/navigation";
import type { Me } from "@/lib/session";

const FORM = "/profile";

export function PasswordGate({ me }: { me: Me }) {
  const pathname = usePathname();
  const router = useRouter();
  const stranded = me.must_change_password && pathname !== FORM;

  useEffect(() => {
    if (stranded) router.replace(FORM);
  }, [stranded, router]);

  return null;
}
