/**
 * A protected file field (`FieldDef.protected`, from `x-karni-storage`) is shown
 * through the component a storage package registered, in ResourceDetail and in
 * a ResourceTable cell. Any other file field stays a plain link.
 */
import { QueryClient, QueryClientProvider, type UseQueryResult } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { useResourceItem } from "../../hooks/useResourceItem";
import { useResourceList } from "../../hooks/useResourceList";
import type { ResourceSchema } from "../../schema/types";
import { useSchema, type UseSchemaResult } from "../../schema/useSchema";
import { eventSchema } from "./form/fixtures";
import { ResourceDetail } from "./detail/ResourceDetail";
import { registerProtectedFileLink, type ProtectedFileLinkRenderProps } from "./protected-file";
import { ResourceTable } from "./table/ResourceTable";

vi.mock("../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../hooks/useResourceItem", () => ({ useResourceItem: vi.fn() }));
vi.mock("../../hooks/useResourceList", () => ({ useResourceList: vi.fn() }));
vi.mock("../../hooks/useResourceMutations", () => ({
  useResourceMutations: () => ({
    create: { mutate: vi.fn(), isPending: false },
    update: { mutate: vi.fn(), isPending: false },
    remove: { mutate: vi.fn(), isPending: false },
  }),
}));

const mockUseSchema = useSchema as unknown as Mock<(resource: string) => UseSchemaResult>;
const mockItem = useResourceItem as unknown as Mock<() => UseQueryResult<Record<string, unknown>>>;
const mockList = useResourceList as unknown as Mock;

const PATH = "http://127.0.0.1:8790/api/events/1/files/image/";

function Signed({ href, className }: ProtectedFileLinkRenderProps): React.ReactElement {
  return (
    <button type="button" data-href={href} className={className}>
      Open signed
    </button>
  );
}

function schemaWith(protectedFile: boolean): ResourceSchema {
  return {
    ...eventSchema,
    fields: eventSchema.fields.map((field) =>
      field.name === "image" && protectedFile ? { ...field, protected: true as const } : field,
    ),
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  mockItem.mockReturnValue({
    data: { id: 1, title: "Gig", image: PATH },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<Record<string, unknown>>);
  mockList.mockReturnValue({
    data: { count: 1, next: null, previous: null, results: [{ id: 1, title: "Gig", image: PATH }] },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  });
});

afterEach(() => registerProtectedFileLink(null));

describe("protected file fields", () => {
  it("ResourceDetail renders one with the registered component, from the schema", () => {
    registerProtectedFileLink(Signed);
    mockUseSchema.mockReturnValue({ data: schemaWith(true), isLoading: false, error: undefined });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResourceDetail resource="events" id={1} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Open signed" })).toHaveAttribute("data-href", PATH);
  });

  it("ResourceTable renders one in its cell", () => {
    registerProtectedFileLink(Signed);
    mockUseSchema.mockReturnValue({ data: schemaWith(true), isLoading: false, error: undefined });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResourceTable resource="events" columns={[{ field: "title" }, { field: "image" }]} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Open signed" })).toHaveAttribute("data-href", PATH);
  });

  it("keeps a plain link for a file field that is not protected, or with nothing registered", () => {
    registerProtectedFileLink(Signed);
    mockUseSchema.mockReturnValue({ data: schemaWith(false), isLoading: false, error: undefined });
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient()}>
        <ResourceDetail resource="events" id={1} />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button", { name: "Open signed" })).toBeNull();
    expect(screen.getByRole("link", { name: "image" })).toHaveAttribute("href", PATH);
    unmount();
    registerProtectedFileLink(null);
    mockUseSchema.mockReturnValue({ data: schemaWith(true), isLoading: false, error: undefined });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResourceDetail resource="events" id={1} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: "image" })).toHaveAttribute("href", PATH);
  });
});
