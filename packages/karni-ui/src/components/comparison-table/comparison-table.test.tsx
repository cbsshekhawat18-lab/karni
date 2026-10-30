import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axeViolations } from "../../../tests/axe";
import { ComparisonTable, bestOf, type ComparisonMetric } from "./comparison-table";

interface Region {
  id: number;
  name: string;
  stores: number;
  returns: number | null;
  online: boolean;
}

const regions: Region[] = [
  { id: 1, name: "North", stores: 12, returns: 0.04, online: true },
  { id: 2, name: "South", stores: 8, returns: 0.02, online: false },
  { id: 3, name: "East", stores: 12, returns: null, online: true },
];

const metrics: ComparisonMetric<Region>[] = [
  { key: "stores", label: "Stores", better: "higher" },
  {
    key: "returns",
    label: "Return rate",
    description: "Share of orders",
    better: "lower",
    format: (value) => (typeof value === "number" ? `${value * 100}%` : ""),
  },
  { key: "online", label: "Sells online" },
];

describe("ComparisonTable", () => {
  it("puts entities in columns and metrics in rows, each headed for a screen reader", () => {
    render(<ComparisonTable caption="Regions" entities={regions} metrics={metrics} />);
    const table = screen.getByRole("table", { name: "Regions" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Metric", "North", "South", "East"]);
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((th) => th.textContent),
    ).toEqual(["Stores", "Return rateShare of orders", "Sells online"]);
    const online = within(table).getByRole("rowheader", { name: "Sells online" }).closest("tr");
    expect(online?.textContent).toBe("Sells onlineYesNoYes");
  });

  it("marks the best value of a metric (ties all count) and says so to a screen reader", () => {
    render(<ComparisonTable caption="Regions" entities={regions} metrics={metrics} />);
    const best = Array.from(document.querySelectorAll("td[data-best]"));
    expect(best.map((cell) => cell.textContent)).toEqual(["12 (best)", "12 (best)", "2% (best)"]);
    expect(best[0]).toHaveClass("font-semibold");
    expect(screen.getAllByText("(best)")[0]).toHaveClass("sr-only");
  });

  it("finds the best values, skipping empty ones, and marks nothing when all tie", () => {
    expect([...bestOf(metrics[1] as ComparisonMetric<Region>, regions)]).toEqual([1]);
    const flat = regions.map((region) => ({ ...region, stores: 5 }));
    expect(bestOf(metrics[0] as ComparisonMetric<Region>, flat).size).toBe(0);
    expect(bestOf(metrics[2] as ComparisonMetric<Region>, regions).size).toBe(0);
  });

  it("keeps the metric column and the entity row in view (sticky)", () => {
    render(<ComparisonTable caption="Regions" entities={regions} metrics={metrics} />);
    expect(document.querySelector("thead")).toHaveClass("sticky", "top-0");
    expect(screen.getByRole("rowheader", { name: "Stores" })).toHaveClass("sticky", "left-0");
  });

  it("reads any entity shape through entityKey and entityLabel", () => {
    render(
      <ComparisonTable
        caption="Plans"
        entities={[{ code: "a", title: "Alpha", seats: 1 }]}
        entityKey={(plan) => plan.code}
        entityLabel={(plan) => `Plan ${plan.title}`}
        metrics={[{ key: "seats", label: "Seats" }]}
        metricHeader="Plan"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Plan Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Plan" })).toBeInTheDocument();
  });

  it("shows loading, empty and error states", async () => {
    const onRetry = vi.fn();
    const { rerender, container } = render(
      <ComparisonTable caption="Regions" entities={[]} metrics={metrics} loading />,
    );
    expect(container.firstElementChild).toHaveAttribute("aria-busy", "true");
    rerender(<ComparisonTable caption="Regions" entities={[]} metrics={metrics} />);
    expect(screen.getByText("Nothing to compare yet.")).toBeInTheDocument();
    rerender(
      <ComparisonTable
        caption="Regions"
        entities={regions}
        metrics={metrics}
        error={new TypeError("Failed to fetch")}
        onRetry={onRetry}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("passes axe", async () => {
    const { container } = render(
      <ComparisonTable caption="Regions" entities={regions} metrics={metrics} />,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
