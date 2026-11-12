/**
 * <ResourceGrid> against the msw backend's twelve events: cards, search, sort,
 * filters, paging, and the empty and error states.
 */
import { QueryClient } from "@tanstack/react-query";
import { render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { resetMswData, server } from "../../../tests/msw/server";
import { axeViolations } from "../../../tests/axe";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { ResourceGrid } from "./ResourceGrid";

interface EventRow {
  id: number;
  title: string;
  status: string;
}

function render(ui: React.ReactElement) {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

const card = (row: EventRow) => <article aria-label={row.title}>{row.title}</article>;

async function cards(): Promise<string[]> {
  const list = await screen.findByRole("list", { name: "Events" });
  return within(list)
    .getAllByRole("article")
    .map((node) => node.getAttribute("aria-label") ?? "");
}

beforeEach(() => resetMswData());

describe("ResourceGrid", () => {
  it("shows a page of cards, the count, and pages through", async () => {
    const user = userEvent.setup();
    render(
      <ResourceGrid<EventRow>
        resource="events"
        label="Events"
        pageSize={5}
        sortOptions={[{ value: "title", label: "Title" }]}
        renderCard={card}
      />,
    );
    expect(await cards()).toEqual([
      "API Workshop",
      "Annual Conference",
      "Community Picnic",
      "Design Meetup",
      "Hack Night",
    ]);
    expect(screen.getByText("12 results")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeInTheDocument());
    expect((await cards())[0]).toBe("Keynote Rehearsal");
  });

  it("searches, and offers to clear a search that matches nothing", async () => {
    const user = userEvent.setup();
    render(<ResourceGrid<EventRow> resource="events" label="Events" renderCard={card} />);
    await cards();
    await user.type(screen.getByLabelText("Search"), "meetup{Enter}");
    await waitFor(() => expect(screen.getByText("1 result")).toBeInTheDocument());
    expect(await cards()).toEqual(["Design Meetup"]);
    await user.clear(screen.getByLabelText("Search"));
    await user.type(screen.getByLabelText("Search"), "nothing like it{Enter}");
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear the search" }));
    await waitFor(() => expect(screen.getByText("12 results")).toBeInTheDocument());
  });

  it("sends the page's filters and goes back to page 1 when they change", async () => {
    const pages: number[] = [];
    function Page() {
      const [status, setStatus] = React.useState("published");
      const [page, setPage] = React.useState(2);
      pages.push(page);
      return (
        <>
          <button type="button" onClick={() => setStatus("draft")}>
            Drafts
          </button>
          <ResourceGrid<EventRow>
            resource="events"
            label="Events"
            pageSize={2}
            filters={{ status }}
            page={page}
            onPageChange={setPage}
            renderCard={(row) => <article aria-label={row.status}>{row.title}</article>}
          />
        </>
      );
    }
    const user = userEvent.setup();
    render(<Page />);
    expect(new Set(await cards())).toEqual(new Set(["published"]));
    await user.click(screen.getByRole("button", { name: "Drafts" }));
    await waitFor(() => expect(pages.at(-1)).toBe(1));
  });

  it("says when there is nothing at all, and when the list fails", async () => {
    server.use(http.get("*/api/events/", () => HttpResponse.json({ count: 0, results: [] })));
    const { unmount } = render(
      <ResourceGrid<EventRow> resource="events" label="Events" renderCard={card} />,
    );
    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    unmount();
    server.use(http.get("*/api/events/", () => HttpResponse.json({}, { status: 500 })));
    render(<ResourceGrid<EventRow> resource="events" label="Events" renderCard={card} />);
    expect(await screen.findByRole("button", { name: /try again|retry/i })).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = render(
      <ResourceGrid<EventRow>
        resource="events"
        label="Events"
        sortOptions={[{ value: "title", label: "Title" }]}
        renderCard={card}
      />,
    );
    await cards();
    expect(await axeViolations(container)).toEqual([]);
  });
});
