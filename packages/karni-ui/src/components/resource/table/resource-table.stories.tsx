import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { delay, http, HttpResponse } from "msw";
import * as React from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { AuthContext, type AuthContextValue } from "../../../auth/provider";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Page } from "../../page/page";
import { Button } from "../../primitives/button";
import { demoHandlers, eventsOpenApi, makeDemoEvents } from "./demo-fixtures";
import { ResourceTable } from "./ResourceTable";
import { largeHandlers, memoryStateStore, partialOpenApi, wideHandlers } from "./story-fixtures";

/**
 * Every story runs against msw handlers that simulate a Karni backend
 * (schema + /api/events/ with pagination, search, ordering and filters), so
 * the table behaves exactly as it does against DRF. One story per state:
 * loading, slow, empty (two kinds), error, failed refresh, forbidden,
 * offline, partial permission, and the real-size cases (50 columns,
 * 100,000 rows, bulk confirm and partial failure). Below 640px of container
 * width every story renders cards.
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    // The baseUrl carries the API prefix: hooks request `/<resource>/` under it.
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      {props.children}
    </KarniProvider>
  );
}

const meta = {
  title: "Resource/ResourceTable",
  component: ResourceTable,
  tags: ["autodocs"],
  // Stories keep their view out of the address bar (a shared preview).
  args: { resource: "events", syncUrl: false },
  parameters: { msw: { handlers: demoHandlers() } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof ResourceTable>;

export default meta;
type Story = StoryObj<typeof meta>;

const schemaHandler = http.get("*/api/schema/", () => HttpResponse.json(eventsOpenApi));

function rowId(row: unknown): string {
  return String((row as Record<string, unknown>)["id"]);
}

/** The contract's target usage: one line is a complete screen. */
export const TargetUsage: Story = {
  render: (args) => (
    <Page title="Events">
      <ResourceTable {...args} />
    </Page>
  ),
};

// states

/** The first load: the real layout in outline, a full page of rows. */
export const Loading: Story = {
  args: { bulkActions: [{ label: "Publish", onClick: () => undefined }], onEdit: () => undefined },
  parameters: {
    msw: {
      handlers: [schemaHandler, http.get("*/api/events/", () => delay("infinite"))],
    },
  },
};

/**
 * A first load that takes 1.5s: the outline holds the table's exact box
 * (toolbar, header, a full page of rows, pagination), so nothing moves when
 * the rows arrive.
 */
export const SlowFirstLoad: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get("*/api/events/", async () => {
          await delay(1500);
        }),
        ...demoHandlers(),
      ],
    },
  },
};

/** A page change that takes long: rows dim, a bar runs, the clicked button shows progress. */
export const SlowPageChange: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get("*/api/events/", async ({ request }) => {
          const page = new URL(request.url).searchParams.get("page");
          if (page !== null && page !== "1") await delay("infinite");
        }),
        ...demoHandlers(),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Next" }, { timeout: 5000 }));
  },
};

/** Nothing has been created yet: says so, and offers the create action. */
export const NoRecords: Story = {
  args: { onCreate: () => alert("Create an event") },
  parameters: { msw: { handlers: demoHandlers(makeDemoEvents(0)) } },
};

/** Rows exist but none match: names what filters, offers "Clear filters". */
export const NoResults: Story = {
  args: {
    syncUrl: true,
    stateStore: memoryStateStore({ "events.search": "zzz", "events.status": "PUBLISHED" }),
  },
};

export const ErrorState: Story = {
  parameters: {
    msw: {
      handlers: [
        schemaHandler,
        http.get("*/api/events/", () =>
          HttpResponse.json({ detail: "Internal server error." }, { status: 500 }),
        ),
      ],
    },
  },
};

/** A refresh fails after rows were shown: the rows stay, a line says so. */
export const RefreshFailed: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get("*/api/events/", ({ request }) => {
          const page = new URL(request.url).searchParams.get("page");
          if (page !== null && page !== "1") {
            return HttpResponse.json({}, { status: 503 });
          }
          return undefined;
        }),
        ...demoHandlers(),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Next" }, { timeout: 5000 }));
    await canvas.findByText("Something went wrong on our side", undefined, { timeout: 12000 });
  },
};

/** The role may not view the list (403): plain words, no retry. */
export const Forbidden: Story = {
  parameters: {
    msw: {
      handlers: [
        schemaHandler,
        http.get("*/api/events/", () =>
          HttpResponse.json(
            { detail: "You do not have permission to perform this action." },
            { status: 403 },
          ),
        ),
      ],
    },
  },
};

/** The request never got an answer (offline, or the server unreachable). */
export const NetworkError: Story = {
  parameters: {
    msw: {
      handlers: [schemaHandler, http.get("*/api/events/", () => HttpResponse.error())],
    },
  },
};

const viewer: AuthContextValue = {
  user: { id: 1, email: "ada@example.com", roles: ["viewer"] },
  roles: ["viewer"],
  status: "authenticated",
  login: () => Promise.reject(new Error("story")),
  logout: () => Promise.resolve(),
  refresh: () => Promise.resolve(),
  adoptTokens: () => Promise.resolve(),
};

/**
 * Signed in as Ada, a "viewer": the schema hides `capacity` from her role
 * (no column), she may edit only the events she organises (Edit shows on
 * those rows only), and only admins may delete (no Delete anywhere).
 */
