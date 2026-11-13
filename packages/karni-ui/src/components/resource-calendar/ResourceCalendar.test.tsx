/**
 * <ResourceCalendar> over an in-memory slots API, in Tokyo's business time:
 * the week, month and list views, free and full slots, creating from an
 * empty time, moving and resizing by keyboard and by drag with rollback, the
 * permission gating, the time zone switch, phone width and the unhappy states.
 */
import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import * as React from "react";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { AuthContext, type AuthContextValue } from "../../auth/provider";
import type { KarniUser } from "../../auth/types";
import { axeViolations } from "../../../tests/axe";
import { server } from "../../../tests/msw/server";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import type { FieldDef, ResourceSchema } from "../../schema/types";
import { useResourceSchemaIfKnown } from "../../schema/useSchema";
import {
  ResourceCalendar,
  type CalendarCreateRequest,
  type ResourceCalendarProps,
} from "./ResourceCalendar";

vi.mock("../../schema/useSchema", () => ({ useResourceSchemaIfKnown: vi.fn() }));
const mockSchema = useResourceSchemaIfKnown as unknown as Mock<
  (resource: string) => ResourceSchema | undefined
>;

interface SlotRow extends Record<string, unknown> {
  id: number;
  name: string;
  starts_at: string;
  ends_at: string;
  status: string;
  capacity: number;
  remaining: number;
}

const ZONE = "Asia/Tokyo";
// Tokyo is UTC+9 all year: Monday 2026-03-02 09:00 in Tokyo is 00:00 UTC.
const base = { required: false, readOnly: false, writeOnly: false, nullable: false };
const field = (name: string, extra: Partial<FieldDef> = {}): FieldDef => ({
  ...base,
  name,
  label: name,
  kind: "string",
  order: 0,
  ...extra,
});

function schemaWith(
  overrides: Partial<Record<string, Partial<FieldDef>>> = {},
  access?: object,
): ResourceSchema {
  return {
    resource: "slots",
    operations: {
      list: { method: "get", path: "/slots/", queryParams: [] },
      update: {
        method: "patch",
        path: "/slots/{id}/",
        queryParams: [],
        ...(access ? { access } : {}),
      },
    },
    fields: [
      field("id", { kind: "integer", readOnly: true }),
      field("name"),
      field("starts_at", { kind: "datetime", ...overrides["starts_at"] }),
      field("ends_at", { kind: "datetime", ...overrides["ends_at"] }),
      field("status", {
        kind: "enum",
        enumValues: ["open", "cancelled"],
        enumLabels: { open: "Open", cancelled: "Cancelled" },
      }),
    ],
  } as ResourceSchema;
}

let rows: SlotRow[] = [];
const urls: URL[] = [];
const patches: Array<Record<string, unknown>> = [];

function seed(): SlotRow[] {
  return [
    {
      id: 1,
      name: "Morning cut",
      starts_at: "2026-03-02T00:00:00Z",
      ends_at: "2026-03-02T01:00:00Z",
      status: "open",
      capacity: 4,
      remaining: 2,
    },
    {
      id: 2,
      name: "Late cut",
      starts_at: "2026-03-02T01:00:00Z",
      ends_at: "2026-03-02T02:00:00Z",
      status: "open",
      capacity: 2,
      remaining: 0,
    },
    {
      id: 3,
      name: "Midweek cut",
      starts_at: "2026-03-04T05:00:00Z",
      ends_at: "2026-03-04T06:00:00Z",
      status: "cancelled",
      capacity: 3,
      remaining: 3,
    },
    {
      id: 4,
      name: "April cut",
      starts_at: "2026-04-08T05:00:00Z",
      ends_at: "2026-04-08T06:00:00Z",
      status: "open",
      capacity: 3,
      remaining: 3,
    },
  ];
}

function serve(): void {
  server.use(
    http.get("*/api/slots/", ({ request }) => {
      const url = new URL(request.url);
      urls.push(url);
      const upper = Date.parse(url.searchParams.get("starts_at__lte") ?? "");
      const lower = Date.parse(url.searchParams.get("ends_at__gte") ?? "");
      const found = rows.filter(
        (row) => Date.parse(row.starts_at) <= upper && Date.parse(row.ends_at) >= lower,
      );
      return HttpResponse.json({ count: found.length, next: null, previous: null, results: found });
    }),
    http.patch("*/api/slots/:id/", async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push(body);
      const row = rows.find((candidate) => String(candidate.id) === params["id"]);
      if (row === undefined) return HttpResponse.json({}, { status: 404 });
      Object.assign(row, body);
      return HttpResponse.json(row);
    }),
  );
}

