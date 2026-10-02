/**
 * Full-stack target-usage proof (contract line 11):
 * `<Page title="Events"><ResourceTable resource="events" /></Page>` renders a
 * populated, sortable, paginated table against msw-simulated backend handlers
 * (schema fetch → parse → derived columns → ordering/search/page params).
 *
 * The schema client, provider and hooks are owned by concurrent builders;
 * until their implementations land, this suite skips with a notice (same
 * pattern as the D9 snapshot guard) and runs for real afterwards.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "../../../../tests/msw/server";
import * as listModule from "../../../hooks/useResourceList";
import * as clientModule from "../../../schema/client";
import * as providerModule from "../../../schema/provider";
import * as useSchemaModule from "../../../schema/useSchema";
import { Page } from "../../page/page";
import { demoHandlers, makeDemoEvents } from "./demo-fixtures";
import { ResourceTable } from "./ResourceTable";

const implReady = (
  [
    clientModule.createKarniClient,
    providerModule.KarniProvider,
    useSchemaModule.useSchema,
    listModule.useResourceList,
  ] as unknown[]
).every((candidate) => typeof candidate === "function");

if (!implReady) {
  console.warn(
    "[resource-table] target-usage suite skipped: schema/hooks builder implementations " +
      "have not landed yet (stub modules found). It runs automatically once they do.",
  );
}

function mountTargetUsage(): void {
  // The baseUrl carries the API prefix (hooks request `/<resource>/` under
  // it); the client de-duplicates the prefix for the default schemaUrl.
  const client = clientModule.createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { KarniProvider } = providerModule;
  // prettier-ignore
  const targetUsage = <Page title="Events"><ResourceTable resource="events" /></Page>;
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {targetUsage}
    </KarniProvider>,
  );
}

describe.skipIf(!implReady)("ResourceTable target usage (full stack)", () => {
  beforeEach(() => {
    server.use(...demoHandlers());
  });

  it("renders a populated sortable paginated table from <Page><ResourceTable/></Page>", async () => {
    mountTargetUsage();

    // The Page chrome is the complete screen.
    expect(screen.getByRole("heading", { level: 1, name: "Events" })).toBeInTheDocument();

    // Populated: a full default page of rows (header row + 25).
    const table = await screen.findByRole("table", undefined, { timeout: 5000 });
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(26), {
      timeout: 5000,
    });
    // Default server order is id-ascending → "Event 57" comes first…
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Event 57");
    // …and the schema-driven default expand resolved organizer objects (D5).
    expect(within(table).getAllByText("Ada Lovelace").length).toBeGreaterThan(0);

    // Paginated: DRF count drives the page math.
    expect(screen.getByText("Page 1 of 3 · 57 items")).toBeInTheDocument();

    // Sortable: a header click maps to the DRF ordering param server-side.
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Title" }));
    await waitFor(
      () =>
        expect(within(screen.getByRole("table")).getAllByRole("row")[1]).toHaveTextContent(
          "Event 01",
        ),
      { timeout: 5000 },
    );
    expect(screen.getByRole("columnheader", { name: "Title" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    // Paginated: Next requests page 2 of the sorted list.
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3 · 57 items")).toBeInTheDocument(), {
      timeout: 5000,
    });
    await waitFor(
      () =>
        expect(within(screen.getByRole("table")).getAllByRole("row")[1]).toHaveTextContent(
          "Event 26",
        ),
      { timeout: 5000 },
    );
  });

  it("narrows through the declared search param end to end", async () => {
    mountTargetUsage();
    await screen.findByRole("table", undefined, { timeout: 5000 });

    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Event 03");

    // 300ms debounce, then one filtered page.
    await waitFor(
      () => expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2),
      { timeout: 5000 },
    );
    expect(screen.getByText("Event 03")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 1 · 1 item")).toBeInTheDocument();
  });

  it("recovers from an out-of-range page via the D5 404 clamp", async () => {
    // Start on page 2 of the 57-event dataset, then shrink the dataset to a
    // single page by swapping handlers — the stale page is now out of range.
    mountTargetUsage();
    await screen.findByRole("table", undefined, { timeout: 5000 });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText(/Page 2 of 3/)).toBeInTheDocument(), {
      timeout: 5000,
    });

    // The dataset shrinks to a single page; pages 2 and 3 now 404 with DRF's
    // "Invalid page." — Next requests page 3, and the clamp walks back to 1.
    server.use(...demoHandlers(makeDemoEvents(10)));
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Page 1 of 1 · 10 items")).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