export const PartialPermission: Story = {
  args: {
    onEdit: (row) => alert(`Edit ${rowId(row)}`),
    enableDelete: true,
    onCreate: () => undefined,
  },
  parameters: {
    msw: {
      handlers: [
        http.get("*/api/schema/", () => HttpResponse.json(partialOpenApi)),
        ...demoHandlers(),
      ],
    },
  },
  decorators: [
    (Story) => (
      <AuthContext.Provider value={viewer}>
        <Story />
      </AuthContext.Provider>
    ),
  ],
};

// real size

/** 50 columns: the table scrolls inside its box, the first column stays, the header sticks. */
export const FiftyColumns: Story = {
  args: { resource: "metrics", bulkActions: [{ label: "Export", onClick: () => undefined }] },
  parameters: { msw: { handlers: wideHandlers() } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const region = await canvas.findByRole("region", { name: "Metrics" }, { timeout: 5000 });
    region.scrollLeft = 480;
    // Whole rows: a row half under the sticky header leaves a sliver of its
    // checkbox within 24px of the header's, which axe counts as a target.
    const row = region.querySelector("tbody tr")?.getBoundingClientRect().height ?? 48;
    region.scrollTop = 3 * row;
    region.dispatchEvent(new Event("scroll"));
  },
};

/** 100,000 rows: one page at a time, page size, first/last, jump to a page. */
export const HundredThousandRows: Story = {
  args: { pageSize: 50 },
  parameters: { msw: { handlers: largeHandlers() } },
};

/** Compact rows (the View menu remembers the choice per user). */
export const Compact: Story = {
  args: { defaultDensity: "compact", onEdit: () => undefined },
};

const archiveSome = async (
  ids: string[],
): Promise<{ failed: Array<{ id: string; reason: string }> }> => {
  await new Promise((resolve) => setTimeout(resolve, 300));
  return {
    failed: ids.slice(0, 2).map((id) => ({ id, reason: "Has bookings. Cancel them first." })),
  };
};

/** A destructive bulk action asks first: the count and the action, in a dialog. */
export const BulkConfirm: Story = {
  args: {
    bulkActions: [
      { label: "Publish", onClick: () => undefined },
      { label: "Delete", destructive: true, onClick: () => undefined },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const boxes = await canvas.findAllByRole("checkbox", undefined, { timeout: 5000 });
    for (const box of boxes.slice(1, 4)) await userEvent.click(box);
    await userEvent.click(canvas.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(document.body).getByRole("dialog")).toBeTruthy());
  },
};

/** A bulk action that fails for some rows: those rows say why and stay selected. */
export const BulkPartialFailure: Story = {
  args: {
    bulkActions: [{ label: "Archive", onClick: archiveSome }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const boxes = await canvas.findAllByRole("checkbox", undefined, { timeout: 5000 });
    for (const box of boxes.slice(1, 5)) await userEvent.click(box);
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    await canvas.findByText(/Archive failed for 2 of 4 events/, undefined, { timeout: 5000 });
  },
};

/** A row delete the server refuses: the dialog says why, in plain words. */
export const DeleteFailed: Story = {
  args: { enableDelete: true },
  parameters: {
    msw: {
      handlers: [
        http.delete("*/api/events/:id/", () => HttpResponse.json({}, { status: 500 })),
        ...demoHandlers(),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const buttons = await canvas.findAllByRole("button", { name: "Delete" }, { timeout: 5000 });
    const first = buttons[0];
    if (first !== undefined) await userEvent.click(first);
    const dialog = await within(document.body).findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await within(dialog).findByText("Something went wrong on our side", undefined, {
      timeout: 5000,
    });
  },
};

// composition

export const BulkSelect: Story = {
  args: {
    bulkActions: [
      { label: "Publish", onClick: (ids) => alert(`Publish ${ids.join(", ")}`) },
      { label: "Delete", destructive: true, onClick: (ids) => alert(`Delete ${ids.join(", ")}`) },
    ],
  },
};

export const RowActions: Story = {
  args: {
    onEdit: (row) => alert(`Edit ${rowId(row)}`),
    rowActions: (row) => (
      <Button variant="ghost" size="sm" onClick={() => alert(`Duplicate ${rowId(row)}`)}>
        Duplicate
      </Button>
    ),
    onRowClick: (row) => alert(`Open ${rowId(row)}`),
  },
};

export const CustomColumns: Story = {
  args: {
    columns: [
      { field: "title", header: "Event" },
      { field: "capacity", hidden: true },
      {
        field: "starts_at",
        cell: (row) =>
          new Date(String((row as Record<string, unknown>)["starts_at"])).toDateString(),
      },
    ],
    extraColumns: [
      {
        id: "spots",
        header: "Spots",
        cell: ({ row }) => {
          const capacity = (row.original as Record<string, unknown>)["capacity"];
          return typeof capacity === "number" ? `${capacity} seats` : "Unlimited";
        },
      },
    ],
    filters: ["status"],
  },
};

/**
 * Audit columns (AUDIT_FIELDS) are hidden by default. `showAuditFields`
 * appends them after the domain columns. To show just one, name it in
 * `columns`, e.g. `columns={[{ field: "created_at" }]}`.
 */
export const AuditFields: Story = {
  args: {
    showAuditFields: true,
    // Keeps the created_by relation filter (users) out of this demo backend.
    filters: ["status", "is_public"],
  },
};
