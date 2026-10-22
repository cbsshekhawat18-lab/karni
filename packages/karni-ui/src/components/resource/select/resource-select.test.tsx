/**
 * ResourceSelect against a simulated backend (msw): the real client, schema
 * parsing, paging and resolution. The suite was on mocked hooks while the
 * picker fetched one page; it now pages through the API's `next` links, so
 * it runs against the network layer instead.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { FilterBar } from "../table/FilterBar";
import { ResourceSelect, type ResourceSelectProps } from "./ResourceSelect";
import { venueBackend, type VenueBackend, type VenueBackendOptions } from "./venue-backend";

type Value = ResourceSelectProps["value"];

function mount(ui: React.ReactElement, options: VenueBackendOptions = {}): VenueBackend {
  const backend = venueBackend(options);
  server.use(...backend.handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
  return backend;
}

/** A controlled select, as an app renders it. */
function Picker(
  props: Partial<Omit<ResourceSelectProps, "value">> & {
    initial?: Value;
    onValue?: (value: Value) => void;
  },
): React.ReactElement {
  const { initial = null, onValue, ...rest } = props;
  const [value, setValue] = React.useState<Value>(initial);
  return (
    <ResourceSelect
      resource="venues"
      aria-label="Venue"
      value={value}
      onChange={(next) => {
        setValue(next);
        onValue?.(next);
      }}
      {...rest}
    />
  );
}

async function openList(user: ReturnType<typeof userEvent.setup>, name = "Venue") {
  const input = screen.getByRole("combobox", { name });
  await user.click(input);
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getAllByRole("option").length).toBeGreaterThan(0));
  return { input, listbox };
}

function liveText(): string {
  const regions = screen.getAllByRole("status");
  return regions.map((region) => region.textContent ?? "").join(" ");
}

describe("ResourceSelect ARIA combobox pattern (D8)", () => {
  it("wires combobox → listbox with activedescendant and keeps focus in the input", async () => {
    const user = userEvent.setup();
    mount(<Picker />);

    const input = screen.getByRole("combobox", { name: "Venue" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    const { listbox } = await openList(user);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    expect(listbox).toHaveAccessibleName("Venue");

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(12);
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);
    expect(options[0]).toHaveAttribute("aria-posinset", "1");
    expect(options[0]).toHaveAttribute("aria-setsize", "12");
    // D8: focus never leaves the input while the popover is open.
    expect(input).toHaveFocus();
  });

  it("moves the active option with arrows and selects with Enter, focus staying put", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker onValue={onValue} />);

    const { input } = await openList(user);
    const options = screen.getAllByRole("option");

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[1]?.id);
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);

    await user.keyboard("{ArrowDown}{Enter}");
    expect(onValue).toHaveBeenCalledWith(2);
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(input).toHaveFocus();
    expect(input).toHaveValue("Basalt Rooms");
  });

  it("Home, End and PageDown move through the list", async () => {
    const user = userEvent.setup();
    mount(<Picker />);
    const { input } = await openList(user);
    const options = screen.getAllByRole("option");

    await user.keyboard("{End}");
    expect(input).toHaveAttribute("aria-activedescendant", options[11]?.id);
    await user.keyboard("{Home}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);
    await user.keyboard("{PageDown}");
    const active = input.getAttribute("aria-activedescendant");
    expect(active).not.toBe(options[0]?.id);
    expect(document.getElementById(active ?? "")).toHaveAttribute("role", "option");
  });

  it("closes on Escape without clearing the selection", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker initial={7} onValue={onValue} />);

    const { input } = await openList(user);
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(onValue).not.toHaveBeenCalled();
    expect(input).toHaveFocus();
  });

  it("closes when interacting outside, and reports the blur once focus leaves", async () => {
    const user = userEvent.setup();
    const onBlur = vi.fn();
    mount(
      <div>
        <button type="button">outside</button>
        <Picker onBlur={onBlur} />
      </div>,
    );

    await openList(user);
    // Moving through the list is not leaving the field.
    await user.keyboard("{ArrowDown}");
    expect(onBlur).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "outside" }));
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("is labelled by a <label for>, and passes the field's aria state to the input", () => {
    mount(
      <>
        <label htmlFor="venue-field">Where</label>
        <p id="venue-help">Pick the room.</p>
        <ResourceSelect
          id="venue-field"
          resource="venues"
          value={null}
          onChange={vi.fn()}
          aria-describedby="venue-help"
          aria-invalid
          aria-required
        />
      </>,
    );
    const input = screen.getByRole("combobox", { name: "Where" });
    expect(input).toHaveAccessibleDescription("Pick the room.");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input.closest("[data-invalid]")).toHaveAttribute("data-invalid", "true");
  });

  it("ResourceTable's filter bar names its relation pickers (a placeholder is not a label)", async () => {
    const user = userEvent.setup();
    mount(
      <FilterBar
        searchEnabled={false}
        searchValue=""
        onSearchChange={vi.fn()}
        filterFields={[
          {
            name: "venue",
            label: "Venue",
            kind: "relation",
            required: false,
            readOnly: false,
            writeOnly: false,
            nullable: true,
            order: 0,
            relation: { resource: "venues", many: false },
          },
        ]}
        values={{ venue: 7 }}
        onFilterChange={vi.fn()}
      />,
    );
    const input = screen.getByRole("combobox", { name: "Venue" });
    await waitFor(() => expect(input).toHaveValue("Berlin Arena"));
    await user.click(input);
    expect(await screen.findByRole("listbox", { name: "Venue" })).toBeInTheDocument();
  });

  it("forwards its ref to the input (a form focuses it after a failed submit)", () => {
    const ref = React.createRef<HTMLInputElement>();
    mount(
      <ResourceSelect
        ref={ref}
        resource="venues"
        value={null}
        onChange={vi.fn()}
        aria-label="Venue"
      />,
    );
    expect(ref.current).toBe(screen.getByRole("combobox", { name: "Venue" }));
  });
});

