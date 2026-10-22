/**
 * ChangeHistory's states against an msw backend: loading in the list's own
 * layout, failures through describeError (403, 404, 500, offline), the empty
 * text, and the entries' accessible wording.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { demoHistory, detailBackend, DEMO_EVENT_ID } from "../testapp-fixtures";
import { ChangeHistory, type ChangeHistoryProps } from "./ChangeHistory";

function mount(props: Partial<ChangeHistoryProps> = {}) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      <ChangeHistory resource="events" id={DEMO_EVENT_ID} {...props} />
    </KarniProvider>,
  );
}

function setOnline(online: boolean): void {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => online });
  window.dispatchEvent(new Event(online ? "online" : "offline"));
}

afterEach(() => {
  act(() => setOnline(true));
});

describe("ChangeHistory states", () => {
  it("holds entry placeholders from the start and draws them once loading is slow", async () => {
    server.use(...detailBackend({ history: "pending" }));
    mount({ pageSize: 2 });
    const section = screen.getByRole("region", { name: "Change history" });
    expect(section).toHaveAttribute("aria-busy", "true");
    const placeholder = screen.getByTestId("change-history-loading");
    expect(placeholder.children).toHaveLength(2);
    expect(placeholder).toHaveAttribute("aria-hidden", "true");
    expect(placeholder).toHaveClass("invisible");
    await waitFor(() => expect(screen.getByText("Loading the history…")).toBeInTheDocument(), {
      timeout: 2000,
    });
    expect(placeholder).not.toHaveClass("invisible");
  });

  it("lists the entries, newest first, with the shared empty value", async () => {
    server.use(...detailBackend());
    mount();
    const entries = await screen.findAllByRole("listitem");
    expect(entries).toHaveLength(3);
    const [newest, , oldest] = entries;
    if (newest === undefined || oldest === undefined) throw new Error("expected three entries");
    expect(within(newest).getByText("grace@example.com")).toBeInTheDocument();
    // description "Bring a laptop." → "": the after value is the dash read as "empty".
    expect(within(newest).getByText("empty")).toHaveClass("sr-only");
    expect(within(newest).getAllByText("changed to")).toHaveLength(2);
    expect(within(oldest).getByText("no user recorded")).toBeInTheDocument();
    expect(screen.getAllByText("redacted")).toHaveLength(2);
  });

  it("shows the empty text when nothing was recorded", async () => {
    server.use(
      ...detailBackend({ historyPage: { count: 0, next: null, previous: null, results: [] } }),
    );
    mount({ empty: "Nothing has changed yet." });
    expect(await screen.findByText("Nothing has changed yet.")).toBeInTheDocument();
  });

  it("says a 403 in plain words, without a retry", async () => {
    server.use(...detailBackend({ history: { status: 403, body: {} } }));
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You can't view the history of this event");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("explains a model that keeps no history (404)", async () => {
    server.use(
      ...detailBackend({
        history: {
          status: 404,
          body: {
            detail: "No history is kept for Event: opt in with class Karni: audit = True.",
          },
        },
      }),
    );
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't find the history of this event");
    expect(alert).toHaveTextContent("No history is kept for Event");
  });

  it("retries after a server error", async () => {
    let calls = 0;
    server.use(...detailBackend());
    server.use(
      http.get("*/api/events/:id/history/", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({}, { status: 500 })
          : HttpResponse.json(demoHistory);
      }),
    );
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findAllByRole("listitem")).toHaveLength(3);
  });

  it("says it is offline, and loads once back online", async () => {
    server.use(...detailBackend());
    act(() => setOnline(false));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("You're offline");
    act(() => setOnline(true));
    expect(await screen.findAllByRole("listitem")).toHaveLength(3);
  });
});
