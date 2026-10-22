/**
 * ResourceForm end to end against the simulated backend (tests/msw): the
 * real client, schema parsing, validation, mutations and ResourceSelect.
 * Covers the states and behaviours the mocked suite cannot: loading, load
 * failures, permission, validation timing, every server error shape and
 * status, focus, preserved input, the unsaved-changes guard, keyboard submit
 * and accessibility wiring for every field kind.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { openApiFixture } from "../../../../tests/msw/openapi";
import { mswDb, resetMswData, server } from "../../../../tests/msw/server";
import { useUnsavedChangesGuard } from "../../../hooks/useUnsavedChangesGuard";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { ResourceForm, type ResourceFormProps } from "./ResourceForm";

beforeEach(() => {
  resetMswData();
});

function mount(ui: React.ReactElement): void {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

function Form(props: Partial<ResourceFormProps>): React.ReactElement {
  return <ResourceForm resource="events" {...props} />;
}

async function title(): Promise<HTMLElement> {
  return screen.findByRole("textbox", { name: "Title" }, { timeout: 3000 });
}

async function fillRequired(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(await title(), "Spring gala");
  fireEvent.change(screen.getByLabelText(/Starts at/), { target: { value: "2026-05-01T18:30" } });
}

/** Answers every create with `respond` and counts the attempts. */
function onCreate(respond: () => Response | Promise<Response>): { calls: () => number } {
  let calls = 0;
  server.use(
    http.post("*/api/events/", async () => {
      calls += 1;
      return respond();
    }),
  );
  return { calls: () => calls };
}

function liveRegion(form: HTMLElement): HTMLElement {
  const region = within(form)
    .getAllByRole("status")
    .find((element) => element.tagName === "P");
  if (region === undefined) throw new Error("no live region");
  return region;
}

/** The writable fields of the fixture's events, in schema order. */
const WRITABLE = [
  "Title",
  "Description",
  "Starts at",
  "Capacity",
  "Category",
  "Priority",
  "Is public",
  "Organizer",
  "Venue",
  "Tags",
  "Poster",
  "Contact email",
  "Website",
  "Metadata",
  "Internal note",
];

