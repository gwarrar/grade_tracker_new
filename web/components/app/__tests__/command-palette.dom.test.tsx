/**
 * @vitest-environment jsdom
 *
 * The keydown listener, and the bug a type checker cannot see.
 *
 * `KeyboardEvent.key` is typed `string`, so `event.key.toLowerCase()` compiles
 * cleanly and every gate passed. At runtime the property is genuinely absent on
 * some events — a password manager filling a field and IME composition both
 * dispatch keydown without one — and the listener is on `document`, so it threw on
 * pages that have nothing to do with the palette. It reached a user before anything
 * here noticed.
 *
 * That is the shape of failure this whole test environment was added for: correct
 * types, passing lint, broken interface.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/app/command-palette";
import type { Me } from "@/lib/session";
import messages from "@/messages/en.json";

// The palette navigates on selection; nothing here selects, so a stub is enough to
// keep the module from reaching Next's router outside a request.
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/dashboard",
  Link: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const ME: Me = {
  user_id: 1,
  email: "teacher@school.test",
  full_name: "Thomas Weber",
  role: "teacher",
  student_id: null,
  locale: "en",
  theme: "system",
  must_change_password: false,
};

function mount() {
  // No retries and no cache: a failed query here should surface, not be swallowed
  // behind three silent attempts.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <CommandPalette me={ME} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

/** Dispatch a real keydown, optionally omitting `key` the way a real one can. */
function press(init: KeyboardEventInit & { omitKey?: boolean }) {
  const { omitKey, ...rest } = init;
  const event = new KeyboardEvent("keydown", { bubbles: true, ...rest });
  if (omitKey) {
    Object.defineProperty(event, "key", { value: undefined });
  }
  document.dispatchEvent(event);
}

/**
 * Dispatch a keydown and return anything the listener threw.
 *
 * `expect(() => press(...)).not.toThrow()` cannot work here and passes either way:
 * `dispatchEvent` catches whatever a listener throws and re-reports it as an
 * uncaught error on the window, so the call itself always returns normally. Written
 * the obvious way, this test went green against the very bug it was added for.
 */
function pressCapturingErrors(init: KeyboardEventInit & { omitKey?: boolean }): unknown[] {
  const thrown: unknown[] = [];
  const record = (event: ErrorEvent) => {
    thrown.push(event.error ?? event.message);
    event.preventDefault();
  };

  window.addEventListener("error", record);
  try {
    press(init);
  } finally {
    window.removeEventListener("error", record);
  }
  return thrown;
}

describe("CommandPalette keyboard shortcut", () => {
  it("survives a keydown that carries no key", () => {
    mount();

    // The regression. Before the optional chain this threw, and because the
    // listener is document-level it took down pages that never open the palette.
    expect(pressCapturingErrors({ omitKey: true, ctrlKey: true })).toEqual([]);
  });

  it("survives a plain keydown with no modifier", () => {
    mount();

    expect(pressCapturingErrors({ key: "a" })).toEqual([]);
  });

  it("opens on ctrl+k", async () => {
    mount();
    expect(screen.queryByPlaceholderText("Search")).not.toBeInTheDocument();

    press({ key: "k", ctrlKey: true });

    expect(await screen.findByPlaceholderText("Search")).toBeInTheDocument();
  });

  it("opens on meta+k, so macOS is not stranded", async () => {
    // Checking only one modifier leaves half the users with a shortcut the
    // interface advertises and does not honour.
    mount();

    press({ key: "k", metaKey: true });

    expect(await screen.findByPlaceholderText("Search")).toBeInTheDocument();
  });

  it("ignores k without a modifier", () => {
    mount();

    press({ key: "k" });

    expect(screen.queryByPlaceholderText("Search")).not.toBeInTheDocument();
  });

  it("accepts an uppercase K", async () => {
    // Caps lock, or shift held from a previous chord. Awaited like the two above:
    // opening is a state update, so a synchronous query runs before React has
    // rendered and reports "closed" for a palette that is about to open.
    mount();

    press({ key: "K", ctrlKey: true });

    expect(await screen.findByPlaceholderText("Search")).toBeInTheDocument();
  });
});
