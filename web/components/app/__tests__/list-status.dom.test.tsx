/**
 * @vitest-environment jsdom
 *
 * The distinction this component exists for: a list that failed must not read as a
 * list that is empty.
 */

import { NextIntlClientProvider } from "next-intl";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ListStatus } from "../list-status";
import { ApiError } from "@/lib/api";

const messages = {
  error: {
    FORBIDDEN: "You do not have permission to see this.",
    NETWORK_ERROR: "Could not reach the server.",
    unknown: "Something went wrong.",
  },
};

function show(props: Parameters<typeof ListStatus>[0]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ListStatus {...props} />
    </NextIntlClientProvider>,
  );
}

const idle = { isPending: false, isError: false, error: null } as const;

describe("ListStatus", () => {
  it("says it is loading before anything has arrived", () => {
    show({
      query: { isPending: true, isError: false, error: null },
      isEmpty: true,
      loadingLabel: "Loading…",
      emptyLabel: "No data",
    });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("No data")).not.toBeInTheDocument();
  });

  it("says the list is empty when the request succeeded and returned nothing", () => {
    show({ query: idle, isEmpty: true, loadingLabel: "Loading…", emptyLabel: "No data" });
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports the failure instead of claiming there is no data", () => {
    // The defect this replaces: `rows.length === 0` is also true when the request
    // failed, so all three list screens told the reader their course had no
    // students when the server had actually refused the request.
    show({
      query: { isPending: false, isError: true, error: new ApiError("FORBIDDEN", 403) },
      isEmpty: true,
      loadingLabel: "Loading…",
      emptyLabel: "No data",
    });
    expect(screen.getByRole("alert")).toHaveTextContent("You do not have permission to see this.");
    expect(screen.queryByText("No data")).not.toBeInTheDocument();
  });

  it("names a dropped connection as such", () => {
    show({
      query: { isPending: false, isError: true, error: new TypeError("fetch failed") },
      isEmpty: true,
      loadingLabel: "Loading…",
      emptyLabel: "No data",
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the server.");
  });

  it("renders nothing at all once there are rows", () => {
    const { container } = show({
      query: idle,
      isEmpty: false,
      loadingLabel: "Loading…",
      emptyLabel: "No data",
    });
    expect(container).toBeEmptyDOMElement();
  });
});