describe("ResourceForm loading", () => {
  it("while the schema loads: a skeleton with the submit row where the real one sits", async () => {
    server.use(
      http.get("*/api/schema/", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    mount(<Form />);
    const skeleton = await screen.findByRole("status", { name: "Loading form" });
    expect(skeleton).toHaveAttribute("aria-busy", "true");
    expect(skeleton.querySelector(".justify-end")).not.toBeNull();
  });

  it("edit mode: once the schema is known the skeleton has the form's own rows and labels", async () => {
    server.use(
      http.get("*/api/events/:id/", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    mount(<Form id={1} />);
    const skeleton = await screen.findByRole("status", { name: "Loading form" });
    await waitFor(() => expect(within(skeleton).queryByText("Title")).not.toBeNull());
    const labels = Array.from(skeleton.querySelectorAll("label")).map((label) =>
      label.textContent?.replace(" *", ""),
    );
    expect(labels).toEqual(WRITABLE);
  });

  it("the loaded form renders the same rows the skeleton promised", async () => {
    mount(<Form id={1} />);
    await title();
    const rows = Array.from(document.querySelectorAll("[data-karni-field]"));
    expect(rows.map((row) => row.querySelector("label")?.textContent?.replace(" *", ""))).toEqual(
      WRITABLE,
    );
  });
});

describe("ResourceForm load failures", () => {
  it("schema failure: plain words and a retry that loads the form", async () => {
    let fail = true;
    server.use(
      http.get("*/api/schema/", () =>
        fail
          ? HttpResponse.json({ detail: "boom" }, { status: 503 })
          : HttpResponse.json(openApiFixture),
      ),
    );
    const user = userEvent.setup();
    mount(<Form />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).not.toHaveTextContent("503");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await title()).toBeInTheDocument();
  });

  it("row failure (5xx): retry", async () => {
    let fail = true;
    server.use(
      http.get("*/api/events/:id/", () =>
        fail ? HttpResponse.json({}, { status: 500 }) : HttpResponse.json(mswDb.events[0]),
      ),
    );
    const user = userEvent.setup();
    mount(<Form id={1} />);
    const alert = await screen.findByRole("alert");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await title()).toHaveValue("Annual Conference");
  });

  it("row not found: says so, no retry", async () => {
    mount(<Form id={999} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't find this event");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();
  });

  it('403 on load: "You can\'t edit this event", not an error', async () => {
    server.use(
      http.get("*/api/events/:id/", () =>
        HttpResponse.json(
          { detail: "You do not have permission to perform this action." },
          { status: 403 },
        ),
      ),
    );
    mount(<Form id={1} />);
    expect(await screen.findByText("You can't edit this event")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

describe("ResourceForm partial permission (per-role schema)", () => {
  it("fields the role cannot see or write are simply absent: no blank rows, no dash, no hint", async () => {
    // What Karni's schema says to a role that may not read capacity and may
    // read but not write venue: capacity is gone, venue is read-only.
    const schema = structuredClone(openApiFixture) as unknown as {
      components: { schemas: Record<string, { properties: Record<string, unknown> }> };
    };
    const { Event, EventRequest, PatchedEventRequest } = schema.components.schemas;
    for (const component of [Event, EventRequest, PatchedEventRequest]) {
      delete component?.properties["capacity"];
    }
    delete EventRequest?.properties["venue"];
    delete PatchedEventRequest?.properties["venue"];
    if (Event !== undefined) {
      Event.properties["venue"] = { ...(Event.properties["venue"] as object), readOnly: true };
    }
    server.use(http.get("*/api/schema/", () => HttpResponse.json(schema)));

    mount(<Form id={1} />);
    await title();
    const rows = Array.from(document.querySelectorAll("[data-karni-field]"));
    expect(rows).toHaveLength(WRITABLE.length - 2);
    expect(screen.queryByText("Capacity")).not.toBeInTheDocument();
    expect(screen.queryByText("Venue")).not.toBeInTheDocument();
    expect(screen.queryByText(/can't|cannot|permission|hidden/i)).not.toBeInTheDocument();
    // Every row is a real field: a label and a control, no placeholder rows.
    for (const row of rows) {
      expect(row.querySelector("label")?.textContent).not.toBe("");
      expect(row.querySelector("input, textarea, button")).not.toBeNull();
    }
  });
});

describe("ResourceForm validation timing", () => {
  it("validates when a field loses focus, not on every keystroke", async () => {
    const user = userEvent.setup();
    mount(<Form />);
    const email = await screen.findByRole("textbox", { name: "Contact email" });
    await user.type(email, "not-an-email");
    expect(email).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("Enter a valid email address.")).not.toBeInTheDocument();
    await user.tab();
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(email).toHaveAttribute("aria-invalid", "true");
  });

  it("re-validates on every change while the field shows an error, so it clears as soon as it is fixed", async () => {
    const user = userEvent.setup();
    mount(<Form />);
    const email = await screen.findByRole("textbox", { name: "Contact email" });
    await user.type(email, "ada");
    await user.tab();
    await screen.findByText("Enter a valid email address.");
    await user.type(email, "@example.com");
    // Still focused: the error went away on change, not on blur.
    expect(email).toHaveFocus();
    await waitFor(() =>
      expect(screen.queryByText("Enter a valid email address.")).not.toBeInTheDocument(),
    );
    expect(email).not.toHaveAttribute("aria-invalid");
  });

  it("a field that loses focus with an error is announced", async () => {
    const user = userEvent.setup();
    mount(<Form />);
    const email = await screen.findByRole("textbox", { name: "Contact email" });
    await user.type(email, "x");
    await user.tab();
    const form = email.closest("form") as HTMLElement;
    await waitFor(() =>
      expect(liveRegion(form)).toHaveTextContent("Contact email: Enter a valid email address."),
    );
  });

  it("validationMode is the escape hatch (onChange validates while typing)", async () => {
    const user = userEvent.setup();
    mount(<Form validationMode="onChange" />);
    const email = await screen.findByRole("textbox", { name: "Contact email" });
    await user.type(email, "x");
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(email).toHaveFocus();
  });
});

describe("ResourceForm submit: client validation, summary and focus", () => {
  it("more than one failing field: a summary, focused, each entry focusing its field", async () => {
    const user = userEvent.setup();
    const create = onCreate(() => HttpResponse.json({}, { status: 201 }));
    mount(<Form />);
    await title();
    await user.click(screen.getByRole("button", { name: "Create" }));

    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent("2 fields need attention");
    await waitFor(() => expect(summary.parentElement).toHaveFocus());
    expect(create.calls()).toBe(0);

    await user.click(within(summary).getByRole("link", { name: /^Starts at:/ }));
    expect(screen.getByLabelText(/Starts at/)).toHaveFocus();
  });

  it("one failing field: no summary, focus moves to it and its error is announced", async () => {
    const user = userEvent.setup();
    mount(<Form />);
    await user.type(await title(), "Spring gala");
    await user.click(screen.getByRole("button", { name: "Create" }));
    const startsAt = screen.getByLabelText(/Starts at/);
    await waitFor(() => expect(startsAt).toHaveFocus());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(startsAt).toHaveAccessibleDescription("This field is required.");
    expect(liveRegion(startsAt.closest("form") as HTMLElement)).toHaveTextContent(
      "Starts at: This field is required.",
    );
  });
});

describe("ResourceForm submit: every DRF error shape lands on its field", () => {
  it("field lists, plain strings, nested objects, unknown keys and non_field_errors", async () => {
    const user = userEvent.setup();
    onCreate(() =>
      HttpResponse.json(
        {
          title: ["An event with this title already exists."],
          capacity: "Ensure this value is less than or equal to 10000.",
          metadata: { theme: ["Unknown theme."] },
          secret_code: ["Only admins may set this."],
          non_field_errors: ["The venue is closed on that day."],
        },
        { status: 400 },
      ),
    );
    mount(<Form />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Create" }));

    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent("3 fields need attention");
    const entries = within(summary)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(entries).toEqual([
      "Title: An event with this title already exists.",
      "Capacity: Ensure this value is less than or equal to 10000.",
      "Metadata: Theme: Unknown theme.",
      "Secret code: Only admins may set this.",
      "The venue is closed on that day.",
    ]);
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveAccessibleDescription(
      "An event with this title already exists.",
    );
    expect(screen.getByRole("spinbutton", { name: "Capacity" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("textbox", { name: "Metadata" })).toHaveAccessibleDescription(
      "Theme: Unknown theme.",
    );
  });

  it("a 400 with only `detail` (or a bare list) is a form-level message", async () => {
    const user = userEvent.setup();
    onCreate(() => HttpResponse.json(["Events are frozen this week."], { status: 400 }));
    mount(<Form />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Create" }));
    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent("Couldn't create event");
    expect(summary).toHaveTextContent("Events are frozen this week.");
  });

  it("one server field error: focus moves to that field, no summary", async () => {
    const user = userEvent.setup();
    onCreate(() => HttpResponse.json({ title: ["Taken."] }, { status: 400 }));
    mount(<Form />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Create" }));
    const field = screen.getByRole("textbox", { name: "Title" });
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveAccessibleDescription("Taken.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("errors on the select, the relation picker and the file upload are wired to them too", async () => {
    const user = userEvent.setup();
    onCreate(() =>
      HttpResponse.json(
        {
          category: ['"party" is not a valid choice.'],
          venue: ['Invalid pk "99" - object does not exist.'],
          poster: ["Upload a valid image."],
          is_public: ["Must be a valid boolean."],
        },
        { status: 400 },
      ),
    );
    mount(<Form />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Create" }));
    await screen.findByRole("alert");

    const category = screen.getByRole("combobox", { name: "Category" });
    expect(category).toHaveAttribute("aria-invalid", "true");
    expect(category).toHaveAccessibleDescription('"party" is not a valid choice.');
    const venue = screen.getByRole("combobox", { name: "Venue" });
    expect(venue).toHaveAttribute("aria-invalid", "true");
    expect(venue).toHaveAccessibleDescription('Invalid pk "99" - object does not exist.');
    const poster = screen.getByRole("button", { name: "Poster" });
    expect(poster).toHaveAttribute("aria-invalid", "true");
    expect(poster).toHaveAccessibleDescription("Upload a valid image.");
    const isPublic = screen.getByRole("switch", { name: "Is public" });
    expect(isPublic).toHaveAttribute("aria-invalid", "true");

    // The summary's entries focus each kind of control.
    const summary = screen.getByRole("alert");
    await user.click(within(summary).getByRole("link", { name: /^Venue:/ }));
    expect(venue).toHaveFocus();
    await user.click(within(summary).getByRole("link", { name: /^Poster:/ }));
    expect(poster).toHaveFocus();
    await user.click(within(summary).getByRole("link", { name: /^Category:/ }));
    expect(category).toHaveFocus();
  });
});

describe("ResourceForm submit: every failure status, and the typed input stays", () => {
  const cases: Array<[string, () => Response, RegExp, boolean]> = [
    ["offline", () => HttpResponse.error(), /Couldn't reach the server/, true],
    ["401", () => HttpResponse.json({}, { status: 401 }), /Your session has ended/, false],
    ["403", () => HttpResponse.json({}, { status: 403 }), /You can't create events/, false],
    ["404", () => HttpResponse.json({}, { status: 404 }), /Couldn't find events/, false],
    [
      "409",
      () => HttpResponse.json({}, { status: 409 }),
      /This changed while you were working/,
      false,
    ],
    ["429", () => HttpResponse.json({}, { status: 429 }), /Too many requests/, true],
    ["500", () => HttpResponse.json({}, { status: 500 }), /Something went wrong on our side/, true],
    ["503", () => HttpResponse.json({}, { status: 503 }), /Something went wrong on our side/, true],
  ];

  it.each(cases)(
    "%s: a banner in plain words, focused; values kept",
    async (_name, respond, text, retry) => {
      const user = userEvent.setup();
      const onError = vi.fn();
      onCreate(respond);
      mount(<Form onError={onError} />);
      await fillRequired(user);
      await user.type(screen.getByRole("textbox", { name: "Description" }), "Bring snacks");
      await user.click(screen.getByRole("button", { name: "Create" }));

      const banner = await screen.findByRole("alert");
      expect(banner).toHaveTextContent(text);
      expect(banner.textContent).not.toMatch(/\b(401|403|404|409|429|500|503)\b/);
      await waitFor(() => expect(banner.parentElement).toHaveFocus());
      expect(within(banner).queryByRole("button", { name: "Try again" }) !== null).toBe(retry);
      expect(onError).toHaveBeenCalledTimes(1);

      // Never lose typed input.
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Spring gala");
      expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("Bring snacks");
      expect(screen.getByLabelText(/Starts at/)).toHaveValue("2026-05-01T18:30");
    },
  );

  it("validation failures (400, 422) keep the typed input too", async () => {
    for (const status of [400, 422]) {
      const user = userEvent.setup();
      onCreate(() => HttpResponse.json({ title: ["Taken."] }, { status }));
      mount(<Form />);
      await fillRequired(user);
      await user.click(screen.getByRole("button", { name: "Create" }));
      await screen.findByText("Taken.");
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Spring gala");
      document.body.innerHTML = "";
    }
  });

  it('edit mode 403: "You can\'t save this event"', async () => {
    const user = userEvent.setup();
    server.use(http.patch("*/api/events/:id/", () => HttpResponse.json({}, { status: 403 })));
    mount(<Form id={1} />);
    const field = await title();
    await user.type(field, "!");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't save this event");
    expect(field).toHaveValue("Annual Conference!");
  });

  it("edit mode 409: offers the latest version, keeping what was typed", async () => {
    const user = userEvent.setup();
    server.use(http.patch("*/api/events/:id/", () => HttpResponse.json({}, { status: 409 })));
    mount(<Form id={1} />);
    const field = await title();
    await user.clear(field);
    await user.type(field, "Renamed");
    // Someone else changed the description meanwhile.
    const record = mswDb.events.find((event) => event.id === 1);
    if (record !== undefined) record.description = "Changed elsewhere";
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("This changed while you were working");
    await user.click(within(banner).getByRole("button", { name: "Load the latest version" }));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("Changed elsewhere"),
    );
    expect(field).toHaveValue("Renamed");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("Try again resubmits what is in the fields now", async () => {
    const user = userEvent.setup();
    let fail = true;
    const bodies: unknown[] = [];
    server.use(
      http.post("*/api/events/", async ({ request }) => {
        bodies.push(await request.json());
        return fail
          ? HttpResponse.error()
          : HttpResponse.json({ id: 50, title: "Spring gala!" }, { status: 201 });
      }),
    );
    const onSuccess = vi.fn();
    mount(<Form onSuccess={onSuccess} />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Create" }));
    const banner = await screen.findByRole("alert");
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!");
    fail = false;
    await user.click(within(banner).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(bodies).toHaveLength(2);
    expect((bodies[1] as Record<string, unknown>)["title"]).toBe("Spring gala!");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ResourceForm slow submit", () => {
  it("disables the fields and the button (which keeps its width) without losing values", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    onCreate(
      () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(HttpResponse.json({ id: 77 }, { status: 201 }));
        }),
    );
    const onSuccess = vi.fn();
    mount(<Form onSuccess={onSuccess} />);
    await fillRequired(user);
    const button = screen.getByRole("button", { name: "Create" });
    await user.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("aria-busy", "true");
    const field = screen.getByRole("textbox", { name: "Title" });
    expect(field).toBeDisabled();
    expect(field).toHaveValue("Spring gala");
    // Progress appears only once the work is slow; the label stays in the layout.
    expect(button.querySelector("svg.animate-spin")).toBeNull();
    await waitFor(() => expect(button.querySelector("svg.animate-spin")).not.toBeNull(), {
      timeout: 1500,
    });
    expect(within(button).getByText("Create")).toHaveClass("text-transparent");
    // Hidden by opacity, not visibility: the button keeps its accessible name.
    expect(button).toHaveAccessibleName("Create");

    // A second click while in flight sends nothing.
    fireEvent.click(button);
    act(() => release());
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(field).not.toBeDisabled();
  });
});

describe("ResourceForm keyboard", () => {
  it("Enter in a text input submits", async () => {
    const user = userEvent.setup();
    const create = onCreate(() => HttpResponse.json({ id: 1 }, { status: 201 }));
    mount(<Form />);
    await fillRequired(user);
    await user.type(screen.getByRole("textbox", { name: "Title" }), "{Enter}");
    await waitFor(() => expect(create.calls()).toBe(1));
  });

  it("Ctrl+Enter (or Cmd+Enter) in a textarea submits; plain Enter adds a line", async () => {
    const user = userEvent.setup();
    const create = onCreate(() => HttpResponse.json({ id: 1 }, { status: 201 }));
    mount(<Form />);
    await fillRequired(user);
    const description = screen.getByRole("textbox", { name: "Description" });
    await user.type(description, "one{Enter}two");
    expect(description).toHaveValue("one\ntwo");
    expect(create.calls()).toBe(0);
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(create.calls()).toBe(1));
    // The created form starts over; fill it again and use Cmd+Enter.
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue(""));
    await fillRequired(user);
    await user.click(description);
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(create.calls()).toBe(2));
  });

  it("Enter inside an open relation picker chooses an option and does not submit", async () => {
    const user = userEvent.setup();
    const create = onCreate(() => HttpResponse.json({ id: 1 }, { status: 201 }));
    mount(<Form />);
    await fillRequired(user);
    const venue = screen.getByRole("combobox", { name: "Venue" });
    await user.click(venue);
    await screen.findByRole("option", { name: "Grand Hall" });
    await user.keyboard("{Enter}");
    await waitFor(() => expect(venue).toHaveValue("Grand Hall"));
    expect(create.calls()).toBe(0);
  });

  it("with custom actions that have no submit button, Enter in an input still submits", async () => {
    const user = userEvent.setup();
    const create = onCreate(() => HttpResponse.json({ id: 1 }, { status: 201 }));
    mount(<Form actions={<span>Saved automatically</span>} />);
    await fillRequired(user);
    await user.type(screen.getByRole("textbox", { name: "Title" }), "{Enter}");
    await waitFor(() => expect(create.calls()).toBe(1));
  });
});

describe("ResourceForm autofocus", () => {
  it("create: the first field", async () => {
    mount(<Form />);
    await waitFor(async () => expect(await title()).toHaveFocus());
  });

  it("edit: nothing, unless asked", async () => {
    mount(<Form id={1} />);
    const field = await title();
    expect(field).not.toHaveFocus();
    document.body.innerHTML = "";
    mount(<Form id={1} autoFocus />);
    await waitFor(async () => expect(await title()).toHaveFocus());
  });
});

describe("ResourceForm accessibility", () => {
  it("every field kind has a bound label; required fields say so", async () => {
    mount(<Form />);
    await title();
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText(/Starts at/)).toHaveAttribute("aria-required", "true");
    expect(screen.getByRole("textbox", { name: "Description" })).not.toHaveAttribute(
      "aria-required",
    );
    expect(screen.getByRole("spinbutton", { name: "Capacity" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Category" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Is public" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Venue" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Tags" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Poster" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Metadata" })).toBeInTheDocument();
  });

  it("a required file field says so in its label (a button cannot carry aria-required)", async () => {
    const schema = structuredClone(openApiFixture) as unknown as {
      components: { schemas: Record<string, { required?: string[] }> };
    };
    const request = schema.components.schemas["EventRequest"];
    if (request !== undefined) request.required = [...(request.required ?? []), "poster"];
    server.use(http.get("*/api/schema/", () => HttpResponse.json(schema)));
    mount(<Form />);
    await title();
    expect(screen.getByRole("button", { name: "Poster (required)" })).toBeInTheDocument();
  });
});

describe("ResourceForm unsaved changes", () => {
  function unload(): Event {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event;
  }

  it("warns before unloading while dirty, and not after a successful save", async () => {
    const user = userEvent.setup();
    onCreate(() => HttpResponse.json({ id: 9 }, { status: 201 }));
    const onSuccess = vi.fn();
    mount(<Form onSuccess={onSuccess} />);
    expect(unload().defaultPrevented).toBe(false);
    await fillRequired(user);
    await waitFor(() => expect(unload().defaultPrevented).toBe(true));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(unload().defaultPrevented).toBe(false);
    // A created form starts over, clean, and stays clean.
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue(""));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(unload().defaultPrevented).toBe(false);
  });

  it("edit: after a save the form keeps the saved values and is clean", async () => {
    const user = userEvent.setup();
    const onDirtyChange = vi.fn();
    mount(<Form id={1} onDirtyChange={onDirtyChange} />);
    const field = await title();
    await user.type(field, "!");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(field).toHaveValue("Annual Conference!");
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    expect(unload().defaultPrevented).toBe(false);
    expect(mswDb.events.find((event) => event.id === 1)?.title).toBe("Annual Conference!");
  });

  it("guardUnsavedChanges={false} opts out", async () => {
    const user = userEvent.setup();
    mount(<Form guardUnsavedChanges={false} />);
    await user.type(await title(), "x");
    expect(unload().defaultPrevented).toBe(false);
  });

  it("onDirtyChange + useUnsavedChangesGuard block in-app navigation, never after a save", async () => {
    const user = userEvent.setup();
    onCreate(() => HttpResponse.json({ id: 9 }, { status: 201 }));
    const confirm = vi.fn(() => false);
    const blockedAtSuccess: boolean[] = [];
    let guard: ReturnType<typeof useUnsavedChangesGuard> | undefined;
    function Page(): React.ReactElement {
      const current = useUnsavedChangesGuard({ confirm });
      guard = current;
      return (
        <Form
          onDirtyChange={current.setDirty}
          // What a router blocker would ask while navigating from onSuccess.
          onSuccess={() => blockedAtSuccess.push(current.shouldBlock())}
        />
      );
    }
    mount(<Page />);
    await title();
    expect(guard?.shouldBlock()).toBe(false);
    await fillRequired(user);
    await waitFor(() => expect(guard?.dirty).toBe(true));
    expect(guard?.shouldBlock()).toBe(true);
    expect(confirm).toHaveBeenCalledWith(guard?.message);
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(blockedAtSuccess).toEqual([false]));
    expect(confirm).toHaveBeenCalledTimes(1);
  });
});

describe("useUnsavedChangesGuard", () => {
  it("controlled, with window.confirm by default", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    let guard: ReturnType<typeof useUnsavedChangesGuard> | undefined;
    function Probe(props: { dirty: boolean }): null {
      guard = useUnsavedChangesGuard({ dirty: props.dirty });
      return null;
    }
    const { rerender } = render(<Probe dirty={false} />);
    expect(guard?.isDirty()).toBe(false);
    rerender(<Probe dirty />);
    expect(guard?.isDirty()).toBe(true);
    // The user chose to leave: not blocked.
    expect(guard?.shouldBlock()).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    confirm.mockReturnValue(false);
    expect(guard?.shouldBlock()).toBe(true);
  });

  it("enabled: false turns it off", () => {
    let guard: ReturnType<typeof useUnsavedChangesGuard> | undefined;
    function Probe(): null {
      guard = useUnsavedChangesGuard({ dirty: true, enabled: false });
      return null;
    }
    render(<Probe />);
    expect(guard?.dirty).toBe(false);
    expect(guard?.shouldBlock()).toBe(false);
  });
});
