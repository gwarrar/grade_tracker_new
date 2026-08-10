/**
 * @vitest-environment jsdom
 *
 * The first component test in the project.
 *
 * `CredentialsCard` is the subject because it is the one screen whose failure is
 * unrecoverable: it shows generated passwords that are stored hashed and returned
 * exactly once, so a card that renders the wrong row, drops one, or dismisses
 * itself destroys credentials nobody can get back.
 *
 * Everything asserted here is invisible to a type checker and to the 150-odd pure
 * function tests: what is on screen, what a click does, what the clipboard receives.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { CredentialsCard, type Credential } from "@/components/app/credentials";
import messages from "@/messages/en.json";

const ROWS: Credential[] = [
  { email: "nadia@school.test", password: "aB3-xY9_pQ", name: "Nadia Haddad" },
  { email: "omar@school.test", password: "kL7-mN2_rS", name: "Omar Nasri" },
];

function show(rows: Credential[], onDismiss = () => {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <CredentialsCard title="Sign-in details" rows={rows} onDismiss={onDismiss} />
    </NextIntlClientProvider>,
  );
}

describe("CredentialsCard", () => {
  it("shows every password it was given", () => {
    show(ROWS);

    for (const row of ROWS) {
      expect(screen.getByText(row.password)).toBeInTheDocument();
    }
  });

  it("renders nothing at all when there is nothing to show", () => {
    // Not an empty card with a heading: the import wizard renders this
    // unconditionally after a commit, and a course import creates no accounts.
    const { container } = show([]);

    expect(container).toBeEmptyDOMElement();
  });

  it("announces itself, because it cannot be recovered once dismissed", () => {
    show(ROWS);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("copies a single password verbatim", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    show([ROWS[0]]);
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));

    // The password alone, with no label or punctuation: whatever this writes is
    // pasted straight into a sign-in field.
    expect(writeText).toHaveBeenCalledWith("aB3-xY9_pQ");
  });

  it("copies every row as CSV when there is more than one", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    show(ROWS);
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));

    const written = writeText.mock.calls[0][0] as string;
    expect(written).toContain("aB3-xY9_pQ");
    expect(written).toContain("kL7-mN2_rS");
  });

  it("offers a file only when copying by hand would be unreasonable", () => {
    const { rerender } = show([ROWS[0]]);
    expect(screen.queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();

    rerender(
      <NextIntlClientProvider locale="en" messages={messages}>
        <CredentialsCard title="Sign-in details" rows={ROWS} onDismiss={() => {}} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("button", { name: /Download/ })).toBeInTheDocument();
  });

  it("dismisses only when asked", async () => {
    const onDismiss = vi.fn();
    show(ROWS, onDismiss);

    expect(onDismiss).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("says that the passwords will not be shown again", () => {
    // The sentence is the whole reason the card is loud. Losing it in a refactor
    // would be silent, and the consequence is somebody closing the tab.
    show(ROWS);

    expect(screen.getByText(/not shown again/i)).toBeInTheDocument();
  });
});
