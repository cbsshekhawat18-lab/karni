import type { UseQueryResult } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import type { Paginated, ResourceItemParams, ResourceListParams } from "../../../hooks/types";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceList } from "../../../hooks/useResourceList";
import { displayLabel } from "../displayLabel";
import { venueById, venues } from "../form/fixtures";
import { ResourceSelect } from "./ResourceSelect";

vi.mock("../../../hooks/useResourceList", () => ({ useResourceList: vi.fn() }));
vi.mock("../../../hooks/useResourceItem", () => ({ useResourceItem: vi.fn() }));
vi.mock("../displayLabel", () => ({ displayLabel: vi.fn() }));

type Row = Record<string, unknown>;

const mockUseResourceList = useResourceList as unknown as Mock<
  (
    resource: string,
    params?: ResourceListParams,
    options?: { enabled?: boolean },
  ) => UseQueryResult<Paginated<Row>>
>;
const mockUseResourceItem = useResourceItem as unknown as Mock<
  (
    resource: string,
    id: string | number,
    params?: ResourceItemParams,
    options?: { enabled?: boolean; retry?: boolean },
  ) => UseQueryResult<Row>
>;
const mockDisplayLabel = displayLabel as unknown as Mock<(obj: Row) => string>;

function queryResult<T>(
  data: T | undefined,
  overrides: { isLoading?: boolean; error?: unknown } = {},
): UseQueryResult<T> {
  return {
    data,
    isLoading: overrides.isLoading ?? false,
    error: overrides.error ?? null,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<T>;
}

function lastListParams(): ResourceListParams | undefined {
  const calls = mockUseResourceList.mock.calls;
  return calls[calls.length - 1]?.[1];
}

beforeEach(() => {
  mockDisplayLabel.mockImplementation((obj: Row) => String(obj["name"] ?? obj["id"]));
  mockUseResourceList.mockImplementation((_resource, params, options) => {
    if (options?.enabled === false) return queryResult<Paginated<Row>>(undefined);
    const search = (params?.search ?? "").toLowerCase();
    const results = venues.filter((venue) => venue.name.toLowerCase().includes(search));
    return queryResult<Paginated<Row>>({
      count: results.length,
      next: null,
      previous: null,
      results: [...results],
    });
  });
  mockUseResourceItem.mockImplementation((_resource, id, _params, options) => {
    if (options?.enabled === false) return queryResult<Row>(undefined);
    const venue = venueById[String(id)];
    return venue !== undefined
      ? queryResult<Row>(venue)
      : queryResult<Row>(undefined, { error: new Error("Not found") });
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as { jest?: unknown }).jest;
});

/**
 * @testing-library's act/waitFor wrappers only advance a faked clock when they
 * detect Jest fake timers through the `jest` global (jestFakeTimersAreEnabled
 * in @testing-library/dom); without it every awaited user-event call deadlocks
 * on a setTimeout(0) the fake clock never fires. Alias the vitest clock under
 * the name they probe for while fake timers are active (removed in afterEach).
 */
function installFakeTimerBridge(): void {
  (globalThis as { jest?: { advanceTimersByTime: (ms: number) => void } }).jest = {
    advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms),
  };
}

describe("ResourceSelect ARIA combobox pattern (D8)", () => {
  it("wires combobox → listbox with activedescendant and keeps focus in the input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ResourceSelect resource="venues" value={null} onChange={onChange} aria-label="Venue" />,
    );

    const input = screen.getByRole("combobox", { name: "Venue" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    await user.click(input);
    const listbox = await screen.findByRole("listbox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", listbox.id);

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(venues.length);
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);
    // D8: focus never leaves the input while the popover is open.
    expect(input).toHaveFocus();
  });

  it("moves the active option with arrows and selects with Enter, focus staying put", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ResourceSelect resource="venues" value={null} onChange={onChange} aria-label="Venue" />,
    );

    const input = screen.getByRole("combobox", { name: "Venue" });
    await user.click(input);
    await screen.findByRole("listbox");
    const options = screen.getAllByRole("option");

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[1]?.id);
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);

    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith(venues[1]?.id);
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(input).toHaveFocus();
  });

  it("closes on Escape without clearing the selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ResourceSelect resource="venues" value={7} onChange={onChange} aria-label="Venue" />);

    const input = screen.getByRole("combobox", { name: "Venue" });
    await user.click(input);
    await screen.findByRole("listbox");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();
    expect(input).toHaveFocus();
  });

  it("closes when interacting outside", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <button type="button">outside</button>
        <ResourceSelect resource="venues" value={null} onChange={vi.fn()} aria-label="Venue" />
      </div>,
    );

    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    await screen.findByRole("listbox");
    await user.click(screen.getByRole("button", { name: "outside" }));
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
  });
});

