import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Confirm } from "./confirm";
import { Modal } from "./modal";

describe("Modal", () => {
  it("labels its native dialog with the visible title", () => {
    // Removing either association makes the dialog unnamed to assistive technology.
    const html = renderToStaticMarkup(
      <Modal open title="Edit student" onClose={() => {}}>
        <p>Form contents</p>
      </Modal>,
    );
    const titleId = html.match(/<h2 id="([^"]+)"/)?.[1];

    expect(titleId).toBeTruthy();
    expect(html).toContain(`aria-labelledby="${titleId}"`);
  });
});

describe("Confirm", () => {
  it("puts autofocus on Cancel and marks its confirmation destructive", () => {
    // Moving autofocus to the destructive action makes an accidental Enter destructive.
    const html = renderToStaticMarkup(
      <Confirm
        open
        title="Archive grade"
        description="This keeps the grade for disputes."
        confirmLabel="Archive"
        cancelLabel="Cancel"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );

    expect(html).toMatch(
      /<button\b(?=[^>]*\bautofocus="")(?=[^>]*\bclass="btn btn-ghost")[^>]*>Cancel<\/button>/,
    );
    expect(html).toMatch(/<button\b(?=[^>]*\bclass="btn btn-danger")[^>]*>Archive<\/button>/);
  });
});
