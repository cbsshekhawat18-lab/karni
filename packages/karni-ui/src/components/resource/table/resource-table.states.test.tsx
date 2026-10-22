/**
 * ResourceTable in every state and at real size: loading, the two empty
 * screens, errors (first load, refresh, 403, offline), slow work, partial
 * permission, delete and bulk failures, URL state, per-user density, cards
 * below the width threshold, and keyboard use.
 *
 * Like resource-table.test.tsx, the schema and list hooks are mocked at the
 * module boundary so every state is reachable deterministically.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { AuthContext, type AuthContextValue } from "../../../auth/provider";
import type { Paginated, ResourceListParams } from "../../../hooks/types";
import { useResourceList } from "../../../hooks/useResourceList";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { KarniApiError } from "../../../schema/client";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { ResourceTable, type ResourceTableProps } from "./ResourceTable";
import { memoryStateStore } from "./story-fixtures";

vi.mock("../../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../../hooks/useResourceList", () => ({ useResourceList: vi.fn() }));
vi.mock("../../../hooks/useResourceMutations", () => ({ useResourceMutations: vi.fn() }));
vi.mock("../ResourceSelect", () => ({ ResourceSelect: () => null }));

const mockUseSchema = useSchema as unknown as Mock;
const mockUseResourceList = useResourceList as unknown as Mock;
const mockUseResourceMutations = useResourceMutations as unknown as Mock;

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

const FIELDS: FieldDef[] = [
  field({ name: "id", kind: "integer", readOnly: true, order: 0 }),
  field({ name: "title", kind: "string", order: 1 }),
  field({ name: "capacity", kind: "integer", order: 2 }),
  field({ name: "status", kind: "enum", enumValues: ["DRAFT", "PUBLISHED"], order: 3 }),
  field({
    name: "organizer",
    kind: "relation",
    relation: { resource: "users", many: false },
    order: 4,
  }),
];

function schemaWith(overrides: Partial<ResourceSchema> = {}): ResourceSchema {
  return {
    resource: "events",
    operations: {
      list: {
        path: "/api/events/",
        method: "get",
        queryParams: ["page", "page_size", "ordering", "search", "status"],
        hasSearch: true,
      },
      create: { path: "/api/events/", method: "post", queryParams: [] },
      detail: { path: "/api/events/{id}/", method: "get", queryParams: [] },
      update: { path: "/api/events/{id}/", method: "patch", queryParams: [] },
      remove: { path: "/api/events/{id}/", method: "delete", queryParams: [] },
    },
    fields: FIELDS,
    ...overrides,
  };
}

const ROWS: Row[] = [
  { id: 1, title: "Spring Gala", capacity: 150, status: "DRAFT", organizer: 7 },
  { id: 2, title: "Autumn Fair", capacity: 80, status: "PUBLISHED", organizer: 8 },
  { id: 3, title: "Winter Ball", capacity: 60, status: "PUBLISHED", organizer: { id: 7 } },
];

function page(results: Row[], overrides: Partial<Paginated<Row>> = {}): Paginated<Row> {
  return { count: 60, next: "http://x/?page=2", previous: null, results, ...overrides };
}

interface ListShape {
  data: Paginated<Row> | undefined;
  error: unknown;
  isPending: boolean;
  isFetching: boolean;
  isPlaceholderData?: boolean;
  fetchStatus?: "fetching" | "paused" | "idle";
  refetch: Mock;
}

function listResult(overrides: Partial<ListShape> = {}): ListShape {
  return {
    data: page(ROWS),
    error: null,
    isPending: false,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function lastParams(): ResourceListParams | undefined {
  return (mockUseResourceList.mock.lastCall as unknown[] | undefined)?.[1] as
    ResourceListParams | undefined;
}

function identity(id: number, roles: string[]): AuthContextValue {
  return {
    user: { id, email: `user${id}@example.com`, roles },
    roles,
    status: "authenticated",
    login: () => Promise.reject(new Error("unused")),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
  };
}

function renderTable(
  props: Partial<ResourceTableProps<Row>> = {},
  auth?: AuthContextValue,
): ReturnType<typeof render> & { queryClient: QueryClient } {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const table = <ResourceTable<Row> resource="events" {...props} />;
  const result = render(
    <QueryClientProvider client={queryClient}>
      {auth === undefined ? (
        table
      ) : (
        <AuthContext.Provider value={auth}>{table}</AuthContext.Provider>
      )}
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

function liveRegion(): HTMLElement {
  const region = document.querySelector<HTMLElement>('[role="status"][aria-atomic="true"]');
  if (region === null) throw new Error("no live region");
  return region;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
  mockUseSchema.mockReturnValue({ data: schemaWith(), isLoading: false, error: null });
  mockUseResourceList.mockImplementation(() => listResult());
  mockUseResourceMutations.mockReturnValue({
    create: { mutate: vi.fn(), isPending: false },
    update: { mutate: vi.fn(), isPending: false },
    remove: { mutate: vi.fn(), isPending: false },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// loading

describe("loading", () => {
  it("outlines the real layout: the schema's column count and a full page of rows", () => {
    mockUseResourceList.mockImplementation(() => listResult({ data: undefined, isPending: true }));
    renderTable({ pageSize: 10, bulkActions: [{ label: "Archive", onClick: vi.fn() }] });
    const outline = screen.getByTestId("resource-table-skeleton");
    // checkbox + title, capacity, status, organizer (id is an audit field)
    expect(outline.querySelectorAll("thead th")).toHaveLength(5);
    expect(outline.querySelectorAll("tbody tr")).toHaveLength(10);
    // The real toolbar is up as soon as the schema is: no toolbar outline.
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("outlines the toolbar too while the schema loads", () => {
    mockUseSchema.mockReturnValue({ data: undefined, isLoading: true, error: null });
    mockUseResourceList.mockImplementation(() => listResult({ data: undefined, isPending: true }));
    renderTable();
    const outline = screen.getByTestId("resource-table-skeleton");
    expect(outline).toHaveAttribute("aria-hidden", "true");
    expect(outline.querySelectorAll("tbody tr")).toHaveLength(25);
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("says Loading only once the work is slow (500ms)", () => {
    vi.useFakeTimers();
    mockUseResourceList.mockImplementation(() =>
      listResult({ data: undefined, isPending: true, isFetching: true }),
    );
    renderTable();
    expect(liveRegion()).toHaveTextContent("");
    act(() => vi.advanceTimersByTime(500));
    expect(liveRegion()).toHaveTextContent("Loading events…");
  });
});

// empty

describe("empty: nothing yet versus nothing matches", () => {
  const empty = (): ListShape => listResult({ data: page([], { count: 0, next: null }) });

  it("no records: explains and offers the create action", async () => {
    const onCreate = vi.fn();
    mockUseResourceList.mockImplementation(empty);
    renderTable({ onCreate });
    const screenRoot = screen.getByText("No events yet").closest("[data-empty-reason]");
    expect(screenRoot).toHaveAttribute("data-empty-reason", "no-records");
    expect(screen.getByText("Create the first event and it will appear here.")).toBeInTheDocument();
    // In the empty screen and in the toolbar.
    const buttons = screen.getAllByRole("button", { name: "New event" });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[1] as HTMLElement);
    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("no records: no create action when the role may not create", () => {
    mockUseResourceList.mockImplementation(empty);
    const operations = schemaWith().operations;
    mockUseSchema.mockReturnValue({
      data: schemaWith({
        operations: {
          ...operations,
          create: {
            path: "/api/events/",
            method: "post",
            queryParams: [],
            access: { role: ["staff"] },
          },
        },
      }),
      isLoading: false,
      error: null,
    });
    renderTable({ onCreate: vi.fn(), createLabel: "Add event" }, identity(7, ["viewer"]));
    expect(screen.getByText("No events yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add event" })).not.toBeInTheDocument();
  });

  it("no results: names what narrows the list and clears search and filters", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/?events.search=zzz&events.status=PUBLISHED&keep=1");
    mockUseResourceList.mockImplementation(empty);
    renderTable({ onCreate: vi.fn(), params: { organizer: 7 } });
    expect(lastParams()).toMatchObject({
      search: "zzz",
      filters: { status: "PUBLISHED", organizer: 7 },
    });
    const root = screen.getByText("No events match").closest("[data-empty-reason]");
    expect(root).toHaveAttribute("data-empty-reason", "no-results");
    expect(
      within(screen.getByRole("list", { name: "Active filters" })).getAllByRole("listitem"),
    ).toHaveLength(2);
    expect(
      screen.getByText(/Nothing matches the search “zzz” and Status: Published/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(lastParams()?.search).toBeUndefined();
    // Pinned params stay; only the user's narrowing is cleared.
    expect(lastParams()?.filters).toEqual({ organizer: 7 });
    expect(window.location.search).toBe("?keep=1");
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("");
  });

  it("the empty prop still replaces both screens; the slots replace one each", () => {
    mockUseResourceList.mockImplementation(empty);
    const { unmount } = renderTable({ empty: <p>Custom empty</p> });
    expect(screen.getByText("Custom empty")).toBeInTheDocument();
    unmount();
    renderTable({ slots: { NoRecords: (props) => <p>Nothing in {props.resourceLabel}</p> } });
    expect(screen.getByText("Nothing in events")).toBeInTheDocument();
  });
});

// errors

describe("errors", () => {
  it("a failed refresh keeps the rows and reports inline, with a retry", async () => {
    const refetch = vi.fn();
    mockUseResourceList.mockImplementation(() =>
      listResult({ error: new KarniApiError(503, {}), refetch }),
    );
    renderTable();
    expect(screen.getByText("Spring Gala")).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("a failed page change keeps the last rows on screen", () => {
    let fail = false;
    mockUseResourceList.mockImplementation(() =>
      fail ? listResult({ data: undefined, error: new KarniApiError(500, {}) }) : listResult(),
    );
    renderTable();
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastParams()?.page).toBe(2);
    expect(screen.getByText("Spring Gala")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong on our side");
  });

  it("403 on the list: plain words, no retry, no toolbar", () => {
    mockUseResourceList.mockImplementation(() =>
      listResult({
        data: undefined,
        error: new KarniApiError(403, {
          detail: "You do not have permission to perform this action.",
        }),
      }),
    );
    renderTable();
    expect(screen.getByText("You can't view events")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/403/)).not.toBeInTheDocument();
  });

  it("the list query does not retry a 403 (nor any 4xx but 408 and 429)", () => {
    renderTable();
    const options = (mockUseResourceList.mock.lastCall as unknown[])[2] as {
      retry: (count: number, error: unknown) => boolean;
    };
    expect(options.retry(0, new KarniApiError(403, {}))).toBe(false);
    expect(options.retry(0, new KarniApiError(429, {}))).toBe(true);
    expect(options.retry(0, new KarniApiError(500, {}))).toBe(true);
  });

  it("a request that never got an answer offers a retry", () => {
    mockUseResourceList.mockImplementation(() =>
      listResult({ data: undefined, error: new TypeError("Failed to fetch") }),
    );
    renderTable();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't reach the server");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

// offline

describe("offline", () => {
  function goOffline(): void {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
  }

  it("says so over the rows it has, and reloads what failed once back online", () => {
    const refetch = vi.fn();
    mockUseResourceList.mockImplementation(() =>
      listResult({ error: new TypeError("Failed to fetch"), refetch }),
    );
    renderTable();
    goOffline();
    expect(
      screen.getByText(/You're offline\. These events may be out of date/),
    ).toBeInTheDocument();
    expect(screen.getByText("Spring Gala")).toBeInTheDocument();

    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(refetch).toHaveBeenCalledOnce();
    expect(screen.queryByText(/You're offline/)).not.toBeInTheDocument();
  });

  it("a first load paused by a lost connection says offline, not loading forever", () => {
    mockUseResourceList.mockImplementation(() =>
      listResult({ data: undefined, isPending: true, fetchStatus: "paused" }),
    );
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderTable();
    expect(screen.getByRole("alert")).toHaveTextContent("You're offline");
    expect(
      screen.getByText("The list loads by itself when you are back online."),
    ).toBeInTheDocument();
  });
});

// slow work

describe("slow work", () => {
  it("shows progress after 500ms and pagination ignores clicks while a page loads", () => {
    vi.useFakeTimers();
    mockUseResourceList.mockImplementation((_resource: string, params?: ResourceListParams) =>
      params?.page === 2 ? listResult({ isFetching: true, isPlaceholderData: true }) : listResult(),
    );
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastParams()?.page).toBe(2);
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).toBeEnabled(); // focus stays on it
    expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    // A second click while page 2 loads does not skip to page 3.
    fireEvent.click(next);
    expect(lastParams()?.page).toBe(2);
    expect(screen.queryByTestId("resource-table-progress")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByTestId("resource-table-progress")).toBeInTheDocument();
    expect(next).toHaveAttribute("aria-busy", "true");
    expect(liveRegion()).toHaveTextContent("Loading events…");
    // Sorting waits too.
    fireEvent.click(screen.getByRole("button", { name: "Title" }));
    expect(lastParams()?.ordering).toBeUndefined();
  });
});

// partial permission

describe("partial permission", () => {
  it("a field the role cannot read is absent from the columns and the filters", () => {
    mockUseSchema.mockReturnValue({
      data: schemaWith({
        fields: FIELDS.filter((def) => def.name !== "capacity" && def.name !== "status"),
      }),
      isLoading: false,
      error: null,
    });
    renderTable();
    expect(screen.queryByRole("columnheader", { name: "Capacity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Status" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Title" })).toBeInTheDocument();
  });

  it("row actions follow the schema's access rules for the signed-in user", () => {
    const operations = schemaWith().operations;
    mockUseSchema.mockReturnValue({
      data: schemaWith({
        operations: {
          ...operations,
          update: {
            ...operations.update,
            path: "/x",
            method: "patch",
            queryParams: [],
            access: { any: [{ owned: "organizer" }, { role: ["staff"] }] },
          },
          remove: { path: "/x", method: "delete", queryParams: [], access: { role: ["admin"] } },
        },
      }),
      isLoading: false,
      error: null,
    });
    const { unmount } = renderTable(
      { onEdit: vi.fn(), enableDelete: true },
      identity(7, ["viewer"]),
    );
    const rows = screen.getAllByRole("row").slice(1);
    // Ada (7) organises Spring Gala and Winter Ball, not Autumn Fair.
    expect(
      within(rows[0] as HTMLElement).getByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(
      within(rows[2] as HTMLElement).getByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    unmount();

    renderTable({ onEdit: vi.fn(), enableDelete: true }, identity(9, ["staff", "admin"]));
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(3);
  });

  it("canEdit / canDelete replace the schema's answer", () => {
    renderTable({
      onEdit: vi.fn(),
      enableDelete: true,
      canEdit: (row) => row["status"] === "DRAFT",
      canDelete: false,
    });
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("no delete action when the schema documents the item without DELETE", () => {
    const operations = { ...schemaWith().operations, remove: undefined };
    mockUseSchema.mockReturnValue({
      data: schemaWith({ operations }),
      isLoading: false,
      error: null,
    });
    renderTable({ enableDelete: true });
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });
});

// delete failures

describe("row delete failures are reported", () => {
  function failWith(error: unknown): Mock {
    const mutate = vi.fn((_id: unknown, options?: { onError?: (e: unknown) => void }) =>
      options?.onError?.(error),
    );
    mockUseResourceMutations.mockReturnValue({
      create: { mutate: vi.fn(), isPending: false },
      update: { mutate: vi.fn(), isPending: false },
      remove: { mutate, isPending: false },
    });
    return mutate;
  }

  it("a server failure keeps the dialog open with a retry", async () => {
    const user = userEvent.setup();
    const mutate = failWith(new KarniApiError(500, {}));
    renderTable({ enableDelete: true });
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0] as HTMLElement);
    const dialog = screen.getByRole("dialog", { name: "Delete “Spring Gala”?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Something went wrong on our side");
    await user.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(mutate).toHaveBeenCalledTimes(2);
  });

  it("a refusal says what the role cannot do, and offers no retry", async () => {
    const user = userEvent.setup();
    failWith(new KarniApiError(403, {}));
    renderTable({ enableDelete: true });
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0] as HTMLElement);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("You can't delete “Spring Gala”");
    expect(within(dialog).queryByRole("button", { name: "Try again" })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Focus returns to the row's Delete button.
    expect(screen.getAllByRole("button", { name: "Delete" })[0]).toHaveFocus();
  });
});

// bulk actions

describe("bulk actions", () => {
  async function selectRows(
    user: ReturnType<typeof userEvent.setup>,
    ...names: string[]
  ): Promise<void> {
    for (const name of names)
      await user.click(screen.getByRole("checkbox", { name: `Select ${name}` }));
  }

  it("a destructive action asks first, with the count and the action", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    renderTable({ bulkActions: [{ label: "Delete", destructive: true, onClick }] });
    await selectRows(user, "Spring Gala", "Winter Ball");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete 2 events?" });
    expect(onClick).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onClick).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete 2 events" }),
    );
    expect(onClick).toHaveBeenCalledWith(["1", "3"]);
  });

  it("reports a partial failure row by row: failed rows say why, the rest are deselected", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn(async (ids: string[]) => ({
      failed: ids.filter((id) => id === "3").map((id) => ({ id, reason: "Has bookings." })),
    }));
    const { queryClient } = renderTable({ bulkActions: [{ label: "Archive", onClick }] });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await selectRows(user, "Spring Gala", "Autumn Fair", "Winter Ball");
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await screen.findByText("Has bookings.");
    expect(screen.getByRole("alert")).toHaveTextContent("Archive failed for 1 of 3 events");
    const failedRow = screen.getByText("Has bookings.").closest("tr");
    expect(failedRow).toHaveAttribute("data-failed", "true");
    expect(screen.getByRole("checkbox", { name: "Select Winter Ball" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Spring Gala" })).not.toBeChecked();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalled();
  });

  it("a promise that resolves deselects everything and says it is done", async () => {
    const user = userEvent.setup();
    renderTable({ bulkActions: [{ label: "Publish", onClick: async () => undefined }] });
    await selectRows(user, "Spring Gala");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(screen.queryByText("1 selected")).not.toBeInTheDocument());
    expect(liveRegion()).toHaveTextContent("Publish: done for 1 event.");
  });

  it("a rejected action is reported in plain words and keeps the selection", async () => {
    const user = userEvent.setup();
    renderTable({
      bulkActions: [
        { label: "Publish", onClick: () => Promise.reject(new KarniApiError(403, {})) },
      ],
    });
    await selectRows(user, "Spring Gala", "Autumn Fair");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't publish 2 events");
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("shows progress while the action runs, after 500ms", async () => {
    let finish: () => void = () => undefined;
    const onClick = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    renderTable({ bulkActions: [{ label: "Publish", onClick, pendingLabel: "Publishing…" }] });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Spring Gala" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const button = screen.getByRole("button", { name: "Publish" });
    await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
    expect(button).toBeDisabled();
    await act(async () => finish());
  });
});

// URL state

describe("view state in the URL", () => {
  it("writes page, sort, size and filters under the table's namespace, and Back restores", async () => {
    const user = userEvent.setup();
    renderTable();
    const start = window.history.length;
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(new URLSearchParams(window.location.search).get("events.page")).toBe("2");
    expect(window.history.length).toBe(start + 1);
    await user.click(screen.getByRole("button", { name: "Title" }));
    // Sorting starts over from page 1, which is the default: no page key.
    expect(window.location.search).toBe("?events.ordering=title");
    expect(lastParams()).toMatchObject({ page: 1, ordering: "title" });

    act(() => {
      window.history.replaceState(null, "", "/?events.page=3&events.page_size=50");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(lastParams()).toMatchObject({ page: 3, pageSize: 50, ordering: undefined });
  });

  it("a settled search adds one history entry, refining it replaces that entry", () => {
    vi.useFakeTimers();
    renderTable();
    const start = window.history.length;
    const box = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.change(box, { target: { value: "ga" } });
    act(() => vi.advanceTimersByTime(350));
    fireEvent.change(box, { target: { value: "gala" } });
    act(() => vi.advanceTimersByTime(350));
    expect(window.location.search).toBe("?events.search=gala");
    expect(window.history.length).toBe(start + 1);
    // Back (or a shared link) puts the term back in the box.
    act(() => {
      window.history.replaceState(null, "", "/?events.search=fair");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(box).toHaveValue("fair");
  });

  it("two tables on one page keep their own keys", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResourceTable resource="events" />
        <ResourceTable resource="events" urlNamespace="archive" caption="Archived events" />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("table", { name: "Archived events" })).toBeInTheDocument();
    const nexts = screen.getAllByRole("button", { name: "Next" });
    await user.click(nexts[1] as HTMLElement);
    expect(window.location.search).toBe("?archive.page=2");
    expect(screen.getAllByText(/^Page 1 of 3 · /)).toHaveLength(1);
    expect(screen.getAllByText(/^Page 2 of 3 · /)).toHaveLength(1);
  });

  it("syncUrl={false} keeps the URL untouched; pinned params are never URL state", async () => {
    const user = userEvent.setup();
    const { unmount } = renderTable({ syncUrl: false });
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(lastParams()?.page).toBe(2);
    expect(window.location.search).toBe("");
    unmount();

    renderTable({ params: { organizer: 7 } });
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(window.location.search).toBe("?events.page=2");
  });

  it("a stateStore adapter (a router) receives the writes and drives the view", async () => {
    const user = userEvent.setup();
    const store = memoryStateStore({ "events.ordering": "-capacity" });
    renderTable({ stateStore: store });
    expect(lastParams()?.ordering).toBe("-capacity");
    expect(screen.getByRole("columnheader", { name: "Capacity" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(store.values).toEqual({ "events.ordering": "-capacity", "events.page": "2" });
    expect(window.location.search).toBe("");
    act(() => store.write({ "events.page": null }, { push: true }));
    expect(lastParams()?.page).toBe(1);
  });

  it("a page size outside the offered sizes falls back to the default", () => {
    window.history.replaceState(null, "", "/?events.page_size=100000");
    renderTable();
    expect(lastParams()?.pageSize).toBe(25);
  });
});

// real size: pagination

describe("pagination at real size", () => {
  it("offers page sizes, first/last and jump to page; changing size starts over", async () => {
    const user = userEvent.setup();
    mockUseResourceList.mockImplementation((_r: string, params?: ResourceListParams) =>
      listResult({
        data: page(ROWS, {
          count: 100_000,
          next: "n",
          previous: (params?.page ?? 1) > 1 ? "p" : null,
        }),
      }),
    );
    renderTable();
    expect(screen.getByText("Page 1 of 4,000 · 100,000 items")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Last page" }));
    expect(lastParams()?.page).toBe(4000);
    await user.click(screen.getByRole("button", { name: "First page" }));
    expect(lastParams()?.page).toBe(1);
    await user.type(screen.getByLabelText("Go to page (1 to 4000)"), "123{Enter}");
    expect(lastParams()?.page).toBe(123);
    await user.click(screen.getByRole("combobox", { name: "Rows per page" }));
    await user.click(await screen.findByRole("option", { name: "100" }));
    expect(lastParams()).toMatchObject({ page: 1, pageSize: 100 });
    expect(window.location.search).toBe("?events.page_size=100");
    expect(liveRegion()).toHaveTextContent("Showing page 1 of 1,000.");
  });
});

// density

describe("row density, remembered per user", () => {
  it("toggles from the View menu and is kept under the user's own key", async () => {
    const user = userEvent.setup();
    const { unmount } = renderTable({}, identity(7, []));
    const firstCell = (): HTMLElement => screen.getAllByRole("cell")[0] as HTMLElement;
    expect(firstCell()).toHaveClass("h-12");
    await user.click(screen.getByRole("button", { name: "View options" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Compact rows" }));
    expect(firstCell()).toHaveClass("h-9");
    expect(window.localStorage.getItem("karni:table:density:7")).toBe("compact");
    unmount();

    // Ada again: compact. Someone else: their own (default) choice.
    const again = renderTable({}, identity(7, []));
    expect(firstCell()).toHaveClass("h-9");
    again.unmount();
    renderTable({}, identity(8, []));
    expect(firstCell()).toHaveClass("h-12");
  });

  it("hides a column from the View menu, remembered for the table", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(screen.getByRole("button", { name: "View options" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Capacity" }));
    expect(screen.queryByRole("columnheader", { name: "Capacity" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem("karni:table:columns:events:anonymous")).toBe(
      '["capacity"]',
    );
  });

  it("a controlled density wins and reports changes", async () => {
    const user = userEvent.setup();
    const onDensityChange = vi.fn();
    renderTable({ density: "compact", onDensityChange });
    expect(screen.getAllByRole("cell")[0]).toHaveClass("h-9");
    await user.click(screen.getByRole("button", { name: "View options" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Compact rows" }));
    expect(onDensityChange).toHaveBeenCalledWith("comfortable");
    expect(window.localStorage.getItem("karni:table:density:anonymous")).toBeNull();
  });
});

// cards below the container breakpoint

describe("cards in a narrow container", () => {
  function stubWidth(width: number): void {
    class FixedWidthObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe(target: Element): void {
        this.callback(
          [{ target, contentRect: { width } } as unknown as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      }
      unobserve(): void {}
      disconnect(): void {}
    }
    vi.stubGlobal("ResizeObserver", FixedWidthObserver);
  }

  it("renders each row as a card with its fields, selection and actions", async () => {
    stubWidth(400);
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const onRowClick = vi.fn();
    renderTable({ onEdit, onRowClick, bulkActions: [{ label: "Archive", onClick: vi.fn() }] });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = within(screen.getByRole("list", { name: "Events" })).getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    const first = cards[0] as HTMLElement;
    expect(within(first).getByText("Capacity")).toBeInTheDocument();
    expect(within(first).getByText("150")).toBeInTheDocument();
    await user.click(within(first).getByRole("checkbox", { name: "Select Spring Gala" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.click(within(first).getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    await user.click(within(first).getByRole("button", { name: "Spring Gala" }));
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    // Sorting still works without headers.
    await user.click(screen.getByRole("combobox", { name: "Sort by" }));
    await user.click(await screen.findByRole("option", { name: "Capacity, descending" }));
    expect(lastParams()?.ordering).toBe("-capacity");
  });

  it("stays a table above the breakpoint, and cardBreakpoint={0} never switches", () => {
    stubWidth(900);
    const { unmount } = renderTable();
    expect(screen.getByRole("table", { name: "Events" })).toBeInTheDocument();
    unmount();
    stubWidth(300);
    renderTable({ cardBreakpoint: 0 });
    expect(screen.getByRole("table", { name: "Events" })).toBeInTheDocument();
  });

  it("a sort chosen from the keyboard keeps focus on the Sort by choice while the page loads", async () => {
    stubWidth(400);
    const user = userEvent.setup();
    // The sorted page is on its way: the table is busy until it lands.
    mockUseResourceList.mockImplementation((_resource: string, params?: ResourceListParams) =>
      params?.ordering === "-capacity"
        ? listResult({ isFetching: true, isPlaceholderData: true })
        : listResult(),
    );
    renderTable();
    const sort = screen.getByRole("combobox", { name: "Sort by" });
    sort.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("listbox");
    // From "Sort: default order" (the current choice): Title ↑↓, then Capacity ↑↓.
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("option", { name: "Capacity, descending" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(lastParams()?.ordering).toBe("-capacity");
    // The list says it is busy; the choice stays enabled, so it keeps the keyboard.
    expect(screen.getByRole("list", { name: "Events" })).toHaveAttribute("aria-busy", "true");
    expect(sort).toBeEnabled();
    await waitFor(() => expect(sort).toHaveFocus());
  });

  it("after a bulk action ran, focus lands on the list, not on <body>", async () => {
    stubWidth(400);
    const user = userEvent.setup();
    renderTable({
      bulkActions: [{ label: "Delete", destructive: true, onClick: async () => undefined }],
    });
    screen.getByRole("checkbox", { name: "Select Spring Gala" }).focus();
    await user.keyboard(" ");
    screen.getByRole("button", { name: "Delete" }).focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Delete 1 event?" });
    within(dialog).getByRole("button", { name: "Delete 1 event" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The toolbar that opened the dialog is gone with the selection: the list takes over.
    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Events" });
    expect(list).toHaveAttribute("tabindex", "-1");
    expect(list).toHaveFocus();
  });

  it("a row deleted from its card hands focus to the list", async () => {
    stubWidth(400);
    const user = userEvent.setup();
    mockUseResourceMutations.mockReturnValue({
      create: { mutate: vi.fn(), isPending: false },
      update: { mutate: vi.fn(), isPending: false },
      remove: {
        mutate: vi.fn((_id: unknown, options?: { onSuccess?: () => void }) =>
          options?.onSuccess?.(),
        ),
        isPending: false,
      },
    });
    renderTable({ enableDelete: true });
    (screen.getAllByRole("button", { name: "Delete" })[0] as HTMLElement).focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Delete “Spring Gala”?" });
    within(dialog).getByRole("button", { name: "Delete" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(liveRegion()).toHaveTextContent("Deleted “Spring Gala”.");
    expect(screen.getByRole("list", { name: "Events" })).toHaveFocus();
  });
});

// keyboard and screen readers

describe("keyboard and assistive technology", () => {
  it("names the table, labels each checkbox after its row, and says what all means", () => {
    renderTable({ bulkActions: [{ label: "Archive", onClick: vi.fn() }] });
    expect(screen.getByRole("table", { name: "Events" })).toHaveAttribute("aria-rowcount", "61");
    expect(
      screen.getByRole("checkbox", { name: "Select all events on this page" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Autumn Fair" })).toBeInTheDocument();
  });

  it("opens a row, sorts, selects and pages from the keyboard alone", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    renderTable({ onRowClick, bulkActions: [{ label: "Archive", onClick: vi.fn() }] });

    // The scroll region is focusable (keyboard scrolling), then the header controls.
    await user.tab(); // search
    const title = screen.getByRole("button", { name: "Title" });
    title.focus();
    await user.keyboard("{Enter}");
    expect(lastParams()?.ordering).toBe("title");
    expect(liveRegion()).toHaveTextContent("Sorted by Title, ascending.");

    const open = screen.getByRole("button", { name: "Spring Gala" });
    open.focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledTimes(1);
    await user.keyboard(" ");
    expect(onRowClick).toHaveBeenCalledTimes(2);

    screen.getByRole("checkbox", { name: "Select Autumn Fair" }).focus();
    await user.keyboard(" ");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(liveRegion()).toHaveTextContent("1 selected.");

    const next = screen.getByRole("button", { name: "Next" });
    next.focus();
    await user.keyboard("{Enter}");
    expect(lastParams()?.page).toBe(2);
    await waitFor(() => expect(liveRegion()).toHaveTextContent("Showing page 2 of 3."));
  });

  it("the scroll region is reachable by Tab, so wide tables scroll from the keyboard", async () => {
    const user = userEvent.setup();
    renderTable({ filters: false, exportFormats: false, viewOptions: false });
    await user.tab(); // the search box
    await user.tab();
    expect(screen.getByRole("region", { name: "Events" })).toHaveFocus();
  });
});
