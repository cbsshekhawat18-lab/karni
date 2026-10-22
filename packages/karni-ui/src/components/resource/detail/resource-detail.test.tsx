import { QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { render as renderUi, screen, within } from "@testing-library/react";
import * as React from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import type { ResourceItemParams } from "../../../hooks/types";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { useResourceItem } from "../../../hooks/useResourceItem";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import type { UseSchemaResult } from "../../../schema/useSchema";
import { AUDIT_FIELDS } from "../audit-fields";
import { displayLabel } from "../displayLabel";
import { eventFields, eventRecord, eventSchema } from "../form/fixtures";
import { ResourceDetail } from "./ResourceDetail";

vi.mock("../../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../../hooks/useResourceItem", () => ({ useResourceItem: vi.fn() }));
vi.mock("../displayLabel", () => ({ displayLabel: vi.fn() }));

type Row = Record<string, unknown>;

const mockUseSchema = useSchema as unknown as Mock<(resource: string) => UseSchemaResult>;
const mockUseResourceItem = useResourceItem as unknown as Mock<
  (
    resource: string,
    id: string | number,
    params?: ResourceItemParams,
    options?: { enabled?: boolean },
  ) => UseQueryResult<Row>
>;
const mockDisplayLabel = displayLabel as unknown as Mock<(obj: Row) => string>;

/** The data hooks are mocked; the provider serves the delete mutation and the schema retry. */
function render(ui: React.ReactElement) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient();
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

/** Detail view data: venue expanded (in expand), tags left as raw pks. */
const detailRecord: Row = {
  ...eventRecord,
  capacity: null,
  venue: { id: 7, name: "Berlin Arena", city: "Berlin" },
};

/**
 * The event schema as a real BaseModel resource emits it: the five audit
 * fields lead the declaration order (created_by/updated_by are relations).
 */
function auditField(
  name: string,
  label: string,
  kind: FieldDef["kind"],
  order: number,
  relation?: FieldDef["relation"],
): FieldDef {
  return {
    name,
    label,
    kind,
    order,
    required: false,
    readOnly: true,
    writeOnly: false,
    nullable: relation !== undefined,
    ...(relation !== undefined ? { relation } : {}),
  };
}

const auditedSchema: ResourceSchema = {
  ...eventSchema,
  fields: [
    auditField("id", "Id", "integer", 0),
    auditField("created_at", "Created at", "datetime", 1),
    auditField("updated_at", "Updated at", "datetime", 2),
    auditField("created_by", "Created by", "relation", 3, { resource: "users", many: false }),
    auditField("updated_by", "Updated by", "relation", 4, { resource: "users", many: false }),
    ...eventFields
      .filter((def) => !AUDIT_FIELDS.includes(def.name))
      .map((def, index) => ({ ...def, order: 5 + index })),
  ],
};

const auditedRecord: Row = {
  ...detailRecord,
  updated_at: "2026-02-10T12:00:00+00:00",
  created_by: 3,
  updated_by: null,
};

const DOMAIN_LABELS = [
  "Title",
  "Description",
  "Starts at",
  "Capacity",
  "Status",
  "Is public",
  "Venue",
  "Tags",
  "Image",
  "Metadata",
];

function termsOf(list: Element): Array<string | null> {
  return Array.from(list.querySelectorAll("dt")).map((term) => term.textContent);
}

function queryResult<T>(
  data: T | undefined,
  overrides: { isLoading?: boolean; error?: unknown; refetch?: Mock } = {},
): UseQueryResult<T> {
  return {
    data,
    isLoading: overrides.isLoading ?? false,
    error: overrides.error ?? null,
    refetch: overrides.refetch ?? vi.fn(),
  } as unknown as UseQueryResult<T>;
}

beforeEach(() => {
  mockUseSchema.mockReturnValue({ data: eventSchema, isLoading: false, error: undefined });
  mockUseResourceItem.mockReturnValue(queryResult<Row>(detailRecord));
  mockDisplayLabel.mockImplementation((obj: Row) => String(obj["name"] ?? obj["id"]));
});

describe("ResourceDetail", () => {
  it("renders a definition list with per-kind formatting", () => {
    const { container } = render(<ResourceDetail resource="events" id={1} />);

    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Launch party")).toBeInTheDocument();
    // enum → humanized label
    expect(screen.getByText("Published")).toBeInTheDocument();
    // boolean → Yes/No
    expect(screen.getByText("Yes")).toBeInTheDocument();
    // datetime → localized
    expect(
      screen.getByText(new Date(String(eventRecord["starts_at"])).toLocaleString()),
    ).toBeInTheDocument();
    // null → the shared empty value: a dash, read as "empty"
    expect(screen.getAllByText("–").length).toBeGreaterThan(0);
    expect(screen.getAllByText("empty").length).toBeGreaterThan(0);
    // expanded relation → displayLabel
    expect(screen.getByText("Berlin Arena")).toBeInTheDocument();
    // unexpanded many relation → raw ids in <code>
    const codes = Array.from(container.querySelectorAll("code")).map((code) => code.textContent);
    expect(codes).toEqual(expect.arrayContaining(["1", "2"]));
    // file → link named by basename
    const link = screen.getByRole("link", { name: "launch.png" });
    expect(link).toHaveAttribute("href", String(eventRecord["image"]));
    // json → pretty-printed block
    expect(screen.getByText(/"theme": "neon"/)).toBeInTheDocument();
    // writeOnly and unknown fields are skipped
    expect(screen.queryByText("Internal note")).not.toBeInTheDocument();
    expect(screen.queryByText("Mystery")).not.toBeInTheDocument();
  });

  it("renders domain fields first and the audit fields last in a muted Record group", () => {
    mockUseSchema.mockReturnValue({ data: auditedSchema, isLoading: false, error: undefined });
    mockUseResourceItem.mockReturnValue(queryResult<Row>(auditedRecord));
    const { container } = render(<ResourceDetail resource="events" id={1} />);

    // The leading list holds only domain fields, in schema order.
    const [domainList] = Array.from(container.querySelectorAll("dl"));
    expect(domainList).toBeDefined();
    if (domainList === undefined) return;
    expect(termsOf(domainList)).toEqual(DOMAIN_LABELS);

    // The audit fields trail it, labelled "Record", in AUDIT_FIELDS order.
    const record = screen.getByRole("region", { name: "Record" });
    expect(termsOf(record)).toEqual(["Id", "Created at", "Updated at", "Created by", "Updated by"]);
    expect(domainList.compareDocumentPosition(record) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );

    // Values render with the stock formatting...
    expect(
      within(record).getByText(new Date(String(auditedRecord["updated_at"])).toLocaleString()),
    ).toBeInTheDocument();
    expect(within(record).getByText("3", { selector: "code" })).toBeInTheDocument();
    // ...but visually muted (labels and values), unlike the domain values.
    for (const value of Array.from(record.querySelectorAll("dd"))) {
      expect(value).toHaveClass("text-muted-foreground");
    }
    for (const value of Array.from(domainList.querySelectorAll("dd"))) {
      expect(value).toHaveClass("text-foreground");
    }
  });

  it("keeps audit fields overridable through the fields map", () => {
    mockUseSchema.mockReturnValue({ data: auditedSchema, isLoading: false, error: undefined });
    mockUseResourceItem.mockReturnValue(queryResult<Row>(auditedRecord));
    render(
      <ResourceDetail
        resource="events"
        id={1}
        fields={{
          id: { hidden: true },
          created_at: { label: "Added" },
          created_by: {
            render: (value) => <span data-testid="author">user {String(value)}</span>,
          },
        }}
      />,
    );
    const record = screen.getByRole("region", { name: "Record" });
    expect(termsOf(record)).toEqual(["Added", "Updated at", "Created by", "Updated by"]);
    expect(within(record).getByTestId("author")).toHaveTextContent("user 3");
  });

  it("omits the Record group when no audit field is visible", () => {
    mockUseSchema.mockReturnValue({ data: auditedSchema, isLoading: false, error: undefined });
    mockUseResourceItem.mockReturnValue(queryResult<Row>(auditedRecord));
    render(
      <ResourceDetail
        resource="events"
        id={1}
        fields={Object.fromEntries(AUDIT_FIELDS.map((name) => [name, { hidden: true }]))}
      />,
    );
    expect(screen.queryByRole("region", { name: "Record" })).not.toBeInTheDocument();
    expect(screen.getByText("Launch party")).toBeInTheDocument();
  });

  it("forwards the expand param to useResourceItem", () => {
    render(<ResourceDetail resource="events" id={1} expand={["venue"]} />);
    expect(mockUseResourceItem).toHaveBeenCalledWith(
      "events",
      1,
      { expand: ["venue"] },
      expect.objectContaining({ enabled: true }),
    );
  });

  it("applies field overrides: hidden, label and render", () => {
    render(
      <ResourceDetail
        resource="events"
        id={1}
        fields={{
          metadata: { hidden: true },
          title: { label: "Name" },
          status: {
            render: (value, item) => (
              <span data-testid="custom-status">
                {String(value)}@{String(item["id"])}
              </span>
            ),
          },
        }}
      />,
    );

    expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.queryByText("Title")).not.toBeInTheDocument();
    expect(screen.getByTestId("custom-status")).toHaveTextContent("published@1");
  });

  it("renders the title/actions header and appends sections", () => {
    render(
      <ResourceDetail
        resource="events"
        id={1}
        title="Launch party"
        actions={<button type="button">Edit</button>}
        sections={[<p key="s1">Related things</p>]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Launch party" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByText("Related things")).toBeInTheDocument();
  });

  it("shows a skeleton while loading", () => {
    mockUseResourceItem.mockReturnValue(queryResult<Row>(undefined, { isLoading: true }));
    render(<ResourceDetail resource="events" id={1} />);
    expect(screen.getByRole("status", { name: "Loading details" })).toBeInTheDocument();
  });

  it("shows an error panel whose retry button refetches", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn(() => Promise.resolve());
    mockUseResourceItem.mockReturnValue(
      queryResult<Row>(undefined, { error: new Error("Boom"), refetch }),
    );
    render(<ResourceDetail resource="events" id={1} />);

    // Plain words from describeError (an unexpected error), never the raw message.
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't view this event");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
