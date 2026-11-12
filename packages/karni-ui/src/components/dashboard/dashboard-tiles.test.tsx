/**
 * <DashboardTiles> against the msw backend: GET /dashboard/ answers the
 * person's tiles, a resource tile is counted through its list endpoint, the
 * server's figures show in their currency, a row links to its record, and a
 * registered component draws a tile its own way.
 */
import { QueryClient } from "@tanstack/react-query";
import { render as renderUi, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../../../tests/msw/server";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import {
  DashboardTiles,
  registerTile,
  unregisterTile,
  type DashboardTileDef,
  type TileProps,
} from "./dashboard-tiles";

function render(ui: React.ReactElement) {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

function tile(values: Partial<DashboardTileDef> & Pick<DashboardTileDef, "key" | "title">) {
  return {
    kind: "stat",
    size: "third",
    order: 0,
    description: "",
    link: null,
    resource: null,
    filters: {},
    columns: [],
    limit: 5,
    data: null,
    ...values,
  } satisfies DashboardTileDef;
}

function answer(tiles: DashboardTileDef[]) {
  server.use(http.get("http://localhost/api/dashboard/", () => HttpResponse.json({ tiles })));
}

afterEach(() => unregisterTile("shop.special"));

describe("DashboardTiles", () => {
  it("counts a resource tile through its list, with the tile's filters", async () => {
    const asked: URL[] = [];
    server.use(
      http.get("http://localhost/api/events/", ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json({ count: 7, next: null, previous: null, results: [] });
      }),
    );
    answer([
      tile({
        key: "events.drafts",
        title: "Drafts",
        resource: "events",
        filters: { status: "draft" },
      }),
    ]);
    render(<DashboardTiles />);
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText("Drafts")).toBeInTheDocument();
    expect(asked[0]?.searchParams.get("status")).toBe("draft");
    expect(asked[0]?.searchParams.get("page_size")).toBe("1");
  });

  it("shows the server's figures in their currency, each opening its link", async () => {
    const open = vi.fn();
    answer([
      tile({
        key: "commerce.revenue",
        title: "Revenue",
        size: "full",
        data: {
          currency: "EUR",
          values: [
            { label: "Today", value: "120.50", format: "money", link: null },
            { label: "Orders", value: 4, format: "number", link: "/orders" },
          ],
        },
      }),
    ]);
    render(<DashboardTiles onOpen={open} />);
    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText(/120\.50/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Orders/ }));
    expect(open).toHaveBeenCalledWith("/orders");
  });

  it("lists the server's rows, the first cell a link to the row", async () => {
    const open = vi.fn();
    answer([
      tile({
        key: "commerce.latest_orders",
        title: "Latest orders",
        kind: "list",
        data: {
          currency: "USD",
          columns: [
            { key: "number", label: "Order", format: "text" },
            { key: "total", label: "Total", format: "money" },
          ],
          rows: [{ number: "1021", total: "48.00", link: "/orders/1021" }],
        },
      }),
    ]);
    render(<DashboardTiles onOpen={open} />);
    await userEvent.click(await screen.findByRole("link", { name: "1021" }));
    expect(open).toHaveBeenCalledWith("/orders/1021");
    expect(screen.getByText("$48.00")).toBeInTheDocument();
  });

  it("draws a chart tile, and a registered component draws its own tile", async () => {
    registerTile("shop.special", ({ tile: own }: TileProps) => <p>Special: {own.title}</p>);
    answer([
      tile({
        key: "commerce.revenue_chart",
        title: "Revenue by day",
        kind: "chart",
        data: {
          kind: "bar",
          format: "money",
          currency: "USD",
          points: [{ label: "2026-11-12", value: "70.00" }],
        },
      }),
      tile({ key: "shop.special", title: "Today's picks", kind: "custom" }),
    ]);
    render(<DashboardTiles />);
    expect(await screen.findByText("Special: Today's picks")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Revenue by day" })).toBeInTheDocument();
  });

  it("says what the empty prop says when the person sees no tile", async () => {
    answer([]);
    render(<DashboardTiles empty={<p>Nothing for you here yet.</p>} />);
    await waitFor(() => expect(screen.getByText("Nothing for you here yet.")).toBeInTheDocument());
  });
});
