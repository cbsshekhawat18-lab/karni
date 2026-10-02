import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Page } from "../../page/page";
import { Button } from "../../primitives/button";
import { demoHandlers, eventsOpenApi, makeDemoEvents } from "./demo-fixtures";
import { ResourceTable } from "./ResourceTable";

/**
 * Every story runs against msw handlers that simulate a Karni backend
 * (schema + /api/events/ with pagination, search, ordering and filters), so
 * the table behaves exactly as it does against DRF.
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
  args: { resource: "events" },
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

/** The contract's target usage: one line is a complete screen. */
export const TargetUsage: Story = {
  render: (args) => (
    <Page title="Events">
      <ResourceTable {...args} />
    </Page>
  ),
};

export const BulkSelect: Story = {
  args: {
    bulkActions: [
      { label: "Publish", onClick: (ids) => alert(`Publish ${ids.join(", ")}`) },
      { label: "Delete", destructive: true, onClick: (ids) => alert(`Delete ${ids.join(", ")}`) },
    ],
  },
};

function rowId(row: unknown): string {
  return String((row as Record<string, unknown>)["id"]);
}

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

export const Empty: Story = {
  parameters: { msw: { handlers: demoHandlers(makeDemoEvents(0)) } },
};

export const ErrorState: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get("*/api/schema/", () => HttpResponse.json(eventsOpenApi)),
        http.get("*/api/events/", () =>
          HttpResponse.json({ detail: "Internal server error." }, { status: 500 }),
        ),
      ],
    },
  },
};
