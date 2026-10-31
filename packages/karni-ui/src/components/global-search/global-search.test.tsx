/**
 * <GlobalSearch> (experimental) against the msw backend's GET /api/search/:
 * the shortcut, the WAI-ARIA combobox, keyboard navigation, the grouped
 * results, the links to ResourceDetail pages, the states and the slots.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import type { GlobalSearchHit } from "../../hooks/useGlobalSearch";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { Layout } from "../layout/layout";
import { GlobalSearch, defaultHitHref, type GlobalSearchResultLinkProps } from "./global-search";

function render(ui: React.ReactElement) {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

async function openAndType(text: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /search/i }));
  const input = screen.getByRole("combobox");
  await user.type(input, text);
  await screen.findAllByRole("option");
  return { user, input };
}

describe("GlobalSearch", () => {
  it("opens with Cmd or Ctrl+K and closes with Escape", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch debounceMs={0} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: "Search" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("combobox"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.keyboard("{Meta>}k{/Meta}");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("shows the results grouped per resource, each linking to its page", async () => {
    render(<GlobalSearch debounceMs={0} />);
    await openAndType("hall");
    const listbox = screen.getByRole("listbox", { name: "Search results" });
    const groups = within(listbox).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-labelledby") !== null)).toEqual([
      true,
      true,
    ]);
    expect(within(groups[0] as HTMLElement).getByText("Venues")).toBeTruthy();
    const options = within(listbox).getAllByRole("option");
    expect(options[0]?.textContent).toContain("Grand Hall");
    expect(options[0]?.textContent).toContain("Jaipur");
    expect(options[0]?.getAttribute("href")).toBe("/venues/1");
    expect(options.at(-1)?.getAttribute("href")).toBe("/events/12");
    expect(screen.getByRole("status").textContent).toBe("2 results.");
  });

  it("follows the WAI-ARIA combobox pattern with the keyboard", async () => {
    const onSelect = vi.fn();
    render(<GlobalSearch debounceMs={0} onSelect={onSelect} />);
    const { user, input } = await openAndType("hall");
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    const listbox = screen.getByRole("listbox");
    expect(input.getAttribute("aria-controls")).toBe(listbox.id);
    const options = screen.getAllByRole("option");
    expect(input.getAttribute("aria-activedescendant")).toBe(options[0]?.id);
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{ArrowDown}");
    expect(input.getAttribute("aria-activedescendant")).toBe(options[1]?.id);
    await user.keyboard("{ArrowDown}");
    expect(input.getAttribute("aria-activedescendant")).toBe(options[0]?.id); // it wraps
    await user.keyboard("{ArrowUp}");
    expect(input.getAttribute("aria-activedescendant")).toBe(options[1]?.id);
    expect(document.activeElement).toBe(input); // focus never leaves the input
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ resource: "events", id: 12, title: "Town Hall" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("follows the hit's own link without onSelect", async () => {
    render(<GlobalSearch debounceMs={0} hrefFor={(hit) => `/app/${hit.resource}/${hit.id}`} />);
    const { user } = await openAndType("grand");
    const clicked = vi.fn((event: MouseEvent) => event.preventDefault());
    const option = screen.getByRole("option");
    option.addEventListener("click", clicked);
    expect(option.getAttribute("href")).toBe("/app/venues/1");
    await user.keyboard("{Enter}");
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says what is happening: too short, no results, failed", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch debounceMs={0} />);
    await user.click(screen.getByRole("button", { name: /search/i }));
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Type at least 2 characters to search.");
    const input = screen.getByRole("combobox");
    await user.type(input, "zz");
    await waitFor(() => expect(status.textContent).toBe("No results for “zz”."));
    expect(input.getAttribute("aria-expanded")).toBe("false");
    await user.clear(input);
    await user.type(input, "boom");
    await waitFor(() => expect(status.textContent).toBe("Search failed. Try again."));
  });

  it("narrows to the models it is given and renders a router link through the slot", async () => {
    function RouterLink({ hit, children, ...props }: GlobalSearchResultLinkProps) {
      return (
        <a {...props} data-router="yes" data-resource={hit.resource}>
          {children}
        </a>
      );
    }
    render(<GlobalSearch debounceMs={0} models={["events"]} slots={{ ResultLink: RouterLink }} />);
    await openAndType("hall");
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.dataset["resource"])).toEqual(["events"]);
    expect(options[0]?.dataset["router"]).toBe("yes");
  });

  it("can be controlled and can turn the shortcut off", async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    const view = render(<GlobalSearch open={false} onOpenChange={onOpenChange} shortcut={false} />);
    await user.keyboard("{Control>}k{/Control}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByText("Ctrl K")).toBeNull();
    await user.click(screen.getByRole("button", { name: /search/i }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("dialog")).toBeNull();
    view.unmount();
  });

  it("links a hit to /<resource>/<id> by default", () => {
    const hit: GlobalSearchHit = {
      resource: "loose-slots",
      id: "a b",
      title: "x",
      subtitle: null,
      score: 1,
    };
    expect(defaultHitHref(hit)).toBe("/loose-slots/a%20b");
  });
});

describe("Layout search", () => {
  it("mounts the palette in the top bar", async () => {
    const user = userEvent.setup();
    render(
      <Layout search={{ debounceMs: 0 }} header={<span>Account</span>}>
        <h1>Home</h1>
      </Layout>,
    );
    const banner = screen.getByRole("banner");
    expect(within(banner).getByRole("button", { name: /search/i })).toBeTruthy();
    expect(within(banner).getByText("Account")).toBeTruthy();
    await act(async () => {
      await user.keyboard("{Control>}k{/Control}");
    });
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("mounts nothing without the prop", () => {
    render(<Layout>content</Layout>);
    expect(screen.queryByRole("button", { name: /search/i })).toBeNull();
  });
});
