import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KarniApiError } from "../../schema/client";
import { ChartCard } from "./chart-card";
import { DashboardCard, DashboardGrid, defaultDashboardCardSlots } from "./dashboard-grid";
import { axeViolations } from "../../../tests/axe";

const points = [
  { label: "North", value: 4 },
  { label: "South", value: 7 },
];

describe("DashboardGrid", () => {
  it("lays cards out one, two, then `columns` per row", () => {
    const { container, rerender } = render(<DashboardGrid />);
    const grid = container.firstElementChild;
    expect(grid).toHaveClass("grid", "grid-cols-1", "md:grid-cols-2", "xl:grid-cols-3");
    rerender(<DashboardGrid columns={4} className="mt-4" />);
    expect(grid).toHaveClass("xl:grid-cols-4", "mt-4");
    rerender(<DashboardGrid columns={2} />);
    expect(grid).not.toHaveClass("xl:grid-cols-3");
  });

  it("clamps a card's span to the grid's columns, and full takes the row", () => {
    render(
      <DashboardGrid columns={2}>
        <DashboardCard title="Wide" span={4}>
          a
        </DashboardCard>
        <DashboardCard title="Row" span="full">
          b
        </DashboardCard>
        <DashboardCard title="One">c</DashboardCard>
      </DashboardGrid>,
    );
    const wide = screen.getByRole("region", { name: "Wide" });
    expect(wide).toHaveClass("md:col-span-2");
    expect(wide).not.toHaveClass("xl:col-span-4");
    expect(screen.getByRole("region", { name: "Row" })).toHaveClass("col-span-full");
    expect(screen.getByRole("region", { name: "One" }).className).not.toMatch(/col-span/);
  });

  it("is a region named by its heading, with a description and actions", () => {
    render(
      <DashboardCard
        title="Revenue"
        description="This quarter"
        actions={<button type="button">Open</button>}
        headingLevel={3}
      >
        <p>content</p>
      </DashboardCard>,
    );
    const card = screen.getByRole("region", { name: "Revenue" });
    expect(within(card).getByRole("heading", { level: 3, name: "Revenue" })).toBeInTheDocument();
    expect(within(card).getByText("This quarter")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(within(card).getByText("content")).toBeInTheDocument();
  });

  it("shows loading, empty and error states in place of the content", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <DashboardCard title="Orders" loading>
        <p>content</p>
      </DashboardCard>,
    );
    const card = screen.getByRole("region", { name: "Orders" });
    expect(card).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Loading Orders")).toHaveClass("sr-only");
    expect(screen.queryByText("content")).not.toBeInTheDocument();

    rerender(
      <DashboardCard title="Orders" empty emptyLabel="No orders yet.">
        <p>content</p>
      </DashboardCard>,
    );
    expect(screen.getByText("No orders yet.")).toBeInTheDocument();
    expect(card).not.toHaveAttribute("aria-busy");

    rerender(
      <DashboardCard title="Orders" loading error={new KarniApiError(500, {})} onRetry={onRetry}>
        <p>content</p>
      </DashboardCard>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong on our side");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("takes slots for its states, and exports the defaults to wrap", () => {
    render(
      <DashboardCard
        title="Orders"
        empty
        slots={{ Empty: ({ title }) => <p>Nothing in {title}</p> }}
      />,
    );
    expect(screen.getByText("Nothing in Orders")).toBeInTheDocument();
    expect(Object.keys(defaultDashboardCardSlots).sort()).toEqual(["Empty", "Error", "Loading"]);
  });

  it("passes axe as a grid of cards", async () => {
    const { container } = render(
      <DashboardGrid>
        <ChartCard title="Orders by region" kind="bar" data={points} span={2} />
        <DashboardCard title="Notes">
          <p>Shipped on time.</p>
        </DashboardCard>
      </DashboardGrid>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("ChartCard", () => {
  it("names the chart with the card's title", () => {
    render(
      <ChartCard title="Orders by region" description="Last 30 days" kind="bar" data={points} />,
    );
    expect(screen.getByRole("region", { name: "Orders by region" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Orders by region/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Orders by region" })).toBeInTheDocument();
  });

  it("says so when there is nothing to chart", () => {
    render(<ChartCard title="Orders" kind="line" series={[{ name: "A", data: [] }]} />);
    expect(screen.getByText("No data to chart yet.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("draws a chart-shaped placeholder while loading", () => {
    render(<ChartCard title="Orders" kind="bar" data={[]} loading />);
    expect(screen.getByRole("region", { name: "Orders" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Loading Orders")).toBeInTheDocument();
    expect(screen.queryByText("No data to chart yet.")).not.toBeInTheDocument();
  });

  it("shows the error with Try again", async () => {
    const onRetry = vi.fn();
    render(
      <ChartCard
        title="Orders"
        kind="bar"
        data={points}
        error={new TypeError("Failed to fetch")}
        onRetry={onRetry}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("passes chart props and slots through, and replaces card states", () => {
    render(
      <ChartCard
        title="Orders"
        kind="bar"
        data={[]}
        cardSlots={{ Empty: () => <p>Nothing yet, check back tomorrow.</p> }}
      />,
    );
    expect(screen.getByText("Nothing yet, check back tomorrow.")).toBeInTheDocument();
  });
});