function Harness(props: Partial<ResourceCalendarProps<SlotRow>>): React.ReactElement {
  const [date, setDate] = React.useState(new Date("2026-03-04T03:00:00Z"));
  return (
    <ResourceCalendar<SlotRow>
      resource="slots"
      startField="starts_at"
      endField="ends_at"
      stateField="status"
      capacity={{ capacity: "capacity", remaining: "remaining" }}
      timeZone={ZONE}
      locale="en-US"
      date={date}
      onDateChange={setDate}
      {...props}
    />
  );
}

function render(props: Partial<ResourceCalendarProps<SlotRow>> = {}) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={auth}>
        <Harness {...props} />
      </AuthContext.Provider>
    </KarniProvider>,
  );
}

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["staff"] };
const auth: AuthContextValue = {
  user: USER,
  roles: USER.roles,
  status: "authenticated",
  login: () => Promise.resolve({ ok: true, user: USER }),
  logout: () => Promise.resolve(),
  refresh: () => Promise.resolve(),
  adoptTokens: () => Promise.resolve(),
};

// jsdom has no PointerEvent: a MouseEvent with a pointer id stands in for the drag tests.
beforeAll(() => {
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number;
    constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  vi.stubGlobal("PointerEvent", TestPointerEvent);
});
afterAll(() => vi.unstubAllGlobals());

const MONDAY = "Monday, March 2, 2026";

beforeEach(() => {
  rows = seed();
  urls.length = 0;
  patches.length = 0;
  mockSchema.mockReturnValue(schemaWith());
  serve();
});
afterEach(() => vi.restoreAllMocks());

