import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DataChart, defaultDataChartSlots, type DataChartSeries } from "./data-chart";

const signups = [
  { label: "Jan", value: 10 },
  { label: "Feb", value: 25 },
  { label: "Mar", value: 18 },
] as const;

const multiSeries: readonly DataChartSeries[] = [
  { name: "Signups", data: signups },
  {
    name: "Churn",
    data: [
      { label: "Jan", value: 4 },
      { label: "Feb", value: 6 },
      // "Mar" intentionally missing — the table must show a placeholder.
    ],
  },
];

/** querySelector that throws instead of returning null (strict, no `!`). */
function q<T extends Element>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (element === null) {
    throw new Error(`expected an element matching ${selector}`);
  }
  return element;
}

describe("DataChart accessibility (contract D10)", () => {
  it("renders the SVG as a labelled image with <title> and <desc>", () => {
    const { container } = render(
      <DataChart
        kind="line"
        data={signups}
        title="Signups over time"
        description="Monthly signups, January through March."
      />,
    );

    const svg = q<SVGSVGElement>(container, "svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute("aria-label", "Signups over time");

    const title = q<SVGTitleElement>(svg, "title");
    expect(title).toHaveTextContent("Signups over time");
    expect(svg.getAttribute("aria-labelledby")).toBe(title.id);

    const desc = q<SVGDescElement>(svg, "desc");
    expect(desc).toHaveTextContent("Monthly signups, January through March.");
    // The description first, then the generated summary.
    expect(svg.getAttribute("aria-describedby")?.split(" ")[0]).toBe(desc.id);
    expect(svg).toHaveAccessibleDescription(
      "Monthly signups, January through March. Line chart, Jan to Mar. Lowest 10 (Jan), highest 25 (Feb). Use the arrow keys to read each value.",
    );
  });

  it("summarises each series for screen readers; summary overrides or drops it", () => {
    const { container, rerender } = render(
      <DataChart kind="bar" series={multiSeries} title="Signups vs churn" showTooltip={false} />,
    );
    const svg = q<SVGSVGElement>(container, "svg");
    expect(svg).toHaveAccessibleDescription(
      "Bar chart, Jan to Mar. Signups: lowest 10 (Jan), highest 25 (Feb). Churn: lowest 4 (Jan), highest 6 (Feb).",
    );
    rerender(<DataChart kind="bar" series={multiSeries} title="T" summary="Churn is flat." />);
    expect(q<SVGSVGElement>(container, "svg")).toHaveAccessibleDescription("Churn is flat.");
    rerender(<DataChart kind="bar" series={multiSeries} title="T" summary="" />);
    expect(q<SVGSVGElement>(container, "svg")).not.toHaveAttribute("aria-describedby");
  });

  it("reads point by point from the keyboard, announcing each one", async () => {
    const user = userEvent.setup();
    const { container } = render(<DataChart kind="line" series={multiSeries} title="Compare" />);
    const svg = q<SVGSVGElement>(container, "svg");
    await user.tab();
    expect(svg).toHaveFocus();
    expect(svg.parentElement).toHaveClass("has-[svg:focus-visible]:ring-2");
    expect(container.querySelector("[data-karni-chart-tooltip]")).toBeNull();

    await user.keyboard("{ArrowRight}");
    expect(q(container, "[data-karni-chart-tooltip]")).toHaveTextContent("Jan");
    expect(screen.getByRole("status")).toHaveTextContent("Jan: Signups 10, Churn 4");

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(screen.getByRole("status")).toHaveTextContent("Mar: Signups 18");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("status")).toHaveTextContent("Mar: Signups 18");
    await user.keyboard("{Home}");
    expect(screen.getByRole("status")).toHaveTextContent("Jan:");
    await user.keyboard("{End}{ArrowLeft}");
    expect(screen.getByRole("status")).toHaveTextContent("Feb: Signups 25, Churn 6");

    await user.keyboard("{Escape}");
    expect(container.querySelector("[data-karni-chart-tooltip]")).toBeNull();
    await user.keyboard("{ArrowLeft}");
    await user.tab();
    expect(container.querySelector("[data-karni-chart-tooltip]")).toBeNull();
  });

  it("hovering does not talk: the live region is for the keyboard", () => {
    const { container } = render(<DataChart kind="line" data={signups} title="Signups" />);
    fireEvent.mouseEnter(q(container, '[data-karni-chart-hit="1"]'));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("is not focusable without a tooltip (the table has the values)", () => {
    const { container } = render(
      <DataChart kind="line" data={signups} title="Signups" showTooltip={false} />,
    );
    expect(q<SVGSVGElement>(container, "svg")).not.toHaveAttribute("tabindex");
  });

  it("exposes the data through a visually-hidden table as the accessible surface", () => {
    render(
      <DataChart kind="bar" series={multiSeries} title="Signups vs churn" categoryHeader="Month" />,
    );

    const table = screen.getByRole("table");
    expect(q(table, "caption")).toHaveTextContent("Signups vs churn");

    const columnHeaders = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(columnHeaders).toEqual(["Month", "Signups", "Churn"]);

    const rowHeaders = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(rowHeaders).toEqual(["Jan", "Feb", "Mar"]);

    const cells = within(table)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    // Churn has no "Mar" value. The gap renders as EmptyValue (a dash read as
    // "empty"), not a crash.
    expect(cells).toEqual(["10", "4", "25", "6", "18", "–empty"]);

    // The table must not live inside the role="img" element.
    expect(table.closest('[role="img"]')).toBeNull();
  });

  it("applies valueFormatter to the hidden table values", () => {
    render(
      <DataChart
        kind="line"
        data={signups}
        title="Revenue"
        valueFormatter={(value) => `$${String(value)}`}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("$25")).toBeInTheDocument();
  });

  it("renders the hover tooltip OUTSIDE the role=img element and hidden from AT", () => {
    const { container } = render(<DataChart kind="line" data={signups} title="Signups" />);

    fireEvent.mouseEnter(q(container, '[data-karni-chart-hit="1"]'));

    const tooltip = q(container, "[data-karni-chart-tooltip]");
    expect(tooltip.closest('[role="img"]')).toBeNull();
    expect(tooltip.closest("svg")).toBeNull();
    expect(tooltip.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(within(tooltip as HTMLElement).getByText("Feb")).toBeInTheDocument();
    expect(within(tooltip as HTMLElement).getByText("25")).toBeInTheDocument();
  });

  it("hides the legend from assistive tech (the table carries the series names)", () => {
    const { container } = render(<DataChart kind="line" series={multiSeries} title="Compare" />);
    const legendSwatch = q(container, ".bg-chart-2");
    expect(legendSwatch.closest('[aria-hidden="true"]')).not.toBeNull();
  });
});

describe("DataChart rendering", () => {
  it("uses a responsive viewBox instead of fixed pixel dimensions", () => {
    const { container } = render(<DataChart kind="line" data={signups} title="Signups" />);
    const svg = q<SVGSVGElement>(container, "svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 640 240");
    expect(svg).not.toHaveAttribute("width");
    expect(svg).not.toHaveAttribute("height");
    expect(svg).toHaveClass("w-full");
  });

  it("width/height props change the viewBox (escape hatch)", () => {
    const { container } = render(
      <DataChart kind="bar" data={signups} title="Signups" width={400} height={200} />,
    );
    expect(q<SVGSVGElement>(container, "svg")).toHaveAttribute("viewBox", "0 0 400 200");
  });

  it("line kind draws one polyline + points per series, colored by chart token classes", () => {
    const { container } = render(<DataChart kind="line" series={multiSeries} title="Compare" />);

    const lines = container.querySelectorAll("polyline");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveClass("stroke-chart-1");
    expect(lines[1]).toHaveClass("stroke-chart-2");
    expect(container.querySelectorAll("circle.fill-chart-1")).toHaveLength(3);
    expect(container.querySelectorAll("circle.fill-chart-2")).toHaveLength(2);
  });

  it("bar kind draws rects grouped per series, colored by chart token classes", () => {
    const { container } = render(<DataChart kind="bar" series={multiSeries} title="Compare" />);

    expect(q(container, "g.fill-chart-1").querySelectorAll("rect")).toHaveLength(3);
    expect(q(container, "g.fill-chart-2").querySelectorAll("rect")).toHaveLength(2);
  });

  it("never sets literal colors on marks — only token classes, currentColor and none", () => {
    const { container } = render(<DataChart kind="line" series={multiSeries} title="Compare" />);
    const svg = q<SVGSVGElement>(container, "svg");
    for (const element of svg.querySelectorAll("[fill], [stroke]")) {
      for (const attribute of ["fill", "stroke"] as const) {
        const value = element.getAttribute(attribute);
        if (value !== null) {
          expect(["none", "currentColor"]).toContain(value);
        }
      }
    }
  });

  it("shows the legend only for multiple series by default, forceable via showLegend", () => {
    const single = render(<DataChart kind="line" data={signups} title="Signups" />);
    expect(single.container.querySelector(".bg-chart-1")).toBeNull();
    single.unmount();

    const forced = render(<DataChart kind="line" data={signups} title="Signups" showLegend />);
    expect(forced.container.querySelector(".bg-chart-1")).not.toBeNull();
    expect(forced.container.ownerDocument.body.textContent).toContain("Value");
  });

  it("renderTooltip replaces the default tooltip content (escape hatch)", () => {
    const { container } = render(
      <DataChart
        kind="line"
        data={signups}
        title="Signups"
        renderTooltip={({ label, points }) => (
          <strong>
            custom {label}: {String(points[0]?.value)}
          </strong>
        )}
      />,
    );

    fireEvent.mouseEnter(q(container, '[data-karni-chart-hit="0"]'));
    expect(screen.getByText("custom Jan: 10")).toBeInTheDocument();
  });

  it("showTooltip={false} removes the hover layer entirely", () => {
    const { container } = render(
      <DataChart kind="line" data={signups} title="Signups" showTooltip={false} />,
    );
    expect(container.querySelector("[data-karni-chart-hit]")).toBeNull();
  });

  it("renders the empty label instead of an SVG when there is no plottable data", () => {
    const { container } = render(
      <DataChart kind="line" data={[]} title="Signups" emptyLabel="Nothing to plot yet" />,
    );
    expect(screen.getByText("Nothing to plot yet")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("skips non-finite values without crashing", () => {
    const { container } = render(
      <DataChart
        kind="line"
        data={[
          { label: "Jan", value: 10 },
          { label: "Feb", value: Number.NaN },
          { label: "Mar", value: 18 },
        ]}
        title="Signups"
      />,
    );
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    const table = screen.getByRole("table");
    expect(within(table).getByText("empty")).toHaveClass("sr-only");
  });

  it("names an empty chart by its title for screen readers", () => {
    render(<DataChart kind="line" data={[]} title="Signups" emptyLabel="Nothing yet" />);
    expect(screen.getByText("Signups:")).toHaveClass("sr-only");
  });

  it("shows a busy placeholder while loading", () => {
    const { container } = render(
      <DataChart kind="line" data={signups} title="Signups" loading className="mt-4" />,
    );
    const root = container.firstElementChild;
    expect(root).toHaveAttribute("aria-busy", "true");
    expect(root).toHaveClass("mt-4");
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("Loading Signups")).toHaveClass("sr-only");
  });
});

describe("DataChart on a narrow screen", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps tick labels legible when drawn smaller than its viewBox", () => {
    let report: (width: number) => void = () => undefined;
    class MeasuringObserver {
      constructor(callback: ResizeObserverCallback) {
        report = (width) =>
          callback(
            [{ contentRect: { width } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          );
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    vi.stubGlobal("ResizeObserver", MeasuringObserver);
    const { container } = render(<DataChart kind="line" data={signups} title="Signups" />);
    const tick = q<SVGTextElement>(container, "text");
    expect(tick.getAttribute("font-size")).toBe("10");

    // 640 units drawn in 320px: 11px labels need 22 units.
    act(() => report(320));
    expect(Number(q<SVGTextElement>(container, "text").getAttribute("font-size"))).toBeCloseTo(22);

    // Wider than the viewBox: labels stay at their drawn size.
    act(() => report(1280));
    expect(q<SVGTextElement>(container, "text").getAttribute("font-size")).toBe("10");
  });
});

describe("DataChart slots", () => {
  it("replace the tooltip, legend, empty and loading pieces", () => {
    const slots = {
      Tooltip: ({ label }: { label: string }) => <b>slot {label}</b>,
      Legend: ({ series }: { series: ReadonlyArray<{ name: string }> }) => (
        <ul data-testid="legend">
          {series.map((entry) => (
            <li key={entry.name}>{entry.name}</li>
          ))}
        </ul>
      ),
      Empty: ({ label }: { label: React.ReactNode }) => <p data-testid="empty">{label}!</p>,
      Loading: (props: { title: string; width: number; height: number }) => (
        <div data-testid="loading">
          <defaultDataChartSlots.Loading {...props} />
        </div>
      ),
    };
    const { container, rerender } = render(
      <DataChart kind="line" series={multiSeries} title="Compare" slots={slots} />,
    );
    fireEvent.mouseEnter(q(container, '[data-karni-chart-hit="1"]'));
    expect(screen.getByText("slot Feb")).toBeInTheDocument();
    expect(screen.getByTestId("legend")).toHaveTextContent("SignupsChurn");

    rerender(<DataChart kind="line" data={[]} title="Compare" emptyLabel="None" slots={slots} />);
    expect(screen.getByTestId("empty")).toHaveTextContent("None!");

    rerender(<DataChart kind="line" data={signups} title="Compare" loading slots={slots} />);
    expect(screen.getByTestId("loading")).toHaveTextContent("Loading Compare");
  });
});