describe("ResourceSelect search (D8)", () => {
  it("debounces typing into a single ?search= request", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker />);

    await openList(user);
    await user.keyboard("ber");

    await waitFor(() =>
      expect(backend.listRequests().some((url) => url.searchParams.get("search") === "ber")).toBe(
        true,
      ),
    );
    const terms = backend.listRequests().map((url) => url.searchParams.get("search"));
    expect(terms).not.toContain("b");
    expect(terms).not.toContain("be");
    const searched = backend.listRequests().find((url) => url.searchParams.get("search") === "ber");
    expect(searched?.searchParams.get("page")).toBe("1");
    // Name or city contains "ber": Ember Yard, Fjord Stage (Bergen), Berlin
    // Arena, Granite Works (Aberdeen).
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(4));
    expect(screen.getByRole("option", { name: "Berlin Arena" })).toBeInTheDocument();
  });

  it("keeps the previous results visible while a new search loads, and says it is searching", async () => {
    const user = userEvent.setup();
    mount(<Picker searchDebounceMs={0} />, { searchDelay: "infinite" });

    await openList(user);
    await user.keyboard("har");

    await waitFor(() => expect(liveText()).toContain("Searching…"));
    // The unfiltered page stays on screen instead of a blank list.
    expect(screen.getAllByRole("option")).toHaveLength(12);
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-busy", "true");
  });

  it("selects an option by click and shows its label in the closed input", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker onValue={onValue} />);

    await openList(user);
    await user.click(screen.getByRole("option", { name: "Berlin Arena" }));
    expect(onValue).toHaveBeenCalledWith(7);
    expect(screen.getByRole("combobox", { name: "Venue" })).toHaveValue("Berlin Arena");
  });

  it("tells 'nothing exists yet' apart from 'nothing matches'", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { count: 0 });
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    expect(await screen.findByText("No venues yet", { selector: "p" })).toBeVisible();
    expect(liveText()).toContain("No venues yet");
  });

  it("says what the search found nothing for", async () => {
    const user = userEvent.setup();
    mount(<Picker searchDebounceMs={0} />);
    await openList(user);
    await user.keyboard("zzz");
    expect(await screen.findByText("No venues match “zzz”", { selector: "p" })).toBeVisible();
  });

  it("forwards extra filter params with the list request", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker filter={{ city: "Berlin" }} />);
    await openList(user);
    expect(backend.listRequests()[0]?.searchParams.get("city")).toBe("Berlin");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Berlin Arena",
    ]);
  });

  it("without search_fields: never sends ?search=, narrows the loaded rows and says so", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker searchDebounceMs={0} />, { search: false });

    await openList(user);
    await user.keyboard("har");

    await waitFor(() =>
      expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
        "Harbor House",
      ]),
    );
    expect(backend.listRequests().every((url) => !url.searchParams.has("search"))).toBe(true);
    expect(liveText()).toContain("Search isn't available for venues: 1 of the 12 loaded match");

    await user.keyboard("zzz");
    expect(
      await screen.findByText("None of the 12 loaded venues match “harzzz”", { selector: "p" }),
    ).toBeVisible();
  });
});

