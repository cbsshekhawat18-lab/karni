/**
 * ResourceDetail's related tabs against the msw backend: the venues, tags
 * and users list operations publish `x-karni-related` (tests/msw/openapi.ts),
 * and the events list filters by `venue` and `organizer`.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { openApiFixture } from "../../../../tests/msw/openapi";
import { axeViolations } from "../../../../tests/axe";
import { createKarniClient } from "../../../schema/client";
import { parseOpenApi } from "../../../schema/parse";
import { KarniProvider } from "../../../schema/provider";
import { ResourceDetail } from "./ResourceDetail";
import { findRelation, resolveRelatedTabs } from "./related";

function mount(ui: React.ReactElement) {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

async function titles(panel: HTMLElement): Promise<string[]> {
  await within(panel).findByText("Annual Conference");
  return within(panel)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.querySelector("td")?.textContent ?? "");
}

describe("ResourceDetail related tabs", () => {
  it("shows a tab per relation, each a table filtered to this row", async () => {
    mount(<ResourceDetail resource="venues" id={2} related={["events"]} />);
    const tab = await screen.findByRole("tab", { name: "Events" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "Events" });
    // Venue 2 holds events 1, 7 and 10 (tests/msw/handlers.ts); no other event shows.
    expect((await titles(panel)).sort()).toEqual(
      ["Annual Conference", "Community Picnic", "Office Hours"].sort(),
    );
    expect(within(panel).queryByText("Design Meetup")).not.toBeInTheDocument();
    // The column that points back here says nothing new: it is hidden.
    expect(within(panel).queryByRole("columnheader", { name: /venue/i })).not.toBeInTheDocument();
  });

  it("names relations by name, resource or resource.field, with a label and table props", async () => {
    const user = userEvent.setup();
    mount(
      <ResourceDetail
        resource="users"
        id={2}
        related={[
          { name: "events.organizer", label: "Hosting", table: { caption: "Hosted events" } },
          "nothing-here",
        ]}
      />,
    );
    const hosting = await screen.findByRole("tab", { name: "Hosting" });
    expect(hosting).toBeInTheDocument();
    // User 2 organizes events 1, 5, 7 and 11.
    expect(await screen.findByRole("grid", { name: "Hosted events" })).toBeInTheDocument();
    const panel = screen.getByRole("tabpanel", { name: "Hosting" });
    expect((await titles(panel)).sort()).toEqual(
      ["Annual Conference", "Community Picnic", "Quarterly Review", "Retro Session"].sort(),
    );
    await user.click(screen.getByRole("tab", { name: "nothing-here" }));
    expect(screen.getByRole("note")).toHaveTextContent(
      'users has no related rows named "nothing-here" (its relations: event_set)',
    );
  });

  it("says why a relation whose list has no filter shows no table", async () => {
    mount(<ResourceDetail resource="tags" id={1} related={["events"]} />);
    await screen.findByRole("tab", { name: "Events" });
    expect(screen.getByRole("note")).toHaveTextContent(
      "The events list has no filter on tags, so it cannot show only the rows of this tag.",
    );
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
  });

  it("renders no tabs without the prop, and the slot replaces them", async () => {
    const { unmount } = mount(<ResourceDetail resource="venues" id={2} />);
    await screen.findByText("Riverside Pavilion");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    unmount();
    mount(
      <ResourceDetail
        resource="venues"
        id={2}
        related={["events"]}
        slots={{
          Related: ({ tabs }) => (
            <p>{tabs.map((tab) => `${tab.label}: ${JSON.stringify(tab.params)}`).join(", ")}</p>
          ),
        }}
      />,
    );
    expect(await screen.findByText('Events: {"venue":2}')).toBeInTheDocument();
  });

  it("passes axe with a tab open", async () => {
    const { container } = mount(<ResourceDetail resource="venues" id={2} related={["events"]} />);
    const panel = await screen.findByRole("tabpanel", { name: "Events" });
    await titles(panel);
    await waitFor(async () => expect(await axeViolations(container)).toEqual([]));
  });
});

describe("resolving related tabs", () => {
  const parsed = parseOpenApi(openApiFixture);
  const venues = parsed.resources["venues"];

  it("parses x-karni-related from the list operation", () => {
    expect(venues?.related).toEqual([
      {
        name: "event_set",
        resource: "events",
        field: "venue",
        param: "venue",
        key: "id",
        label: "Events",
      },
    ]);
    expect(parsed.resources["events"]?.related).toBeUndefined();
  });

  it("finds a relation by name, resource.field, or a resource only one relation leads to", () => {
    const related = [
      {
        name: "deals",
        resource: "deals",
        field: "company",
        param: "company",
        key: "id",
        label: "Deals",
      },
      {
        name: "referred_deals",
        resource: "deals",
        field: "referrer",
        param: "referrer",
        key: "id",
        label: "Deals",
      },
      {
        name: "person_set",
        resource: "people",
        field: "company",
        param: "company",
        key: "id",
        label: "People",
      },
    ];
    expect(findRelation(related, "referred_deals")?.field).toBe("referrer");
    expect(findRelation(related, "deals.referrer")?.name).toBe("referred_deals");
    expect(findRelation(related, "deals")?.field).toBe("company"); // the name wins
    expect(findRelation(related, "people")?.name).toBe("person_set");
    // Two relations lead to deals and neither is named so: the name must say which.
    expect(
      findRelation(
        related.slice(1, 2).concat({
          ...related[1],
          name: "owned_deals",
          field: "owner",
        } as (typeof related)[number]),
        "deals",
      ),
    ).toBeUndefined();
  });

  it("leaves out a relation whose list the user may not read, and takes the key's value", () => {
    if (venues === undefined) throw new Error("no venues");
    const events = parsed.resources["events"];
    if (events === undefined) throw new Error("no events");
    const guarded = {
      ...parsed.resources,
      events: {
        ...events,
        operations: {
          ...events.operations,
          list: {
            ...events.operations.list,
            path: "/api/events/",
            method: "get" as const,
            queryParams: [],
            access: { authenticated: true },
          },
        },
      },
    };
    const anonymous = { status: "anonymous" as const, user: null };
    expect(
      resolveRelatedTabs(["events"], venues, guarded, { id: 2 }, 2, anonymous, "venue"),
    ).toEqual([]);
    const [tab] = resolveRelatedTabs(
      ["events"],
      venues,
      parsed.resources,
      { id: 9 },
      2,
      null,
      "venue",
    );
    expect(tab?.params).toEqual({ venue: 9 });
  });
});
