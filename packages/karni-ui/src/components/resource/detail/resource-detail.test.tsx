import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import type { ResourceItemParams } from "../../../hooks/types";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useSchema } from "../../../schema/useSchema";
import type { UseSchemaResult } from "../../../schema/useSchema";
import { displayLabel } from "../displayLabel";
import { eventRecord, eventSchema } from "../form/fixtures";
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

/** Detail view data: venue expanded (in expand), tags left as raw pks. */
const detailRecord: Row = {
  ...eventRecord,
  capacity: null,
  venue: { id: 7, name: "Berlin Arena", city: "Berlin" },
};

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
    // null → em dash
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
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

  it("forwards the expand param to useResourceItem", () => {
    render(<ResourceDetail resource="events" id={1} expand={["venue"]} />);
    expect(mockUseResourceItem).toHaveBeenCalledWith("events", 1, { expand: ["venue"] });
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

    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