describe("ResourceSelect paging through 10,000 rows", () => {
  it("loads one page, says how many exist, and loads the next page on scroll — never all", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker />, { count: 10_000 });

    await openList(user);
    expect(screen.getAllByRole("option")).toHaveLength(50);
    expect(backend.listRequests()).toHaveLength(1);
    const total = (10_000).toLocaleString();
    expect(liveText()).toContain(`Showing 50 of ${total}. Type to narrow.`);
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-setsize", "10000");

    const scroller = screen.getByRole("listbox").parentElement as HTMLElement;
    fireEvent.scroll(scroller, { target: { scrollTop: 50 * 32 - 256 } });
    await waitFor(() => expect(backend.listRequests()).toHaveLength(2));
    expect(backend.listRequests()[1]?.searchParams.get("page")).toBe("2");
    await waitFor(() => expect(liveText()).toContain(`Showing 100 of ${total}`));
    expect(backend.listRequests().length).toBeLessThan(3);
  });

  it("offers an explicit 'Load more' too", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker />, { count: 120 });
    await openList(user);
    await user.click(screen.getByRole("button", { name: "Load more venues" }));
    await waitFor(() => expect(backend.listRequests()).toHaveLength(2));
    await waitFor(() => expect(liveText()).toContain("Showing 100 of 120"));
  });

  it("keyboard: End reaches the last loaded row and fetches more; ArrowDown continues into the new page", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker />, { count: 10_000 });
    const { input } = await openList(user);

    await user.keyboard("{End}");
    const last = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(last).toHaveTextContent("Venue 00050");
    await waitFor(() => expect(backend.listRequests()).toHaveLength(2));
    await waitFor(() => expect(liveText()).toContain("Showing 100"));

    await user.keyboard("{ArrowDown}");
    const next = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(next).toHaveTextContent("Venue 00051");
    expect(next).toHaveAttribute("aria-posinset", "51");
  });

  it("keyboard: ArrowDown on the last loaded row waits for the next page, then moves into it", async () => {
    const user = userEvent.setup();
    mount(<Picker pageSize={20} />, { count: 45 });
    const { input } = await openList(user);
    await user.keyboard("{End}");
    await waitFor(() => expect(screen.getAllByRole("option").length).toBe(40));
    // End fetched page 2 already; End again goes to row 40 and fetches page 3.
    await user.keyboard("{End}");
    await waitFor(() => expect(screen.getAllByRole("option").length).toBe(45));
    await user.keyboard("{End}{ArrowDown}");
    // The last row of the last page wraps to the first.
    expect(input).toHaveAttribute("aria-activedescendant", screen.getAllByRole("option")[0]?.id);
  });

  it("renders only the rows in view once the list is long, keeping the active row in the DOM", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker pageSize={100} />, { count: 10_000 });
    const { input } = await openList(user);
    await user.keyboard("{End}");
    await waitFor(() => expect(backend.listRequests()).toHaveLength(2));
    await waitFor(() => expect(liveText()).toContain("Showing 200"));

    // 200 rows loaded, far fewer in the DOM.
    expect(screen.getAllByRole("option").length).toBeLessThan(40);
    await user.keyboard("{End}");
    const active = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(active).toHaveTextContent("Venue 00200");
    expect(active).toHaveAttribute("aria-posinset", "200");
    await user.keyboard("{Home}");
    expect(
      document.getElementById(input.getAttribute("aria-activedescendant") ?? ""),
    ).toHaveTextContent("Aurora Hall");
  });

  it("a failed next page says so and can be tried again", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { count: 120, nextPageFailure: 500 });
    await openList(user);
    await user.click(screen.getByRole("button", { name: "Load more venues" }));
    expect(await screen.findByText("Couldn't load more venues.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    // The rows already loaded stay.
    expect(screen.getAllByRole("option")).toHaveLength(50);
  });
});