describe("ResourceSelect search (D8)", () => {
  it("debounces typing into a single ?search= request after 300ms", async () => {
    vi.useFakeTimers();
    installFakeTimerBridge();
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    render(<ResourceSelect resource="venues" value={null} onChange={vi.fn()} aria-label="Venue" />);

    const input = screen.getByRole("combobox", { name: "Venue" });
    await user.click(input);
    await user.keyboard("ber");

    // Still inside the 300ms window: no keystroke leaked into the params.
    expect(lastListParams()?.search).toBeUndefined();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(lastListParams()?.search).toBeUndefined();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(lastListParams()?.search).toBe("ber");
    expect(lastListParams()?.page).toBe(1);
  });

  it("selects an option by click and shows its label in the closed input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <ResourceSelect resource="venues" value={null} onChange={onChange} aria-label="Venue" />,
    );

    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    await user.click(await screen.findByRole("option", { name: "Berlin Arena" }));
    expect(onChange).toHaveBeenCalledWith(7);

    rerender(<ResourceSelect resource="venues" value={7} onChange={onChange} aria-label="Venue" />);
    expect(screen.getByRole("combobox", { name: "Venue" })).toHaveValue("Berlin Arena");
  });

  it("shows an empty state when the page has no results", async () => {
    mockUseResourceList.mockImplementation(() =>
      queryResult<Paginated<Row>>({ count: 0, next: null, previous: null, results: [] }),
    );
    const user = userEvent.setup();
    render(<ResourceSelect resource="venues" value={null} onChange={vi.fn()} aria-label="Venue" />);

    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    expect(await screen.findByText("No results")).toBeInTheDocument();
  });

  it("forwards extra filter params with the list request", async () => {
    const user = userEvent.setup();
    render(
      <ResourceSelect
        resource="venues"
        value={null}
        onChange={vi.fn()}
        filter={{ city: "Berlin" }}
        aria-label="Venue"
      />,
    );
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    await screen.findByRole("listbox");
    expect(lastListParams()?.filters).toEqual({ city: "Berlin" });
  });
});

describe("ResourceSelect selected-id resolution (D8)", () => {
  it("resolves a preselected id through the detail endpoint", async () => {
    render(<ResourceSelect resource="venues" value={7} onChange={vi.fn()} aria-label="Venue" />);

    expect(mockUseResourceItem).toHaveBeenCalledWith(
      "venues",
      7,
      undefined,
      expect.objectContaining({ enabled: true }),
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Venue" })).toHaveValue("Berlin Arena"),
    );
  });

  it("falls back to the raw id when resolution fails", async () => {
    render(<ResourceSelect resource="venues" value={999} onChange={vi.fn()} aria-label="Venue" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Venue" })).toHaveValue("999"));
  });
});

describe("ResourceSelect clear affordance + multiple (D8)", () => {
  it("renders a clear button that emits null", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ResourceSelect resource="venues" value={7} onChange={onChange} aria-label="Venue" />);

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("hides the clear affordance when clearable is false", () => {
    render(
      <ResourceSelect
        resource="venues"
        value={7}
        onChange={vi.fn()}
        clearable={false}
        aria-label="Venue"
      />,
    );
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
  });

  it("multiple: renders chips, removes via chip buttons and Backspace, toggles options", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ResourceSelect
        resource="venues"
        multiple
        value={[1, 2]}
        onChange={onChange}
        aria-label="Venues"
      />,
    );

    await screen.findByText("Aurora Hall");
    expect(screen.getByText("Basalt Rooms")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove Aurora Hall" }));
    expect(onChange).toHaveBeenLastCalledWith([2]);

    const input = screen.getByRole("combobox", { name: "Venues" });
    await user.click(input);
    await user.keyboard("{Backspace}");
    expect(onChange).toHaveBeenLastCalledWith([1]);

    // Toggling an already-selected option removes it; a new one is appended.
    const selectedOption = await screen.findByRole("option", { name: "Aurora Hall" });
    expect(selectedOption).toHaveAttribute("aria-selected", "true");
    await user.click(selectedOption);
    expect(onChange).toHaveBeenLastCalledWith([2]);
  });

  it("disabled: never opens and disables the input", async () => {
    const user = userEvent.setup();
    render(
      <ResourceSelect
        resource="venues"
        value={null}
        onChange={vi.fn()}
        disabled
        aria-label="Venue"
      />,
    );
    const input = screen.getByRole("combobox", { name: "Venue" });
    expect(input).toBeDisabled();
    await user.click(input).catch(() => undefined);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
