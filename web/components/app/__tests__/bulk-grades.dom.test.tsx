/**
 * @vitest-environment jsdom
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BulkGrades } from "@/components/app/bulk-grades";
import messages from "@/messages/de.json";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: vi.fn().mockResolvedValue([]) };
});

const COURSES = [
  {
    course_id: "MATH-1",
    name: "Mathematik",
    max_grade: 100,
    assessments: [
      { name: "Zwischenprüfung", weight: 1.5 },
      { name: "Abschlussprüfung", weight: 3 },
    ],
  },
  {
    course_id: "HIST-1",
    name: "Geschichte",
    max_grade: 100,
    assessments: [],
  },
];

function show() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NextIntlClientProvider locale="de" messages={messages}>
        <BulkGrades
          courses={COURSES}
          initialCourseId="MATH-1"
          locale="de"
          onClose={() => {}}
          onSaved={() => {}}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("BulkGrades assessment scheme", () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
    HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
      this.removeAttribute("open");
    });
  });

  it("derives a localized editable weight and resets the assessment when the course changes", async () => {
    const user = userEvent.setup();
    show();

    const assessment = screen.getByLabelText("Leistung");
    expect(assessment).toBeInstanceOf(HTMLSelectElement);

    await user.selectOptions(assessment, "Zwischenprüfung");
    const weight = screen.getByLabelText("Gewichtung");
    expect(weight).toHaveValue("1,5");

    await user.clear(weight);
    await user.type(weight, "2,25");
    expect(weight).toHaveValue("2,25");

    await user.selectOptions(screen.getByLabelText("Kurs"), "HIST-1");
    expect(screen.getByLabelText("Leistung")).toBeInstanceOf(HTMLInputElement);
    expect(screen.getByLabelText("Leistung")).toHaveValue("");

    await user.selectOptions(screen.getByLabelText("Kurs"), "MATH-1");
    expect(screen.getByLabelText("Leistung")).toHaveValue("");
    expect(screen.getByLabelText("Gewichtung")).toHaveValue("1");
  });
});