describe("ResourceSelect states", () => {
  it("loading: placeholder rows, announced", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { listDelay: "infinite" });
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    await waitFor(() => expect(liveText()).toContain("Loading venues…"));
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("combobox", { name: "Venue" })).not.toHaveAttribute(
      "aria-activedescendant",
    );
  });

  it("server error: plain words and a retry that works", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { listFailure: 500 });
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).not.toHaveTextContent("500");

    server.use(...venueBackend().handlers);
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(12));
  });

  it("403: says the role can't view the resource, without a retry", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { listFailure: 403 });
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You can't view venues");
    expect(within(alert).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offline: says the server could not be reached, with a retry", async () => {
    const user = userEvent.setup();
    mount(<Picker />, { listFailure: "offline" });
    await user.click(screen.getByRole("combobox", { name: "Venue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't reach the server");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("ResourceSelect selected-id resolution (D8)", () => {
  it("without an id-list filter: one detail request per id, in parallel, never a raw id", async () => {
    const backend = mount(<Picker multiple initial={[7, 2]} aria-label="Venues" />, {
      detailDelay: 30,
    });
    const input = screen.getByRole("combobox", { name: "Venues" });
    // While loading, no raw id is shown as a label.
    expect(input.parentElement).not.toHaveTextContent(/\b7\b/);
    expect(await screen.findByText("Berlin Arena")).toBeInTheDocument();
    expect(screen.getByText("Basalt Rooms")).toBeInTheDocument();
    const details = backend.requests.filter((url) => /\/venues\/\d+\/$/.test(url.pathname));
    expect(details.map((url) => url.pathname).sort()).toEqual(["/api/venues/2/", "/api/venues/7/"]);
  });

  it("with ?id__in= documented: ONE request for every preselected id", async () => {
    const backend = mount(<Picker multiple initial={[7, 2, 11]} aria-label="Venues" />, {
      idsFilter: true,
    });
    expect(await screen.findByText("Juniper Court")).toBeInTheDocument();
    expect(screen.getByText("Berlin Arena")).toBeInTheDocument();
    const lists = backend.listRequests();
    expect(lists).toHaveLength(1);
    expect(lists[0]?.searchParams.get("id__in")).toBe("7,2,11");
    expect(backend.requests.some((url) => /\/venues\/\d+\/$/.test(url.pathname))).toBe(false);
  });

  it("a single preselected id shows its label; the input says it is loading meanwhile", async () => {
    mount(<Picker initial={7} />, { detailDelay: 50 });
    const input = screen.getByRole("combobox", { name: "Venue" });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "Loading venue…");
    await waitFor(() => expect(input).toHaveValue("Berlin Arena"));
  });

  it("an id that cannot be loaded says so instead of showing the bare id", async () => {
    mount(<Picker initial={999} />);
    const input = screen.getByRole("combobox", { name: "Venue" });
    await waitFor(() => expect(input).toHaveValue("Couldn't load venue 999"));
  });

  it("a chip for an id that cannot be loaded says so, and can still be removed", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker multiple initial={[7, 999]} onValue={onValue} aria-label="Venues" />);
    expect(await screen.findByText("Couldn't load venue 999")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Couldn't load venue 999" }));
    expect(onValue).toHaveBeenLastCalledWith([7]);
  });
});

describe("ResourceSelect clear affordance + multiple (D8)", () => {
  it("renders a clear button that emits null", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker initial={7} onValue={onValue} />);
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onValue).toHaveBeenCalledWith(null);
  });

  it("hides the clear affordance when clearable is false", () => {
    mount(<Picker initial={7} clearable={false} />);
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
  });

  it("multiple: renders chips, removes via chip buttons and Backspace, toggles options", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker multiple initial={[1, 2]} onValue={onValue} aria-label="Venues" />);

    await screen.findByText("Aurora Hall");
    expect(screen.getByText("Basalt Rooms")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove Aurora Hall" }));
    expect(onValue).toHaveBeenLastCalledWith([2]);

    const input = screen.getByRole("combobox", { name: "Venues" });
    await user.click(input);
    await user.keyboard("{Backspace}");
    expect(onValue).toHaveBeenLastCalledWith([]);

    // Toggling an option adds it; toggling it again removes it.
    await screen.findByRole("listbox");
    const aurora = await screen.findByRole("option", { name: "Aurora Hall" });
    await user.click(aurora);
    expect(onValue).toHaveBeenLastCalledWith([1]);
    expect(screen.getByRole("option", { name: "Aurora Hall" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.click(screen.getByRole("option", { name: "Aurora Hall" }));
    expect(onValue).toHaveBeenLastCalledWith([]);
  });

  it("multiple: chips are removable from the keyboard, and focus returns to the input", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker multiple initial={[1, 2]} onValue={onValue} aria-label="Venues" />);
    await screen.findByText("Aurora Hall");

    const remove = screen.getByRole("button", { name: "Remove Basalt Rooms" });
    remove.focus();
    await user.keyboard("{Delete}");
    expect(onValue).toHaveBeenLastCalledWith([1]);
    expect(screen.getByRole("combobox", { name: "Venues" })).toHaveFocus();

    screen.getByRole("button", { name: "Remove Aurora Hall" }).focus();
    await user.keyboard("{Enter}");
    expect(onValue).toHaveBeenLastCalledWith([]);
  });

  it("disabled: never opens and disables the input", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker disabled />);
    const input = screen.getByRole("combobox", { name: "Venue" });
    expect(input).toBeDisabled();
    await user.click(input).catch(() => undefined);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(backend.listRequests()).toHaveLength(0);
  });
});
