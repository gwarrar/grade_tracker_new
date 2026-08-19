/**
 * @vitest-environment jsdom
 *
 * The account picker must render the student's current link before the account
 * list arrives.
 *
 * `Select` passes its `value` through as `defaultValue`, so the browser resolves
 * the selection once, at mount. The accounts query is `enabled: editing`, which
 * means it starts on the same render the select mounts — so the first paint has
 * exactly one option, "no account", and that is what gets selected. Nothing
 * corrects it when the options arrive, because React does not re-apply
 * `defaultValue`. Saving then sent `user_id: null` and unlinked an account the
 * user never touched.
 *
 * It looked intermittent because the second edit in a page load found the query
 * cached and rendered the real option in time.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { StudentDetail } from "@/app/[locale]/(app)/students/students-view";
import messages from "@/messages/en.json";
import type { Me } from "@/lib/session";

// Never resolves: the accounts request is still in flight while the form is on
// screen, which is the state the defect lived in.
vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: vi.fn(() => new Promise(() => {})) };
});

// next-intl's client navigation reaches for `next/navigation`, which does not
// resolve under vitest. The link is not what this test is about.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const ME = { id: 1, email: "admin@test", role: "admin", full_name: "Admin" } as unknown as Me;

const STUDENT = {
  student_id: "S001",
  first_name: "Anna",
  last_name: "Schmidt",
  email: "anna@test.local",
  user_id: 7,
  is_active: true,
  phone: null,
  date_of_birth: null,
  cohort: null,
  enrolled_count: 0,
  grade_count: 0,
} as never;

function show() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <StudentDetail
          student={STUDENT}
          loading={false}
          error={null}
          editable
          me={ME}
          courses={[]}
          coursesReady
          coursesLoading={false}
          coursesError={null}
          locale="en"
          onClose={() => {}}
          onSaved={() => {}}
          onDeleted={() => {}}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("the student account picker", () => {
  it("keeps the existing link selected while the account list is still loading", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByRole("button", { name: /edit/i }));

    const select = screen.getByLabelText(/account/i) as HTMLSelectElement;
    expect(select.value).toBe("7");
  });

  it("submits the unchanged link rather than clearing it", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByRole("button", { name: /edit/i }));

    const select = screen.getByLabelText(/account/i) as HTMLSelectElement;
    const form = select.closest("form");
    expect(form).not.toBeNull();
    // What the submit handler reads. `""` here is the unlink.
    expect(new FormData(form as HTMLFormElement).get("user_id")).toBe("7");
  });
});
