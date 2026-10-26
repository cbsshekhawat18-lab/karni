/**
 * <Dashboard> against the msw backend: the Event resource declares a
 * dashboard (x-karni-dashboard in tests/msw/openapi.ts), so the page shows
 * its counts (every row, new ones, one per state, a named count) and the
 * newest rows, each number a page_size=1 list request with the count's
 * filters.
 */
import { QueryClient } from "@tanstack/react-query";
import { render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { openApiFixture, resetMswData, server } from "../../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../../auth/provider";
import type { KarniUser } from "../../auth/types";
import { createKarniClient } from "../../schema/client";
import { parseOpenApi } from "../../schema/parse";
import { KarniProvider } from "../../schema/provider";
import { Dashboard, resolveRelativeDate, resolveSection } from "./dashboard";

function render(ui: React.ReactElement, identity?: AuthContextValue) {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>
  );
  return renderUi(
    identity === undefined ? (
      tree
    ) : (
      <AuthContext.Provider value={identity}>{tree}</AuthContext.Provider>
    ),
  );
}

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["attendee"] };
const signedIn: AuthContextValue = {
  user: USER,
  roles: USER.roles,
  status: "authenticated",
  login: () => Promise.resolve({ ok: true, user: USER }),
  logout: () => Promise.resolve(),
  refresh: () => Promise.resolve(),
  adoptTokens: () => Promise.resolve(),
};

const NOW = new Date(2026, 9, 12, 12, 0, 0); // 2026-10-12 noon, local time

function must<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`fixture has no ${what}`);
  return value;
}

/** The fixture with its events list operation's extensions changed. */
function schemaWith(change: (listOp: Record<string, unknown>) => void): Record<string, unknown> {
  const doc = structuredClone(openApiFixture) as {
    paths: Record<string, { get: Record<string, unknown> }>;
  };
  change(must(doc.paths["/api/events/"], "events path").get);
  return doc;
}

beforeEach(() => {
  resetMswData();
  window.history.replaceState(null, "", "/");
});

describe("resolveSection", () => {
  const events = must(parseOpenApi(openApiFixture).resources["events"], "events resource");
  const declaration = must(events.dashboard, "events dashboard");

  it("turns the declaration into counts with the list filters that count them", () => {
    const section = resolveSection("events", events, declaration, NOW);
    expect(section.label).toBe("Events");
    expect(section.counts.map((count) => [count.key, count.label, count.params])).toEqual([
      ["total", "All", {}],
      ["new", "New in 7 days", { created_at__gte: new Date(2026, 9, 5).toISOString() }],
      ["by:draft", "Draft", { status: "draft" }],
      ["by:published", "Published", { status: "published" }],
      ["count:Public", "Public", { is_public: true }],
    ]);
    expect(section.recent).toBe(3);
    expect(section.ordering).toBe("-created_at");
    expect(section.columns).toEqual(["title", "status"]);
  });

  it("resolves relative dates against the day the page is viewed", () => {
    expect(resolveRelativeDate("today", NOW)).toBe("2026-10-12");
    expect(resolveRelativeDate("today-7", NOW)).toBe("2026-10-05");
    expect(resolveRelativeDate("today+1", NOW)).toBe("2026-10-13");
    expect(resolveRelativeDate(["today", "x"], NOW)).toEqual(["2026-10-12", "x"]);
    expect(resolveRelativeDate("tomorrow", NOW)).toBe("tomorrow");
    expect(resolveRelativeDate(3, NOW)).toBe(3);
  });

  it("sends a plain date for a date field and a boolean for a boolean field", () => {
    const schema = {
      ...events,
      fields: events.fields.map((field) =>
        field.name === "created_at" ? { ...field, kind: "date" as const } : field,
      ),
    };
    const section = resolveSection(
      "events",
      schema,
      { ...declaration, by: "is_public", values: ["true"], counts: [] },
      NOW,
    );
    expect(section.counts[1]?.params).toEqual({ created_at__gte: "2026-10-05" });
    expect(section.counts[2]).toMatchObject({ label: "Yes", params: { is_public: true } });
  });
});