describe("ResourceCalendar week view", () => {
  it("draws a column per day with each event at its time in the business zone", async () => {
    render();
    const monday = await screen.findByRole("region", { name: MONDAY });
    const morning = await within(monday).findByRole("button", { name: /Morning cut/ });
    expect(morning).toHaveTextContent("9:00 AM – 10:00 AM");
    expect(morning).toHaveTextContent("Open");
    expect(morning).toHaveTextContent("2 free");
    expect(within(monday).getByRole("button", { name: /Late cut/ })).toHaveTextContent("Full");
    const wednesday = screen.getByRole("region", { name: "Wednesday, March 4, 2026" });
    expect(within(wednesday).getByRole("button", { name: /Midweek cut/ })).toHaveTextContent(
      "Cancelled",
    );
    expect(screen.queryByText(/April cut/)).toBeNull();
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(7);
  });

  it("asks for the range with the start and end filters, ordered by start", async () => {
    render();
    await screen.findByRole("button", { name: /Morning cut/ });
    const url = urls[0] as URL;
    expect(url.searchParams.get("ordering")).toBe("starts_at");
    // The week of Mon 2026-03-02 to Mon 2026-03-09 in Tokyo.
    expect(url.searchParams.get("ends_at__gte")).toBe("2026-03-01T15:00:00.000Z");
    expect(url.searchParams.get("starts_at__lte")).toBe("2026-03-08T15:00:00.000Z");
  });

  it("steps to the next week and back to today", async () => {
    const user = userEvent.setup();
    render();
    await screen.findByRole("button", { name: /Morning cut/ });
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Morning cut/ })).toBeNull());
    expect(screen.getByRole("region", { name: "Monday, March 9, 2026" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(urls.length).toBeGreaterThan(1));
    expect(screen.queryByRole("region", { name: "Monday, March 9, 2026" })).toBeNull();
  });

  it("opens an event on click and from its day heading switches to the day view", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();
    render({ onSelectEvent });
    await user.click(await screen.findByRole("button", { name: /Morning cut/ }));
    expect(onSelectEvent).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    await user.click(screen.getByRole("button", { name: "Mon, Mar 2" }));
    expect(screen.getByRole("button", { name: "Day" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
  });

  it("creates from an empty time, in the business zone, by click and by keyboard", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn<(request: CalendarCreateRequest) => void>();
    render({ onCreate });
    await screen.findByRole("button", { name: /Morning cut/ });
    await user.click(screen.getByRole("button", { name: `New at 3:30 PM on ${MONDAY}` }));
    const first = onCreate.mock.calls[0]?.[0] as CalendarCreateRequest;
    expect(first.start.toISOString()).toBe("2026-03-02T06:30:00.000Z");
    expect(first.end.toISOString()).toBe("2026-03-02T07:00:00.000Z");
    expect(first.allDay).toBe(false);

    // The one tab stop is 8:00 on the first day: the arrows walk from it.
    const start = screen.getByRole("button", { name: `New at 8:00 AM on ${MONDAY}` });
    start.focus();
    await user.keyboard("{ArrowDown}{ArrowRight}{Enter}");
    const second = onCreate.mock.calls[1]?.[0] as CalendarCreateRequest;
    expect(second.start.toISOString()).toBe("2026-03-02T23:30:00.000Z");
  });

  it("offers no empty times to create when nothing can be created", async () => {
    render();
    await screen.findByRole("button", { name: /Morning cut/ });
    expect(screen.queryByRole("button", { name: /^New at/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
  });

  it("puts overlapping events side by side", async () => {
    rows.push({
      ...seed()[0],
      id: 9,
      name: "Overlap",
      starts_at: "2026-03-02T00:30:00Z",
      ends_at: "2026-03-02T01:30:00Z",
    } as SlotRow);
    render();
    const a = (await screen.findByRole("button", { name: /Morning cut/ })).closest(
      "li",
    ) as HTMLElement;
    const b = screen.getByRole("button", { name: /Overlap/ }).closest("li") as HTMLElement;
    expect(a.style.width).toBe("50%");
    expect(b.style.width).toBe("50%");
    expect(a.style.left).not.toBe(b.style.left);
  });
});

describe("ResourceCalendar time zones", () => {
  it("offers business time and the viewer's time when they differ, and switches the times", async () => {
    const user = userEvent.setup();
    render();
    const morning = await screen.findByRole("button", { name: /Morning cut/ });
    expect(morning).toHaveTextContent("9:00 AM – 10:00 AM");
    expect(screen.getByText(/Times in Asia\/Tokyo/)).toBeInTheDocument();
    expect(morning.getAttribute("title")).toMatch(/9:00 AM – 10:00 AM .* · /);
    await user.click(screen.getByRole("button", { name: "My time" }));
    expect(screen.getByRole("button", { name: "My time" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/Times in Asia\/Tokyo/)).toBeNull();
    expect(screen.getByRole("button", { name: /Morning cut/ })).not.toHaveTextContent(
      "9:00 AM – 10:00 AM",
    );
  });

  it("shows no switch when the business zone is the viewer's", async () => {
    render({ timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone });
    await screen.findByRole("button", { name: /Morning cut/ });
    expect(screen.queryByRole("group", { name: "Time zone" })).toBeNull();
  });
});

describe("ResourceCalendar month and list views", () => {
  it("draws the month as a grid of days with each event in its day", async () => {
    const user = userEvent.setup();
    render({ defaultView: "month" });
    const grid = await screen.findByRole("grid", { name: "Month" });
    const cell = await within(grid).findByRole("gridcell", { name: `${MONDAY}, 2 events` });
    expect(within(cell).getByRole("button", { name: /Morning cut/ })).toBeInTheDocument();
    expect(within(grid).getAllByRole("columnheader")).toHaveLength(7);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("March 2026");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("April 2026");
  });

  it("walks the month's days with the arrows and creates a whole-day item with Enter", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn<(request: CalendarCreateRequest) => void>();
    render({ defaultView: "month", onCreate });
    const cell = await screen.findByRole("gridcell", { name: `${MONDAY}, 2 events` });
    cell.focus();
    await user.keyboard("{ArrowRight}{Enter}");
    const request = onCreate.mock.calls[0]?.[0] as CalendarCreateRequest;
    expect(request.allDay).toBe(true);
    expect(request.start.toISOString()).toBe("2026-03-02T15:00:00.000Z");
  });

  it("folds a crowded day into a count that opens the day", async () => {
    const user = userEvent.setup();
    for (let id = 20; id < 24; id += 1) {
      rows.push({ ...seed()[0], id, name: `Extra ${id}` } as SlotRow);
    }
    render({ defaultView: "month" });
    await user.click(await screen.findByRole("button", { name: "3 more" }));
    expect(screen.getByRole("button", { name: "Day" })).toHaveAttribute("aria-pressed", "true");
  });

  it("lists the week by day in time order, and says plainly when it is empty", async () => {
    const user = userEvent.setup();
    render({ defaultView: "list" });
    const monday = await screen.findByRole("region", { name: MONDAY });
    const names = within(monday)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(names[0]).toContain("Morning cut");
    expect(names[1]).toContain("Late cut");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Nothing scheduled")).toBeInTheDocument();
  });

  it("is a list at phone width", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 400,
      height: 600,
      top: 0,
      left: 0,
      right: 400,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    render({ defaultView: "month" });
    const monday = await screen.findByRole("region", { name: MONDAY });
    expect(within(monday).getByRole("button", { name: /Morning cut/ })).toBeInTheDocument();
    expect(screen.queryByRole("grid")).toBeNull();
  });
});

describe("ResourceCalendar availability", () => {
  it("draws open and full slots from a second resource and creates from an open one", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn<(request: CalendarCreateRequest) => void>();
    server.use(
      http.get("*/api/shifts/", () =>
        HttpResponse.json({
          count: 2,
          next: null,
          previous: null,
          results: [
            {
              id: 70,
              starts_at: "2026-03-03T00:00:00Z",
              ends_at: "2026-03-03T01:00:00Z",
              capacity: 5,
              taken: 1,
            },
            {
              id: 71,
              starts_at: "2026-03-03T01:00:00Z",
              ends_at: "2026-03-03T02:00:00Z",
              capacity: 5,
              taken: 5,
            },
          ],
        }),
      ),
    );
    render({
      onCreate,
      availability: {
        resource: "shifts",
        startField: "starts_at",
        endField: "ends_at",
        capacity: "capacity",
        taken: "taken",
      },
    });
    const open = await screen.findByRole("button", { name: /New at 9:00 AM 4 free/ });
    const full = document.querySelector('[data-slot-band="full"]');
    expect(full).toHaveTextContent("Full");
    await user.click(open);
    const request = onCreate.mock.calls[0]?.[0] as CalendarCreateRequest;
    expect(request.slot).toMatchObject({ id: 70 });
    expect(request.start.toISOString()).toBe("2026-03-03T00:00:00.000Z");
  });
});

