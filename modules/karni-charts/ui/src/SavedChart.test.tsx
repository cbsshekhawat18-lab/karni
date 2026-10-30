import { http, HttpResponse } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { API_BASE, dataCalls } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { savedChartKey, savedChartQuery } from "./hooks";
import { SavedChart } from "./SavedChart";

function hiddenTable(container: HTMLElement): HTMLTableElement {
  const table = container.querySelector("table");
  if (table === null) throw new Error("expected the chart's data table");
  return table;
}

describe("SavedChart", () => {
  it("draws the saved chart with its name, description and data", async () => {
    const { container } = renderWithKarni(<SavedChart chart="launches-per-year" />);
    const svg = await screen.findByRole("img", { name: "Launches per year" });
    expect(svg.querySelector("desc")).toHaveTextContent("Products launched each year, by channel.");
    const table = hiddenTable(container);
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual(["Year", "Online", "Store"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
  });

  it("stacks the bars of a chart whose z axis stacks", async () => {
    const { container } = renderWithKarni(<SavedChart chart="launches-per-year" />);
    await screen.findByRole("img", { name: "Launches per year" });
    const online = container.querySelector("g.fill-chart-1 rect");
    const store = container.querySelector("g.fill-chart-2 rect");
    expect(online?.getAttribute("x")).toBe(store?.getAttribute("x"));
  });

  it("sends the filters and shows the narrowed data", async () => {
    const { container } = renderWithKarni(
      <SavedChart chart="launches-per-year" filters={{ channel: "online" }} />,
    );
    await screen.findByRole("img", { name: "Launches per year" });
    expect(dataCalls[0]?.get("channel")).toBe("online");
    const headers = within(hiddenTable(container))
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual(["Year", "Online"]);
  });

  it("lets the props replace the saved title and kind", async () => {
    const { container } = renderWithKarni(
      <SavedChart chart="launches-per-year" title="Launches" kind="line" />,
    );
    await screen.findByRole("img", { name: "Launches" });
    expect(container.querySelector("polyline")).not.toBeNull();
  });

  it("shows a placeholder while loading", () => {
    const { container } = renderWithKarni(<SavedChart chart="launches-per-year" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("shows the refusal when a filter is not allowed", async () => {
    renderWithKarni(<SavedChart chart="launches-per-year" filters={{ price__gte: 5 }} />);
    expect(await screen.findByText(/does not allow the filter/)).toBeInTheDocument();
  });

  it("offers a retry when the server fails", async () => {
    server.use(
      http.get(`${API_BASE}/charts/:slug/data/`, () =>
        HttpResponse.json({ detail: "Server error." }, { status: 500 }),
      ),
    );
    renderWithKarni(<SavedChart chart="launches-per-year" />);
    expect(await screen.findByRole("button", { name: /try again|retry/i })).toBeInTheDocument();
  });

  it("takes an Error slot of the project's own", async () => {
    server.use(
      http.get(`${API_BASE}/charts/:slug/data/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    renderWithKarni(
      <SavedChart
        chart="nope"
        slots={{ Error: ({ retrying }) => <p>Chart unavailable {String(retrying)}</p> }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Chart unavailable/)).toBeInTheDocument());
  });
});

describe("useSavedChart's query", () => {
  it("drops empty filters, repeats lists and keys by slug and filters", () => {
    expect(savedChartQuery({ channel: ["online", "store"], empty: null, top: 3 })).toEqual({
      channel: ["online", "store"],
      top: "3",
    });
    expect(savedChartKey("a", { b: "1", a: "2" })).toEqual(savedChartKey("a", { a: "2", b: "1" }));
    expect(savedChartKey("a").slice(0, 2)).toEqual(["karni", "charts"]);
  });
});