describe("Dashboard", () => {
  it("shows a section per model that opts in: its counts and its newest rows", async () => {
    render(<Dashboard now={() => NOW} />);
    const section = await screen.findByRole("region", { name: "Events" });
    // a tile's label is the Stat's <p> (a table cell may carry the same word)
    const tile = (label: string): HTMLElement =>
      within(section)
        .getByText(label, { selector: "p" })
        .closest("[class*='rounded-lg']") as HTMLElement;
    // twelve seeded events: every even id is published and public
    await waitFor(() => expect(tile("All")).toHaveTextContent("12"));
    await waitFor(() => expect(tile("Draft")).toHaveTextContent("6"));
    await waitFor(() => expect(tile("Published")).toHaveTextContent("6"));
    await waitFor(() => expect(tile("Public")).toHaveTextContent("6"));
    expect(tile("New in 7 days")).toHaveTextContent(/\d/);
    // the newest three, by created_at, with the declared columns only
    const grid = await within(section).findByRole("grid", undefined, { timeout: 5000 });
    await within(grid).findByText("Town Hall");
    const rows = within(grid).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Town Hall"),
      expect.stringContaining("Retro Session"),
      expect.stringContaining("Office Hours"),
    ]);
    const headers = within(grid)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["Title", "Status"]);
    expect(within(section).queryByRole("combobox")).toBeNull(); // no filter bar, no page size
  });

  it("opens a row and the list from the tiles", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onOpenList = vi.fn();
    render(<Dashboard now={() => NOW} onOpen={onOpen} onOpenList={onOpenList} />);
    const section = await screen.findByRole("region", { name: "Events" });
    await user.click(await within(section).findByRole("button", { name: /^Draft: 6/ }));
    expect(onOpenList).toHaveBeenCalledWith("events", { status: "draft" });
    await user.click(within(section).getByRole("button", { name: "All events" }));
    expect(onOpenList).toHaveBeenLastCalledWith("events", {});
    const grid = await within(section).findByRole("grid", undefined, { timeout: 5000 });
    await user.click(await within(grid).findByRole("button", { name: /Town Hall/ }));
    expect(onOpen).toHaveBeenCalledWith("events", expect.objectContaining({ title: "Town Hall" }));
  });

  it("says when a declared filter is not one of the list's, instead of a wrong number", async () => {
    const doc = schemaWith((listOp) => {
      listOp["x-karni-dashboard"] = {
        label: "Events",
        counts: [{ label: "Due", params: { due_on: "today" } }],
        recent: 0,
        total: false,
      };
    });
    server.use(http.get("*/api/schema/", () => HttpResponse.json(doc)));
    render(<Dashboard now={() => NOW} />);
    const section = await screen.findByRole("region", { name: "Events" });
    expect(await within(section).findByText(/Not a filter of this list/)).toHaveTextContent(
      "due_on",
    );
    expect(within(section).queryByRole("grid")).toBeNull();
  });

  it("leaves out a resource the signed-in user may not list", async () => {
    const doc = schemaWith((listOp) => {
      listOp["x-karni-access"] = { role: ["staff"] };
    });
    server.use(http.get("*/api/schema/", () => HttpResponse.json(doc)));
    render(<Dashboard now={() => NOW} />, signedIn);
    expect(await screen.findByText("Nothing on the dashboard yet")).toBeInTheDocument();
    expect(screen.getByText(/dashboard = True/)).toHaveTextContent("events");
  });

  it("explains an empty dashboard, and a schema that failed to load", async () => {
    const doc = schemaWith((listOp) => {
      delete listOp["x-karni-dashboard"];
    });
    server.use(http.get("*/api/schema/", () => HttpResponse.json(doc)));
    const { unmount } = render(<Dashboard />);
    expect(await screen.findByText("Nothing on the dashboard yet")).toBeInTheDocument();
    unmount();

    server.use(http.get("*/api/schema/", () => HttpResponse.json({}, { status: 500 })));
    render(<Dashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong on our side");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("the sections hook and the slots replace what renders", async () => {
    render(
      <Dashboard
        now={() => NOW}
        sections={(found) => found.map((section) => ({ ...section, label: "Happenings" }))}
        slots={{
          Count: ({ count, value }) => (
            <p>
              {count.label}={value ?? "…"}
            </p>
          ),
          Recent: () => <p>no table</p>,
        }}
      />,
    );
    const section = await screen.findByRole("region", { name: "Happenings" });
    await within(section).findByText("All=12");
    expect(within(section).getByText("no table")).toBeInTheDocument();
    expect(within(section).queryByRole("grid")).toBeNull();
  });
});
