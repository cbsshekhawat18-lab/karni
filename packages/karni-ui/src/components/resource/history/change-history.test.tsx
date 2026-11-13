import { QueryClient, QueryClientProvider, type UseQueryResult } from "@tanstack/react-query";
import { render as renderUi, screen, within } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import {
  useChangeHistory,
  type ChangeHistoryPage,
  type ChangeHistoryParams,
} from "../../../hooks/useChangeHistory";
import { KarniApiError } from "../../../schema/client";
import type { FieldDef } from "../../../schema/types";
import { ChangeHistory, defaultChangeHistorySlots, historyValueText } from "./ChangeHistory";

vi.mock("../../../hooks/useChangeHistory", () => ({ useChangeHistory: vi.fn() }));

const mockUseChangeHistory = useChangeHistory as unknown as Mock<
  (
    resource: string,
    id: string | number,
    params?: ChangeHistoryParams,
    options?: object,
  ) => UseQueryResult<ChangeHistoryPage>
>;

/** The data hook is mocked; the query client only serves the retry policy. */
function render(ui: React.ReactElement) {
  return renderUi(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

function result(partial: Partial<UseQueryResult<ChangeHistoryPage>>) {
  return {
    isPending: false,
    error: null,
    data: undefined,
    ...partial,
  } as UseQueryResult<ChangeHistoryPage>;
}

const page: ChangeHistoryPage = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: 2,
      timestamp: "2026-10-19T10:00:00Z",
      actor: { id: 1, email: "ada@example.com" },
      action: "update",
      diff: { amount: ["10.00", "12.50"], note: ["[redacted]", "[redacted]"] },
      fields_changed: ["amount", "note"],
    },
    {
      id: 1,
      timestamp: "2026-10-19T09:00:00Z",
      actor: null,
      action: "create",
      diff: { amount: [null, "10.00"], currency: [null, "EUR"] },
      fields_changed: ["amount", "currency"],
    },
  ],
};

describe("ChangeHistory", () => {
  it("renders each entry with its action, actor and field diffs, newest first", () => {
    mockUseChangeHistory.mockReturnValue(result({ data: page }));
    render(<ChangeHistory resource="prices" id={7} />);
    expect(mockUseChangeHistory).toHaveBeenCalledWith("prices", 7, undefined, expect.anything());
    const [newest, oldest] = screen.getAllByRole("listitem");
    if (newest === undefined || oldest === undefined) throw new Error("expected two entries");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(within(newest).getByText("Changed")).toBeInTheDocument();
    expect(within(newest).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(newest).getByText("12.50")).toBeInTheDocument();
    expect(within(newest).getAllByText("redacted")).toHaveLength(2);
    expect(within(oldest).getByText("Created")).toBeInTheDocument();
    expect(within(oldest).getByText("EUR")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
  });

  it("passes the page size through and shows the empty state", () => {
    mockUseChangeHistory.mockReturnValue(result({ data: { ...page, count: 0, results: [] } }));
    render(<ChangeHistory resource="prices" id="abc" pageSize={5} empty="Nothing yet" />);
    expect(mockUseChangeHistory).toHaveBeenCalledWith(
      "prices",
      "abc",
      { pageSize: 5 },
      expect.anything(),
    );
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });

  it("shows a skeleton while loading and the error when the request fails", () => {
    mockUseChangeHistory.mockReturnValue(result({ isPending: true }));
    const { unmount } = render(<ChangeHistory resource="prices" id={1} />);
    expect(screen.getByTestId("change-history-loading")).toBeInTheDocument();
    unmount();
    // The backend's 404 for a model that keeps no history: plain words, plus its explanation.
    mockUseChangeHistory.mockReturnValue(
      result({
        error: new KarniApiError(404, {
          detail: "No history is kept for Venue: opt in with class Karni: audit = True.",
        }),
      }),
    );
    render(<ChangeHistory resource="venues" id={1} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't find the history of this venue");
    expect(screen.getByRole("alert")).toHaveTextContent("No history is kept");
  });
});

function field(partial: Partial<FieldDef> & { name: string; label: string }): FieldDef {
  return {
    kind: "string",
    required: false,
    readOnly: true,
    writeOnly: false,
    nullable: false,
    order: 0,
    ...partial,
  };
}

describe("ChangeHistory in words", () => {
  const fields: FieldDef[] = [
    field({
      name: "status",
      label: "Status",
      kind: "enum",
      enumValues: ["paid", "part_refunded"],
      enumLabels: { paid: "Paid", part_refunded: "Part refunded" },
      transitions: { paid: ["part_refunded"], part_refunded: [] },
    }),
    field({
      name: "amount_refunded",
      label: "Amount refunded",
      kind: "string",
      money: { currencyField: "currency" },
    }),
  ];
  const Entry = defaultChangeHistorySlots.Entry;

  it("says a move of a state in words, with the states' labels", () => {
    render(
      <Entry
        entry={{
          id: 3,
          timestamp: "2026-10-19T10:00:00Z",
          actor: null,
          action: "transition",
          diff: { status: ["paid", "part_refunded"] },
          fields_changed: ["status"],
        }}
        fields={fields}
      />,
    );
    expect(screen.getByText("Status changed from Paid to Part refunded")).toBeInTheDocument();
    expect(screen.queryByText("Transitioned")).toBeNull();
    expect(screen.queryByText("part_refunded")).toBeNull();
  });

  it("names each field by its label and shows money in the record's currency", () => {
    render(
      <Entry
        entry={{
          id: 4,
          timestamp: "2026-10-19T10:00:00Z",
          actor: { id: 1, email: "ada@example.com" },
          action: "update",
          diff: { amount_refunded: ["0.0000", "52.0000"] },
          fields_changed: ["amount_refunded"],
        }}
        fields={fields}
        record={{ currency: "USD" }}
      />,
    );
    expect(screen.getByText("Changed")).toBeInTheDocument();
    expect(screen.getByText("Amount refunded")).toBeInTheDocument();
    expect(screen.queryByText("amount_refunded")).toBeNull();
    expect(screen.getByText("$52.00", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("52.0000")).toBeNull();
  });

  it("humanizes a field the schema does not know, and money without a currency", () => {
    expect(historyValueText(undefined, "x")).toBe("x");
    expect(historyValueText(fields[1], "52.0000")).toBe("52.00");
    expect(historyValueText(fields[0], "part_refunded")).toBe("Part refunded");
    expect(historyValueText(field({ name: "on", label: "On", kind: "boolean" }), true)).toBe("Yes");
  });
});
