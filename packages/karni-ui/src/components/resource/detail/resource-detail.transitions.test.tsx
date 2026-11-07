/**
 * ResourceDetail's lifecycle buttons: one per state the record may move to
 * (x-karni-transitions), shown only when the API lets this user write the
 * field, a PATCH on click, a question first before a move nobody can undo,
 * and the server's own words when it refuses.
 */
import { QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { server } from "../../../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../../../auth/provider";
import type { KarniUser } from "../../../auth/types";
import type { ResourceItemParams } from "../../../hooks/types";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema, type UseSchemaResult } from "../../../schema/useSchema";
import { eventFields, eventRecord, eventSchema } from "../form/fixtures";
import { ResourceDetail, defaultResourceDetailSlots } from "./ResourceDetail";

vi.mock("../../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../../hooks/useResourceItem", () => ({ useResourceItem: vi.fn() }));

type Row = Record<string, unknown>;
const mockUseSchema = useSchema as unknown as Mock<(resource: string) => UseSchemaResult>;
const mockUseResourceItem = useResourceItem as unknown as Mock<
  (resource: string, id: string | number, params?: ResourceItemParams) => UseQueryResult<Row>
>;

/** An order's lifecycle: draft → confirmed → cancelled / refunded (two terminal states). */
const statusField: FieldDef = {
  name: "status",
  label: "Status",
  kind: "enum",
  required: false,
  readOnly: false,
  writeOnly: false,
  nullable: false,
  order: 5,
  enumValues: ["draft", "confirmed", "cancelled", "refunded"],
  enumLabels: {
    draft: "Draft",
    confirmed: "Confirmed",
    cancelled: "Cancelled",
    refunded: "Refunded",
  },
  transitions: {
    draft: ["confirmed", "cancelled"],
    confirmed: ["cancelled", "refunded"],
    cancelled: [],
    refunded: [],
  },
  initial: ["draft"],
};

const schema: ResourceSchema = {
  ...eventSchema,
  fields: eventFields.map((field) => (field.name === "status" ? statusField : field)),
};
const record: Row = { ...eventRecord, status: "draft" };

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["staff"] };
function auth(partial: Partial<AuthContextValue>): AuthContextValue {
  return {
    user: USER,
    roles: USER.roles,
    status: "authenticated",
    login: () => Promise.resolve({ ok: true, user: USER }),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
    ...partial,
  };
}

function render(ui: React.ReactElement, identity: AuthContextValue = auth({})) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={identity}>{ui}</AuthContext.Provider>
    </KarniProvider>,
  );
}

