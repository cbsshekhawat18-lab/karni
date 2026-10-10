/**
 * ResourceTable unit suite (contract "ResourceTable" + D5).
 *
 * The schema/hooks modules are owned by concurrent builders, so this suite
 * mocks them at the module boundary (their signatures are pinned by D11) and
 * drives every table behaviour deterministically. The full-stack flow runs in
 * resource-table.integration.test.tsx.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { Paginated, ResourceListParams } from "../../../hooks/types";
import { useResourceList } from "../../../hooks/useResourceList";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { AUDIT_FIELDS } from "../audit-fields";
import { ResourceTable } from "./ResourceTable";

vi.mock("../../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../../hooks/useResourceList", () => ({ useResourceList: vi.fn() }));
vi.mock("../../../hooks/useResourceMutations", () => ({ useResourceMutations: vi.fn() }));
vi.mock("../../../hooks/keys", () => ({
  karniKeys: {
    schema: () => ["karni", "$schema"],
    resource: (resource: string) => ["karni", resource],
    list: (resource: string, params?: unknown) => ["karni", resource, "list", params],
    detail: (resource: string, id: string | number) => ["karni", resource, "detail", String(id)],
  },
}));
// ResourceSelect is the form builder's component; a minimal test double keeps
// the relation-filter behaviour testable without it.
vi.mock("../ResourceSelect", async () => {
  const ReactModule = await import("react");
  return {
    ResourceSelect: (props: {
      resource: string;
      placeholder?: string;
      value: unknown;
      onChange: (value: string | number | Array<string | number> | null) => void;
    }) =>
      ReactModule.createElement("input", {
        "aria-label": props.placeholder ?? props.resource,
        value:
          typeof props.value === "string" || typeof props.value === "number"
            ? String(props.value)
            : "",
        onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
          props.onChange(event.target.value === "" ? null : event.target.value),
      }),
  };
});

const mockUseSchema = useSchema as unknown as Mock;
const mockUseResourceList = useResourceList as unknown as Mock;
const mockUseResourceMutations = useResourceMutations as unknown as Mock;

// --- fixtures ----------------------------------------------------------------

type Row = Record<string, unknown>;

function field(partial: Partial<FieldDef> & Pick<FieldDef, "name" | "kind" | "order">): FieldDef {
  const spaced = partial.name.replace(/_/g, " ");
  return {
    label: spaced.charAt(0).toUpperCase() + spaced.slice(1),
    required: false,
    readOnly: false,
    writeOnly: false,
    nullable: false,
    ...partial,
  };
}

const eventsSchema: ResourceSchema = {
  resource: "events",
  operations: {
    list: {
      path: "/api/events/",
      method: "get",
      queryParams: [
        "page",
        "page_size",
        "ordering",
        "search",
        "expand",
        "status",
        "is_public",
        "organizer",
        "venue",
        "tags",
        // BaseModel audit relations are declared filters on a real backend.
        "created_by",
        "updated_by",
      ],
      expandEnum: ["organizer", "venue", "tags"],
      hasSearch: true,
    },
  },
  // BaseModel audit fields lead the declaration order, as the backend emits.
  fields: [
    field({ name: "id", kind: "integer", readOnly: true, order: 0 }),
    field({ name: "created_at", kind: "datetime", readOnly: true, order: 1 }),
    field({ name: "updated_at", kind: "datetime", readOnly: true, order: 2 }),
    field({
      name: "created_by",
      kind: "relation",
      readOnly: true,
      nullable: true,
      relation: { resource: "users", many: false },
      order: 3,
    }),
    field({
      name: "updated_by",
      kind: "relation",
      readOnly: true,
      nullable: true,
      relation: { resource: "users", many: false },
      order: 4,
    }),
    field({ name: "title", kind: "string", required: true, maxLength: 200, order: 5 }),
    field({ name: "starts_at", kind: "datetime", order: 6 }),
    field({ name: "capacity", kind: "integer", nullable: true, order: 7 }),
    field({
      name: "status",
      kind: "enum",
      readOnly: true,
      enumValues: ["DRAFT", "PUBLISHED"],
      order: 8,
    }),
    field({ name: "is_public", kind: "boolean", order: 9 }),
    field({
      name: "organizer",
      kind: "relation",
      nullable: true,
      relation: { resource: "users", many: false },
      order: 10,
    }),
    field({
      name: "venue",
      kind: "relation",
      nullable: true,
      relation: { resource: "venues", many: false },
      order: 11,
    }),
    field({
      name: "tags",
      kind: "relation",
      relation: { resource: "tags", many: true },
      order: 12,
    }),
    field({ name: "metadata", kind: "json", order: 13 }),
    field({ name: "internal_note", kind: "string", writeOnly: true, order: 14 }),
    field({ name: "mystery", kind: "unknown", order: 15 }),
  ],
};

const DOMAIN_HEADERS = [
  "Title",
  "Starts at",
  "Capacity",
  "Status",
  "Is public",
  "Organizer",
  "Venue",
  "Tags",
];
const AUDIT_HEADERS = ["Id", "Created at", "Updated at", "Created by", "Updated by"];

const audit = {
  created_at: "2026-01-02T08:00:00Z",
  updated_at: "2026-01-03T08:00:00Z",
  created_by: 7,
  updated_by: null,
};

const page1Rows: Row[] = [
  {
    id: 1,
    ...audit,
    title: "Spring Gala",
    starts_at: "2026-05-04T18:30:00Z",
    capacity: 150,
    status: "DRAFT",
    is_public: true,
    organizer: { id: 7, name: "Ada Lovelace" },
    venue: 3,
    tags: [{ id: 1, name: "music" }, 9],
  },
  {
    id: 2,
    ...audit,
    title: "Autumn Fair",
    starts_at: "2026-09-12T10:00:00Z",
    capacity: null,
    status: "PUBLISHED",
    is_public: false,
    organizer: null,
    venue: { id: 4, name: "Main Hall" },
    tags: [],
  },
  {
    id: 3,
    ...audit,
    title: "Winter Ball",
    starts_at: "2026-12-20T20:00:00Z",
    capacity: 80,
    status: "PUBLISHED",
    is_public: true,
    organizer: null,
    venue: null,
    tags: [],
  },
];

const page2Rows: Row[] = [
  { id: 4, title: "Summer Camp", starts_at: "2027-07-01T09:00:00Z", status: "DRAFT" },
  { id: 5, title: "Book Club", starts_at: "2027-08-01T09:00:00Z", status: "DRAFT" },
];

function paginated(results: Row[], overrides?: Partial<Paginated<Row>>): Paginated<Row> {
  return { count: 60, next: "http://x/api/events/?page=2", previous: null, ...overrides, results };
}

interface ListResultShape {
  data: Paginated<Row> | undefined;
  error: unknown;
  isPending: boolean;
  isFetching: boolean;
  refetch: Mock;
}

function listResult(overrides?: Partial<ListResultShape>): ListResultShape {
  return {
    data: paginated(page1Rows),
    error: null,
    isPending: false,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function defaultListImpl(_resource: string, params?: ResourceListParams): ListResultShape {
  if (params?.page === 2) {
    return listResult({
      data: paginated(page2Rows, {
        next: "http://x/api/events/?page=3",
        previous: "http://x/api/events/?page=1",
      }),
    });
  }
  return listResult();
}

function lastListParams(): ResourceListParams | undefined {
  const call = mockUseResourceList.mock.lastCall as unknown[] | undefined;
  return call?.[1] as ResourceListParams | undefined;
}

function headerTexts(): Array<string | null> {
  return screen.getAllByRole("columnheader").map((th) => th.textContent);
}

function renderTable(ui: React.ReactElement): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mockUseSchema.mockReturnValue({ data: eventsSchema, isLoading: false, error: null });
  mockUseResourceList.mockImplementation(defaultListImpl);
  mockUseResourceMutations.mockReturnValue({
    create: { mutate: vi.fn(), isPending: false },
    update: { mutate: vi.fn(), isPending: false },
    remove: { mutate: vi.fn(), isPending: false },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// --- derived columns ---------------------------------------------------------

describe("derived columns", () => {
  it("renders domain fields in declaration order, skipping writeOnly/json/unknown/audit", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(headerTexts()).toEqual(DOMAIN_HEADERS);
  });

  it("formats cells per kind: relation labels/ids, enum labels, booleans, dates, null dash", () => {
    renderTable(<ResourceTable resource="events" />);
    const row1 = screen.getByText("Spring Gala").closest("tr");
    const row2 = screen.getByText("Autumn Fair").closest("tr");
    expect(row1).not.toBeNull();
    expect(row2).not.toBeNull();
    if (row1 === null || row2 === null) return;

    // relation: expanded object → displayLabel, raw id → <code>
    expect(within(row1).getByText("Ada Lovelace")).toBeInTheDocument();
    expect(within(row1).getByText("3", { selector: "code" })).toBeInTheDocument();
    // many-relation mixes labels and <code> ids
    expect(within(row1).getByText("music")).toBeInTheDocument();
    expect(within(row1).getByText("9", { selector: "code" })).toBeInTheDocument();
    // enum label prettified
    expect(within(row1).getByText("Draft")).toBeInTheDocument();
    expect(within(row2).getByText("Published")).toBeInTheDocument();
    // boolean → check icon with accessible text
    expect(within(row1).getByText("Yes")).toBeInTheDocument();
    expect(within(row2).getByText("No")).toBeInTheDocument();
    // datetime localized
    const expected = new Date("2026-05-04T18:30:00Z").toLocaleString();
    expect(within(row1).getByText(expected)).toBeInTheDocument();
    // nullable capacity → placeholder dash
    expect(within(row2).getAllByText("–").length).toBeGreaterThan(0);
  });

  it("getRowLabel overrides displayLabel for relation cells", () => {
    renderTable(<ResourceTable resource="events" getRowLabel={(row) => `#${String(row["id"])}`} />);
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });
});

// --- escape hatches ----------------------------------------------------------

describe("escape hatches", () => {
  it("columns: header/cell overrides, hidden, and sortable flips", () => {
    renderTable(
      <ResourceTable
        resource="events"
        columns={[
          { field: "title", header: "Name", cell: (row) => `T:${String(row["title"])}` },
          { field: "capacity", hidden: true },
          { field: "organizer", sortable: true },
          { field: "metadata" },
        ]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByText("T:Spring Gala")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Capacity" })).not.toBeInTheDocument();
    // sortable: true turns the (default-unsortable) relation header into a button
    expect(screen.getByRole("button", { name: "Organizer" })).toBeInTheDocument();
    // explicitly named json field appears even though derived columns skip json
    expect(screen.getByRole("columnheader", { name: "Metadata" })).toBeInTheDocument();
  });

  it("extraColumns are appended and columnsOverride is applied last", () => {
    renderTable(
      <ResourceTable
        resource="events"
        extraColumns={[{ id: "custom", header: "Custom", cell: () => "X" }]}
        columnsOverride={(derived) => derived.filter((column) => column.id !== "capacity")}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Custom" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Capacity" })).not.toBeInTheDocument();
  });

  it("columns naming undeclared fields become plain appended columns", () => {
    renderTable(
      <ResourceTable resource="events" columns={[{ field: "computed", header: "Computed" }]} />,
    );
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers[headers.length - 1]).toBe("Computed");
  });

  it("toolbar and footer slots render", () => {
    renderTable(
      <ResourceTable resource="events" toolbar={<button>New event</button>} footer={<p>Foot</p>} />,
    );
    expect(screen.getByRole("button", { name: "New event" })).toBeInTheDocument();
    expect(screen.getByText("Foot")).toBeInTheDocument();
  });
});

// --- audit fields (BaseModel) -----------------------------------------------

describe("audit fields (BaseModel)", () => {
  it("AUDIT_FIELDS lists the five BaseModel fields in display order", () => {
    expect(AUDIT_FIELDS).toEqual(["id", "created_at", "updated_at", "created_by", "updated_by"]);
  });

  it("hides the five audit columns by default and keeps domain declaration order", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(headerTexts()).toEqual(DOMAIN_HEADERS);
    for (const header of AUDIT_HEADERS) {
      expect(screen.queryByRole("columnheader", { name: header })).not.toBeInTheDocument();
    }
  });

  it("a columns entry re-shows one audit column after the domain columns", () => {
    const { unmount } = renderTable(
      <ResourceTable resource="events" columns={[{ field: "created_at" }]} />,
    );
    expect(headerTexts()).toEqual([...DOMAIN_HEADERS, "Created at"]);
    const row1 = screen.getByText("Spring Gala").closest("tr");
    expect(row1).not.toBeNull();
    if (row1 === null) return;
    const created = new Date(audit.created_at).toLocaleString();
    expect(within(row1).getByText(created)).toBeInTheDocument();
    unmount();

    // `hidden: false` works too; shown audit columns follow AUDIT_FIELDS order.
    renderTable(
      <ResourceTable
        resource="events"
        columns={[{ field: "updated_by" }, { field: "id", hidden: false, header: "#" }]}
      />,
    );
    expect(headerTexts()).toEqual([...DOMAIN_HEADERS, "#", "Updated by"]);
  });

  it("showAuditFields shows all five after the domain columns; hidden: true still wins", () => {
    const { unmount } = renderTable(<ResourceTable resource="events" showAuditFields />);
    expect(headerTexts()).toEqual([...DOMAIN_HEADERS, ...AUDIT_HEADERS]);
    unmount();

    renderTable(
      <ResourceTable resource="events" showAuditFields columns={[{ field: "id", hidden: true }]} />,
    );
    expect(headerTexts()).toEqual([...DOMAIN_HEADERS, ...AUDIT_HEADERS.slice(1)]);
  });

  it("orders shown audit columns by AUDIT_FIELDS, whatever the schema order", () => {
    mockUseSchema.mockReturnValue({
      data: { ...eventsSchema, fields: [...eventsSchema.fields].reverse() },
      isLoading: false,
      error: null,
    });
    renderTable(<ResourceTable resource="events" showAuditFields />);
    expect(headerTexts()).toEqual([...[...DOMAIN_HEADERS].reverse(), ...AUDIT_HEADERS]);
  });

  it("a writable field that merely shares an audit name is domain data", () => {
    mockUseSchema.mockReturnValue({
      data: {
        ...eventsSchema,
        fields: eventsSchema.fields.map((def) =>
          def.name === "id" ? { ...def, readOnly: false } : def,
        ),
      },
      isLoading: false,
      error: null,
    });
    renderTable(<ResourceTable resource="events" />);
    expect(headerTexts()).toEqual(["Id", ...DOMAIN_HEADERS]);
  });

  it("rows stay keyed by id while the Id column is hidden", async () => {
    const user = userEvent.setup();
    const archive = vi.fn();
    const onRowClick = vi.fn();
    const onEdit = vi.fn();
    const remove = vi.fn();
    mockUseResourceMutations.mockReturnValue({
      create: { mutate: vi.fn(), isPending: false },
      update: { mutate: vi.fn(), isPending: false },
      remove: { mutate: remove, isPending: false },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderTable(
      <ResourceTable
        resource="events"
        bulkActions={[{ label: "Archive", onClick: archive }]}
        onRowClick={onRowClick}
        onEdit={onEdit}
        enableDelete
        rowActions={(row) => <button>View {String(row["id"])}</button>}
      />,
    );
    expect(screen.queryByRole("columnheader", { name: "Id" })).not.toBeInTheDocument();

    // getRowId: bulk selection is keyed by String(row.id).
    const rowBoxes = screen.getAllByRole("checkbox", { name: "Select row" });
    await user.click(rowBoxes[0]);
    await user.click(rowBoxes[2]);
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(archive).toHaveBeenCalledWith(["1", "3"]);

    // Navigation and row actions receive the full row, id included.
    await user.click(screen.getByText("Winter Ball"));
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
    expect(screen.getByRole("button", { name: "View 2" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(remove).toHaveBeenCalledWith(1);
  });

  it("sorting by a hidden audit field still reaches the server", () => {
    renderTable(
      <ResourceTable resource="events" initialSorting={[{ id: "created_at", desc: true }]} />,
    );
    expect(lastListParams()?.ordering).toBe("-created_at");
    expect(screen.queryByRole("columnheader", { name: "Created at" })).not.toBeInTheDocument();
    expect(screen.getByText("Spring Gala")).toBeInTheDocument();
  });

  it("derived filters skip audit relations unless showAuditFields (domain first)", () => {
    // Default: created_by/updated_by are declared relation params, yet the
    // four slots go to domain fields.
    const { unmount } = renderTable(<ResourceTable resource="events" />);
    expect(screen.queryByLabelText("Created by")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Updated by")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    unmount();

    // A schema with room under the cap: audit candidates follow the domain ones.
    const byName = new Map(eventsSchema.fields.map((def) => [def.name, def]));
    const pick = (...names: string[]): FieldDef[] =>
      names.map((name) => byName.get(name)).filter((def): def is FieldDef => def !== undefined);
    mockUseSchema.mockReturnValue({
      data: { ...eventsSchema, fields: pick("id", "created_by", "updated_by", "title", "status") },
      isLoading: false,
      error: null,
    });
    const second = renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Created by")).not.toBeInTheDocument();
    second.unmount();

    renderTable(<ResourceTable resource="events" showAuditFields />);
    const status = screen.getByRole("combobox", { name: "Status" });
    const createdBy = screen.getByLabelText("Created by");
    expect(screen.getByLabelText("Updated by")).toBeInTheDocument();
    expect(status.compareDocumentPosition(createdBy) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("an explicit filters list may name an audit field", () => {
    renderTable(<ResourceTable resource="events" filters={["created_by"]} />);
    fireEvent.change(screen.getByLabelText("Created by"), { target: { value: "7" } });
    expect(lastListParams()?.filters).toEqual({ created_by: "7" });
  });
});

// --- sorting -----------------------------------------------------------------

describe("sorting (server mode)", () => {
  it("maps header clicks to the DRF ordering param with aria-sort feedback", async () => {
    const user = userEvent.setup();
    renderTable(<ResourceTable resource="events" />);
    const titleButton = screen.getByRole("button", { name: "Title" });

    await user.click(titleButton);
    expect(lastListParams()?.ordering).toBe("title");
    expect(screen.getByRole("columnheader", { name: "Title" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(lastListParams()?.ordering).toBe("-title");
    expect(screen.getByRole("columnheader", { name: "Title" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(lastListParams()?.ordering).toBeUndefined();
  });

  it("relation/many columns are not sortable by default; scalars are", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("button", { name: "Capacity" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Organizer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tags" })).not.toBeInTheDocument();
  });

  it("initialSorting seeds the first request's ordering", () => {
    renderTable(<ResourceTable resource="events" initialSorting={[{ id: "title", desc: true }]} />);
    expect(lastListParams()?.ordering).toBe("-title");
  });

  it("sorting resets pagination to page 1", async () => {
    const user = userEvent.setup();
    renderTable(<ResourceTable resource="events" />);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(lastListParams()?.page).toBe(2);
    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(lastListParams()?.page).toBe(1);
  });
});

// --- search + filter bar -----------------------------------------------------

describe("search box and filter bar (D5)", () => {
  it("debounces the search box into the search param and resets the page", () => {
    vi.useFakeTimers();
    renderTable(<ResourceTable resource="events" />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastListParams()?.page).toBe(2);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "gala" },
    });
    expect(lastListParams()?.search).toBeUndefined();
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(lastListParams()?.search).toBe("gala");
    expect(lastListParams()?.page).toBe(1);
  });

  it("omits the search box when the list op declares no search param", () => {
    const list = eventsSchema.operations.list;
    mockUseSchema.mockReturnValue({
      data: {
        ...eventsSchema,
        operations: { list: { ...list, hasSearch: false } },
      },
      isLoading: false,
      error: null,
    });
    renderTable(<ResourceTable resource="events" />);
    expect(screen.queryByRole("searchbox", { name: "Search" })).not.toBeInTheDocument();
  });

  it("derives (enum/boolean/relation) ∩ declared params, capped at 4", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Is public" })).toBeInTheDocument();
    expect(screen.getByLabelText("Organizer")).toBeInTheDocument();
    expect(screen.getByLabelText("Venue")).toBeInTheDocument();
    // tags is the 5th candidate — the cap drops it
    expect(screen.queryByLabelText("Tags")).not.toBeInTheDocument();
  });

  it("enum filter sends the raw member value and clears to no filter", async () => {
    const user = userEvent.setup();
    renderTable(<ResourceTable resource="events" />);
    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "Draft" }));
    expect(lastListParams()?.filters).toEqual({ status: "DRAFT" });

    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "All" }));
    expect(lastListParams()?.filters).toBeUndefined();
  });

  it("boolean filter sends a real boolean", async () => {
    const user = userEvent.setup();
    renderTable(<ResourceTable resource="events" />);
    await user.click(screen.getByRole("combobox", { name: "Is public" }));
    await user.click(await screen.findByRole("option", { name: "Yes" }));
    expect(lastListParams()?.filters).toEqual({ is_public: true });
  });

  it("relation filter passes the selected id through", () => {
    renderTable(<ResourceTable resource="events" />);
    fireEvent.change(screen.getByLabelText("Organizer"), { target: { value: "7" } });
    expect(lastListParams()?.filters).toEqual({ organizer: "7" });
  });

  it("params pins filters on every request and keeps them out of the bar", () => {
    renderTable(<ResourceTable resource="events" params={{ organizer: "7" }} />);
    expect(lastListParams()?.filters).toEqual({ organizer: "7" });
    expect(screen.queryByLabelText("Organizer")).toBeNull();
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
  });

  it("filters={false} disables the bar; filters=[...] overrides the derived set", () => {
    const { unmount } = renderTable(<ResourceTable resource="events" filters={false} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    unmount();

    renderTable(<ResourceTable resource="events" filters={["status"]} />);
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Is public" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Organizer")).not.toBeInTheDocument();
  });
});

// --- pagination --------------------------------------------------------------

describe("pagination (server mode)", () => {
  it("shows page math from DRF count and navigates with page params", async () => {
    const user = userEvent.setup();
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByText("Page 1 of 3 · 60 items")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(lastListParams()?.page).toBe(2);
    expect(screen.getByText("Page 2 of 3 · 60 items")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("pageSize is sent as page_size and drives the page count", () => {
    renderTable(<ResourceTable resource="events" pageSize={10} />);
    expect(lastListParams()?.pageSize).toBe(10);
    expect(screen.getByText("Page 1 of 6 · 60 items")).toBeInTheDocument();
  });
});

// --- D5 404 page clamp -------------------------------------------------------

describe("404 page clamp (D5)", () => {
  it("a list 404 with page > 1 decrements the page and recovers without an error panel", async () => {
    const user = userEvent.setup();
    mockUseResourceList.mockImplementation(
      (_resource: string, params?: ResourceListParams): ListResultShape => {
        if (params?.page === 2) {
          return listResult({ data: undefined, error: { status: 404, message: "Invalid page." } });
        }
        return listResult();
      },
    );
    renderTable(<ResourceTable resource="events" />);
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(lastListParams()?.page).toBe(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Spring Gala")).toBeInTheDocument();
  });

  it("a 404 on page 1 is a real error", () => {
    mockUseResourceList.mockImplementation((): ListResultShape =>
      listResult({ data: undefined, error: { status: 404, message: "Not found." } }),
    );
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Not found.");
  });
});

// --- bulk select -------------------------------------------------------------

describe("bulk select (D5)", () => {
  it("renders no checkboxes without bulkActions", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("selects rows by String(row.id) and runs bulk actions on them", async () => {
    const user = userEvent.setup();
    const archive = vi.fn();
    renderTable(
      <ResourceTable resource="events" bulkActions={[{ label: "Archive", onClick: archive }]} />,
    );
    const rowBoxes = screen.getAllByRole("checkbox", { name: "Select row" });
    await user.click(rowBoxes[0]);
    await user.click(rowBoxes[1]);
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(archive).toHaveBeenCalledWith(["1", "2"]);
  });

  it("select-all toggles the page and Clear empties the selection", async () => {
    const user = userEvent.setup();
    renderTable(
      <ResourceTable
        resource="events"
        bulkActions={[{ label: "Delete", onClick: vi.fn(), destructive: true }]}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: "Select all rows" }));
    expect(screen.getByText("3 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("3 selected")).not.toBeInTheDocument();
  });

  it("selection persists across page changes", async () => {
    const user = userEvent.setup();
    renderTable(
      <ResourceTable resource="events" bulkActions={[{ label: "Tag", onClick: vi.fn() }]} />,
    );
    await user.click(screen.getAllByRole("checkbox", { name: "Select row" })[0]);
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Summer Camp")).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });
});

// --- row interactions --------------------------------------------------------

describe("row actions and clicks", () => {
  it("onRowClick fires on cell clicks but not on the selection checkbox", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    renderTable(
      <ResourceTable
        resource="events"
        onRowClick={onRowClick}
        bulkActions={[{ label: "Archive", onClick: vi.fn() }]}
      />,
    );
    await user.click(screen.getAllByRole("checkbox", { name: "Select row" })[0]);
    expect(onRowClick).not.toHaveBeenCalled();

    await user.click(screen.getByText("Spring Gala"));
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it("rowActions render per row and onEdit enables the default edit action", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    renderTable(
      <ResourceTable
        resource="events"
        onEdit={onEdit}
        rowActions={(row) => <button>View {String(row["id"])}</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "View 1" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });

  it("enableDelete confirms, then calls useResourceMutations().remove", async () => {
    const user = userEvent.setup();
    const remove = vi.fn();
    mockUseResourceMutations.mockReturnValue({
      create: { mutate: vi.fn(), isPending: false },
      update: { mutate: vi.fn(), isPending: false },
      remove: { mutate: remove, isPending: false },
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderTable(<ResourceTable resource="events" enableDelete />);
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith(1);

    confirmSpy.mockReturnValue(false);
    await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    expect(remove).toHaveBeenCalledTimes(1);
  });
});

// --- expand (D5) -------------------------------------------------------------

describe("default expand (D5)", () => {
  it("defaults to single-relation fields ∩ the expand enum", () => {
    renderTable(<ResourceTable resource="events" />);
    expect(lastListParams()?.expand).toEqual(["organizer", "venue"]);
  });

  it("the expand prop overrides the derived default", () => {
    renderTable(<ResourceTable resource="events" expand={["venue"]} />);
    expect(lastListParams()?.expand).toEqual(["venue"]);
  });

  it("never guesses when the schema declares no expand enum", () => {
    const list = eventsSchema.operations.list;
    const bare = list === undefined ? undefined : { ...list };
    if (bare !== undefined) delete bare.expandEnum;
    mockUseSchema.mockReturnValue({
      data: { ...eventsSchema, operations: { list: bare } },
      isLoading: false,
      error: null,
    });
    renderTable(<ResourceTable resource="events" />);
    expect(lastListParams()?.expand).toBeUndefined();
  });
});

// --- states ------------------------------------------------------------------

describe("loading / error / empty states", () => {
  it("shows a skeleton while the list is pending", () => {
    mockUseResourceList.mockImplementation((): ListResultShape =>
      listResult({ data: undefined, isPending: true }),
    );
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a skeleton while the schema loads", () => {
    mockUseSchema.mockReturnValue({ data: undefined, isLoading: true, error: null });
    mockUseResourceList.mockImplementation((): ListResultShape =>
      listResult({ data: undefined, isPending: true }),
    );
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an error panel with a working retry", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    mockUseResourceList.mockImplementation((): ListResultShape =>
      listResult({ data: undefined, error: { status: 500, message: "Server exploded" }, refetch }),
    );
    renderTable(<ResourceTable resource="events" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Server exploded");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("shows a schema error panel", () => {
    mockUseSchema.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Unknown resource 'evnts'. Known resources: events."),
    });
    renderTable(<ResourceTable resource="evnts" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unknown resource");
  });

  it("renders the default EmptyState and the empty slot override", () => {
    mockUseResourceList.mockImplementation((): ListResultShape =>
      listResult({ data: paginated([], { count: 0, next: null, previous: null }) }),
    );
    const { unmount } = renderTable(<ResourceTable resource="events" />);
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
    unmount();

    renderTable(<ResourceTable resource="events" empty={<p>Custom empty</p>} />);
    expect(screen.getByText("Custom empty")).toBeInTheDocument();
  });
});
