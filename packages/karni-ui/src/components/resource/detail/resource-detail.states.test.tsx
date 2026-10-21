/**
 * ResourceDetail's states against an msw backend serving the generated
 * testapp schema (tests/fixtures/schema.testapp.json): loading in the
 * record's own layout, per-role fields, the shared empty value, 404 / 403 /
 * 500 / offline, and the edit and delete actions.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Button } from "../../primitives/button";
import {
  demoEvent,
  detailBackend,
  DEMO_EVENT_ID,
  eventHiding,
  openApiHidingEventFields,
  SCOPED_NOT_FOUND,
  testappOpenApi,
} from "../testapp-fixtures";
import { ResourceDetail, type ResourceDetailProps } from "./ResourceDetail";

const BASE = "http://karni.test/api";

/** The testapp Event's domain labels, in the snapshot's (alphabetical) order. */
const DOMAIN_LABELS = [
  "Capacity",
  "Description",
  "Is public",
  "Organizer",
  "Starts at",
  "Status",
  "Tags",
  "Title",
  "Venue",
];

function mount(props: Partial<ResourceDetailProps> = {}) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      <ResourceDetail resource="events" id={DEMO_EVENT_ID} expand={["venue"]} {...props} />
    </KarniProvider>,
  );
  return { queryClient };
}

function terms(): string[] {
  return screen.getAllByRole("term").map((term) => term.textContent ?? "");
}

function setOnline(online: boolean): void {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => online });
  window.dispatchEvent(new Event(online ? "online" : "offline"));
}

afterEach(() => {
  act(() => setOnline(true));
});

describe("ResourceDetail loading", () => {
  it("holds the record's layout from the start and draws it once loading is slow", async () => {
    server.use(...detailBackend({ event: "pending" }));
    mount({ title: "Event", back: <Button variant="outline">Back to events</Button> });

    // The static header is real content: it is there before the record.
    expect(screen.getByRole("heading", { name: "Event" })).toBeInTheDocument();
    const status = screen.getByRole("status", { name: "Loading details" });
    expect(status).toHaveTextContent("");

    // Held from the start, drawn only once slow: a fast load never flashes it.
    expect(screen.getByTestId("resource-detail-skeleton")).toHaveClass("invisible");
    // Once the schema is in, the placeholder has one row per field it will show.
    await waitFor(() =>
      expect(screen.getByTestId("resource-detail-skeleton").querySelectorAll(".grid")).toHaveLength(
        9 + 5,
      ),
    );
    await waitFor(() => expect(status).toHaveTextContent("Loading this event…"), {
      timeout: 2000,
    });
    expect(screen.getByTestId("resource-detail-skeleton")).not.toHaveClass("invisible");
  });

  it("stands in for a title and actions that need the record, then fills them", async () => {
    server.use(...detailBackend({ event: { delayMs: 50 } }));
    mount({
      title: (item) => String(item["title"]),
      onEdit: () => undefined,
    });
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "React workshop" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });
});

describe("ResourceDetail fields", () => {
  it("shows every readable field; an empty value is a dash read as 'empty'", async () => {
    server.use(...detailBackend());
    mount();
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    const [domain] = screen.getAllByRole("definition").map((value) => value.closest("dl"));
    expect(domain).not.toBeNull();
    expect(terms().slice(0, DOMAIN_LABELS.length)).toEqual(DOMAIN_LABELS);
    expect(screen.getByText("Riverside Pavilion")).toBeInTheDocument(); // expanded relation

    // description "", organizer null, tags [] and updated_by null: the same dash, read as "empty".
    const empties = screen.getAllByText("empty");
    expect(empties).toHaveLength(4);
    for (const word of empties) {
      expect(word).toHaveClass("sr-only");
      expect(word.previousElementSibling).toHaveAttribute("aria-hidden", "true");
      expect(word.previousElementSibling).toHaveTextContent("–");
    }
  });

  it("leaves out a field the role may not read: no row, no dash, no hint (per-role schema)", async () => {
    const hidden = ["capacity", "description"];
    server.use(
      ...detailBackend({
        openApi: openApiHidingEventFields(hidden),
        record: eventHiding(hidden),
      }),
    );
    mount();
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    expect(terms()).not.toContain("Capacity");
    expect(terms()).not.toContain("Description");
    expect(terms().slice(0, 7)).toEqual(
      DOMAIN_LABELS.filter((label) => !["Capacity", "Description"].includes(label)),
    );
    // Only the visible empty fields read "empty" (organizer, tags, updated_by).
    expect(screen.getAllByText("empty")).toHaveLength(3);
    expect(screen.queryByText(/hidden|restricted|permission/i)).toBeNull();
  });

  it("leaves the row out too when a shared schema lists the field but the payload omits it", async () => {
    server.use(...detailBackend({ record: eventHiding(["capacity"]) }));
    mount();
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    expect(terms()).not.toContain("Capacity");
    expect(screen.getAllByText("empty")).toHaveLength(4);
  });
});