function loaded(data: Row): UseQueryResult<Row> {
  return {
    data,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<Row>;
}

beforeEach(() => {
  mockUseSchema.mockReturnValue({ data: schema, isLoading: false, error: undefined });
  mockUseResourceItem.mockReturnValue(loaded(record));
});

describe("ResourceDetail lifecycle buttons", () => {
  it("offers the current state's next states, the first open one as the main button", () => {
    render(<ResourceDetail resource="events" id={1} />);
    const group = screen.getByRole("group", { name: "Change status" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Mark as Confirmed",
      "Mark as Cancelled",
    ]);
    expect(buttons[0]).toHaveClass("bg-primary");
    expect(buttons[1]).toHaveClass("border");
  });

  it("PATCHes the field with the chosen state and announces the change", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/events/1/", async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        return HttpResponse.json({ ...record, ...(body as Row) });
      }),
    );
    const onTransition = vi.fn();
    render(<ResourceDetail resource="events" id={1} onTransition={onTransition} />);
    await user.click(screen.getByRole("button", { name: "Mark as Confirmed" }));
    await waitFor(() => expect(bodies).toEqual([{ status: "confirmed" }]));
    await waitFor(() =>
      expect(onTransition).toHaveBeenCalledWith(
        expect.objectContaining({ status: "confirmed" }),
        "status",
        "confirmed",
      ),
    );
    expect(screen.getByText("Status changed to Confirmed.")).toHaveAttribute("role", "status");
  });

  it("asks before a move into a terminal state, and the dialog's cancel keeps the state", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/events/1/", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ ...record, status: "cancelled" });
      }),
    );
    render(<ResourceDetail resource="events" id={1} resourceLabel="order" />);
    await user.click(screen.getByRole("button", { name: "Mark as Cancelled" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as Cancelled?" });
    expect(dialog).toHaveTextContent(
      "The status of this order goes from Draft to Cancelled. Nothing moves it out of Cancelled afterwards.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Keep it Draft" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(bodies).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Mark as Cancelled" }));
    const again = await screen.findByRole("dialog");
    await user.click(within(again).getByRole("button", { name: "Mark as Cancelled" }));
    await waitFor(() => expect(bodies).toEqual([{ status: "cancelled" }]));
  });

  it("shows the server's own sentence when it refuses the move", async () => {
    const user = userEvent.setup();
    server.use(
      http.patch("*/api/events/1/", () =>
        HttpResponse.json(
          {
            status: [
              "E980: Order 3f2a: status cannot go from 'draft' to 'confirmed'. From 'draft' " +
                "the legal transitions are: 'cancelled'. See https://example.test/errors/#e980",
            ],
          },
          { status: 400 },
        ),
      ),
    );
    render(<ResourceDetail resource="events" id={1} resourceLabel="order" />);
    await user.click(screen.getByRole("button", { name: "Mark as Confirmed" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't mark this order as Confirmed");
    expect(alert).toHaveTextContent(
      "Order 3f2a: status cannot go from 'draft' to 'confirmed'. From 'draft' the legal transitions are: 'cancelled'.",
    );
    expect(alert).not.toHaveTextContent("E980");
    expect(alert).not.toHaveTextContent("https://");
  });

  it("shows nothing for a terminal state, a read-only field, or a user the access rule refuses", () => {
    mockUseResourceItem.mockReturnValue(loaded({ ...record, status: "refunded" }));
    const { unmount } = render(<ResourceDetail resource="events" id={1} />);
    expect(screen.queryByRole("group", { name: "Change status" })).toBeNull();
    unmount();

    mockUseResourceItem.mockReturnValue(loaded(record));
    mockUseSchema.mockReturnValue({
      data: {
        ...schema,
        fields: schema.fields.map((field) =>
          field.name === "status" ? { ...field, readOnly: true } : field,
        ),
      },
      isLoading: false,
      error: undefined,
    });
    const readOnly = render(<ResourceDetail resource="events" id={1} />);
    expect(screen.queryByRole("group", { name: "Change status" })).toBeNull();
    readOnly.unmount();

    mockUseSchema.mockReturnValue({
      data: {
        ...schema,
        operations: {
          ...schema.operations,
          update: {
            path: "/api/events/{id}/",
            method: "patch",
            queryParams: [],
            access: { role: ["manager"] },
          },
        },
      },
      isLoading: false,
      error: undefined,
    });
    render(<ResourceDetail resource="events" id={1} />);
    expect(screen.queryByRole("group", { name: "Change status" })).toBeNull();
  });

  it("transitions={false} hides them, and the options tune labels, fields and who may", () => {
    const { unmount } = render(<ResourceDetail resource="events" id={1} transitions={false} />);
    expect(screen.queryByRole("group", { name: "Change status" })).toBeNull();
    unmount();

    render(
      <ResourceDetail
        resource="events"
        id={1}
        transitions={{
          labels: { confirmed: "Confirm order" },
          can: (_item, _field, target) => target !== "cancelled",
        }}
      />,
    );
    const group = screen.getByRole("group", { name: "Change status" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Confirm order"]);
  });

  it("the Transitions slot replaces the buttons and receives the targets", () => {
    const Transitions = vi.fn(({ targets, currentLabel }) => (
      <p>
        {currentLabel}: {targets.map((target: { value: string }) => target.value).join(",")}
      </p>
    ));
    render(<ResourceDetail resource="events" id={1} slots={{ Transitions }} />);
    expect(screen.getByText("Draft: confirmed,cancelled")).toBeInTheDocument();
    expect(defaultResourceDetailSlots.Transitions).toBeTypeOf("function");
  });
});
