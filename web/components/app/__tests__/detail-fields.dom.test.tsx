/**
 * @vitest-environment jsdom
 *
 * `FieldHelp` exists for the person who does not already know what Weight means,
 * which makes two of its properties load-bearing rather than decorative — and both
 * are invisible to the type checker.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { FieldHelp } from "@/components/app/detail-fields";
import messages from "@/messages/en.json";

const HELP = "A final worth 3 counts three times a quiz worth 1.";

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <FieldHelp help={HELP} />
    </NextIntlClientProvider>,
  );
}

describe("FieldHelp", () => {
  it("is reachable by keyboard, not only by hover", async () => {
    const user = userEvent.setup();
    show();

    await user.tab();

    expect(screen.getByRole("button")).toHaveFocus();
  });

  it("names the control and describes it with the explanation", () => {
    show();

    // The button is called "Help"; the explanation is its *description*. Putting
    // the explanation in the name instead would read the whole sentence back as
    // the button's title and leave it with no description at all.
    const trigger = screen.getByRole("button", { name: messages.action.help });

    expect(trigger).toHaveAccessibleDescription(HELP);
  });

  it("positions the tip against the viewport, not its scrolling ancestors", async () => {
    const user = userEvent.setup();
    show();

    await user.tab();

    // Every caller sits inside a <dialog>, which the UA stylesheet gives
    // `overflow: auto`; an absolutely positioned tip is clipped by it. Only the
    // wiring is checked here — jsdom zeroes every getBoundingClientRect, so
    // whether the tip actually clears the dialog edge is a browser question.
    const tip = screen.getByRole("tooltip", { hidden: true });

    expect(tip.className.split(/\s+/)).toContain("fixed");
    expect(tip.style.top).not.toBe("");
    expect(tip.style.left).not.toBe("");
  });

  it("hides the tip by opacity, never by display", () => {
    show();

    // The regression this guards: hiding the tip with `display: none` drops it out
    // of the accessibility tree, `aria-describedby` resolves to nothing, and the
    // description silently disappears — while looking identical on screen.
    //
    // Asserted against the class list rather than the computed style, which reads
    // as a peculiar thing to do until you check: jsdom applies no Tailwind, so
    // `getComputedStyle(tip).display` is never "none" whatever the class says, and
    // `toHaveAccessibleDescription` above stays green either way. Both are false
    // positives — probed and confirmed. The class is what actually decides this.
    const tip = screen.getByRole("tooltip", { hidden: true });

    expect(tip.className).toContain("opacity-0");
    expect(tip.className.split(/\s+/)).not.toContain("hidden");
  });
});