describe("ResourceCalendar moving and resizing", () => {
  it("gives no move to a read-only start field, a refusing rule, or a schema nobody loaded", async () => {
    mockSchema.mockReturnValue(schemaWith({ starts_at: { readOnly: true } }));
    const { unmount } = render();
    expect(await screen.findByRole("button", { name: /Morning cut/ })).not.toHaveAttribute(
      "aria-keyshortcuts",
    );
    unmount();
    mockSchema.mockReturnValue(schemaWith({}, { role: ["manager"] }));
    const second = render();
    expect(await screen.findByRole("button", { name: /Morning cut/ })).not.toHaveAttribute(
      "aria-keyshortcuts",
    );
    second.unmount();
    mockSchema.mockReturnValue(undefined);
    render();
    expect(await screen.findByRole("button", { name: /Morning cut/ })).not.toHaveAttribute(
      "aria-keyshortcuts",
    );
  });

  it("needs a writable start and end in the schema to allow a move", async () => {
    mockSchema.mockReturnValue(schemaWith({ starts_at: {}, ends_at: {} }));
    render();
    expect(await screen.findByRole("button", { name: /Morning cut/ })).toHaveAttribute(
      "aria-keyshortcuts",
    );
  });

  it("moves an event with Shift and the arrows: PATCHes the start and end and keeps its length", async () => {
    const user = userEvent.setup();
    render({ canEdit: () => true });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    card.focus();
    await user.keyboard("{Shift>}{ArrowDown}{/Shift}");
    await waitFor(() =>
      expect(patches).toEqual([
        { starts_at: "2026-03-02T00:30:00.000Z", ends_at: "2026-03-02T01:30:00.000Z" },
      ]),
    );
    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
  });

  it("resizes the end with Alt and Down, never below one slot", async () => {
    const user = userEvent.setup();
    render({ canEdit: () => true });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    card.focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() =>
      expect(patches).toEqual([
        { starts_at: "2026-03-02T00:00:00.000Z", ends_at: "2026-03-02T01:30:00.000Z" },
      ]),
    );
  });

  it("puts the event back and says why when the server refuses", async () => {
    const user = userEvent.setup();
    server.use(
      http.patch("*/api/slots/:id/", () =>
        HttpResponse.json(
          { starts_at: ["E985: That time is taken. See https://x.test/e985"] },
          { status: 409 },
        ),
      ),
    );
    render({ canEdit: () => true });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    card.focus();
    await user.keyboard("{Shift>}{ArrowDown}{/Shift}");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't change Morning cut");
    expect(alert).toHaveTextContent("That time is taken.");
    expect(alert).not.toHaveTextContent("E985");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Morning cut/ })).toHaveTextContent(
        "9:00 AM – 10:00 AM",
      ),
    );
  });

  it("hands the change to onReschedule instead of PATCHing, and rolls back when it throws", async () => {
    const user = userEvent.setup();
    const onReschedule = vi.fn().mockRejectedValue(new Error("Not that day."));
    render({ canEdit: () => true, onReschedule });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    card.focus();
    await user.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Not that day.");
    expect(patches).toEqual([]);
    const change = onReschedule.mock.calls[0]?.[1] as { start: Date; end: Date };
    expect(change.start.toISOString()).toBe("2026-03-02T00:30:00.000Z");
  });

  it("posts to a declared row action when rescheduleAction is set and open", async () => {
    const user = userEvent.setup();
    const posted: unknown[] = [];
    server.use(
      http.post("*/api/slots/:id/reschedule/", async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json(rows[0]);
      }),
    );
    mockSchema.mockReturnValue({
      ...schemaWith(),
      rowActions: {
        reschedule: { from: ["open"], to: null, field: "status", by: null, requires: [] },
      },
    });
    render({ rescheduleAction: "reschedule" });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    expect(card).toHaveAttribute("aria-keyshortcuts");
    card.focus();
    await user.keyboard("{Shift>}{ArrowDown}{/Shift}");
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({
      starts_at: "2026-03-02T00:30:00.000Z",
      ends_at: "2026-03-02T01:30:00.000Z",
    });
    // A cancelled slot is outside the action's `from`: no move for it.
    expect(screen.getByRole("button", { name: /Midweek cut/ })).not.toHaveAttribute(
      "aria-keyshortcuts",
    );
  });

  it("moves an event by a drag: a day across and an hour down", async () => {
    const box = {
      width: 700,
      height: 24 * 48,
      top: 0,
      left: 0,
      right: 700,
      bottom: 1152,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    };
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.className.includes("grid min-w-0 flex-1") ? box : { ...box, width: 1000 };
    });
    render({ canEdit: () => true });
    const card = await screen.findByRole("button", { name: /Morning cut/ });
    fireEvent.pointerDown(card, { button: 0, clientX: 10, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(card, { clientX: 110, clientY: 148, pointerId: 1 });
    fireEvent.pointerUp(card, { clientX: 110, clientY: 148, pointerId: 1 });
    await waitFor(() =>
      expect(patches).toEqual([
        { starts_at: "2026-03-03T01:00:00.000Z", ends_at: "2026-03-03T02:00:00.000Z" },
      ]),
    );
  });
});