describe("ResourceDetail failures", () => {
  it("words a 404 without implying the record exists, with the way back and no retry", async () => {
    server.use(...detailBackend({ event: SCOPED_NOT_FOUND }));
    mount({ back: <Button variant="outline">Back to events</Button> });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't find this event");
    expect(alert).toHaveTextContent("may have been deleted or not shared with you");
    // Neither the access declaration nor "you can't view it" (which would confirm it exists).
    expect(alert).not.toHaveTextContent(/EventViewSet|access|can't view|404/);
    expect(within(alert).getByRole("button", { name: "Back to events" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("says a 403 in plain words, without a retry", async () => {
    server.use(...detailBackend({ event: { status: 403, body: {} } }));
    mount({ resourceLabel: "workshop" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You can't view this workshop");
    expect(alert).not.toHaveTextContent("403");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("retries the record after a server error", async () => {
    let calls = 0;
    server.use(...detailBackend());
    server.use(
      http.get("*/api/events/:id/", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(demoEvent);
      }),
    );
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).not.toHaveTextContent("boom"); // a 5xx body is never shown
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("retries the schema when the schema is what failed", async () => {
    let schemaCalls = 0;
    server.use(...detailBackend());
    server.use(
      http.get("*/api/schema/", () => {
        schemaCalls += 1;
        return schemaCalls === 1
          ? HttpResponse.json({}, { status: 503 })
          : HttpResponse.json(testappOpenApi);
      }),
    );
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    expect(schemaCalls).toBe(2);
  });

  it("says when the server cannot be reached, and tries again when the connection returns", async () => {
    let calls = 0;
    server.use(...detailBackend());
    server.use(
      http.get("*/api/events/:id/", () => {
        calls += 1;
        return calls === 1 ? HttpResponse.error() : HttpResponse.json(demoEvent);
      }),
    );
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the server");
    act(() => setOnline(false));
    act(() => setOnline(true));
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
  });

  it("says it is offline, and loads by itself once back online", async () => {
    server.use(...detailBackend());
    act(() => setOnline(false));
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You're offline");
    act(() => setOnline(true));
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
  });
});

describe("ResourceDetail actions", () => {
  it("shows Edit and Delete only when the role may use them", async () => {
    server.use(...detailBackend());
    const onEdit = vi.fn();
    mount({
      onEdit,
      canEdit: (item) => item["status"] === "published",
      enableDelete: true,
      canDelete: false,
    });
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: DEMO_EVENT_ID }));
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("hides Edit when the predicate refuses this record", async () => {
    server.use(...detailBackend());
    mount({ onEdit: () => undefined, canEdit: () => false, title: "Event" });
    expect(await screen.findByText("React workshop")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("deletes only after confirmation, then says so and takes the focus", async () => {
    let deletes = 0;
    server.use(...detailBackend());
    server.use(
      http.delete("*/api/events/:id/", () => {
        deletes += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    mount({ enableDelete: true, onDeleted, back: <Button>Back to events</Button> });

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    let dialog = screen.getByRole("dialog", { name: "Delete this event?" });
    expect(dialog).toHaveTextContent("React workshop will be deleted. This can't be undone.");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(deletes).toBe(0);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("dialog", { name: "Delete this event?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(demoEvent));
    expect(deletes).toBe(1);
    const status = await screen.findByText("The event was deleted");
    expect(status.closest("[role=status]")).toHaveFocus();
    // The record's later 404 (it is gone) is not an error.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports a refused delete inside the dialog and moves focus to it", async () => {
    server.use(...detailBackend({ remove: { status: 403, body: {} } }));
    const user = userEvent.setup();
    mount({ enableDelete: true });
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("You can't delete this event");
    expect(alert).not.toHaveTextContent("403");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(screen.getByText("React workshop", { selector: "dd" })).toBeInTheDocument();
  });

  it("works from the keyboard: open with Enter, close with Escape, focus returns", async () => {
    server.use(...detailBackend());
    const user = userEvent.setup();
    mount({ enableDelete: true, onEdit: () => undefined });
    await screen.findByRole("button", { name: "Delete" });
    await user.tab(); // Edit
    await user.tab(); // Delete
    const trigger = screen.getByRole("button", { name: "Delete" });
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe("ResourceDetail slots", () => {
  it("renders a project's NotFound and EmptyValue in place of Karni's", async () => {
    server.use(...detailBackend({ event: { status: 404, body: { detail: "Not found." } } }));
    mount({
      slots: {
        NotFound: ({ resourceLabel }) => <p role="alert">No {resourceLabel} here</p>,
      },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("No event here");
  });

  it("passes each empty field to the EmptyValue slot", async () => {
    server.use(...detailBackend());
    mount({ slots: { EmptyValue: ({ field }) => <i>no {field.name}</i> } });
    expect(await screen.findByText("no organizer")).toBeInTheDocument();
    expect(screen.getByText("no tags")).toBeInTheDocument();
  });
});