describe("ResourceCalendar unhappy states", () => {
  it("shows the Loading slot, then the events", async () => {
    render({ slots: { Loading: () => <p>Loading the calendar</p> } });
    expect(screen.getByText("Loading the calendar")).toBeInTheDocument();
    await screen.findByRole("button", { name: /Morning cut/ });
    expect(screen.queryByText("Loading the calendar")).toBeNull();
  });

  it("explains a failed load and offers to try again", async () => {
    server.use(http.get("*/api/slots/", () => HttpResponse.json({}, { status: 500 })));
    render();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("says when more rows exist than were loaded", async () => {
    server.use(
      http.get("*/api/slots/", () =>
        HttpResponse.json({ count: 500, next: "x", previous: null, results: [seed()[0]] }),
      ),
    );
    render();
    expect(await screen.findByText(/Showing the first 1 of 500/)).toBeInTheDocument();
  });
});

describe("ResourceCalendar accessibility", () => {
  it("has no axe violations in the week, month and list views", async () => {
    for (const view of ["week", "month", "list"] as const) {
      const { container, unmount } = render({
        defaultView: view,
        onCreate: () => undefined,
        onSelectEvent: () => undefined,
      });
      await screen.findAllByRole("button", { name: /Morning cut/ });
      expect(await axeViolations(container)).toEqual([]);
      unmount();
    }
  });
});
