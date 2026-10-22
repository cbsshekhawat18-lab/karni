import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { Skeleton } from "../primitives/skeleton";

registerComponentRole("chart", "DataChart");

/**
 * In-house SVG chart (contract: no chart dependency).
 *
 * Accessibility model (contract D10): the SVG is a labelled image
 * (role="img" + aria-label + <title>/<desc>) described by a generated
 * summary (the range of each series); the REAL accessible data surface is a
 * visually-hidden <table> rendered next to it. The tooltip is rendered
 * OUTSIDE the role="img" element and hidden from assistive tech; the SVG is
 * focusable, the arrow keys move the tooltip from point to point, and each
 * point is announced through a polite live region.
 *
 * Colors come exclusively from the --karni-chart-1..5 tokens, via the
 * Tailwind preset's chart color scale (stroke-chart-N / fill-chart-N /
 * bg-chart-N classes — whole class names, per contract D7).
 */

export type DataChartKind = "line" | "bar";

export interface DataChartPoint {
  label: string;
  value: number;
}

export interface DataChartSeries {
  name: string;
  data: readonly DataChartPoint[];
}

export interface DataChartTooltipContext {
  /** Category (x-axis) label under the pointer. */
  label: string;
  /** One entry per series that has a value at this category. */
  points: ReadonlyArray<{ seriesName: string; value: number; swatchClassName: string }>;
}

/** What the `Tooltip` slot receives: the hovered (or keyboard-selected) category. */
export interface DataChartTooltipProps extends DataChartTooltipContext {
  valueFormatter: (value: number) => string;
}

/** What the `Legend` slot receives. */
export interface DataChartLegendProps {
  series: ReadonlyArray<{ name: string; swatchClassName: string }>;
}

/** What the `Empty` slot receives (no plottable data). */
export interface DataChartEmptyProps {
  /** The chart's title, for screen readers. */
  title: string;
  /** The `emptyLabel` prop. */
  label: React.ReactNode;
}

/** What the `Loading` slot receives (`loading` is true). */
export interface DataChartLoadingProps {
  title: string;
  /** The viewBox size, for a placeholder of the chart's proportions. */
  width: number;
  height: number;
}

/** The parts of the chart a project can replace (`slots={{ Tooltip: MyTooltip }}`). */
export interface DataChartSlots {
  /** The tooltip's content (the positioned box around it stays the chart's). */
  Tooltip: React.ComponentType<DataChartTooltipProps>;
  /** The series legend; decorative, the hidden table carries the names. */
  Legend: React.ComponentType<DataChartLegendProps>;
  /** Shown instead of the chart when there is nothing to plot. */
  Empty: React.ComponentType<DataChartEmptyProps>;
  /** Shown instead of the chart while `loading`. */
  Loading: React.ComponentType<DataChartLoadingProps>;
}

export interface DataChartProps {
  kind: DataChartKind;
  /** Single-series shorthand (ignored when `series` is given). */
  data?: readonly DataChartPoint[];
  /** Multi-series data; series cycle through --karni-chart-1..5. */
  series?: readonly DataChartSeries[];
  /** Chart title: SVG <title>, aria-label and the hidden table's caption. */
  title: string;
  /** Longer description for the SVG <desc>. */
  description?: string;
  /**
   * What screen readers hear after the title and description. Default: a
   * generated summary (each series' lowest and highest value). "" omits it.
   */
  summary?: string;
  /** Formats values in the tooltip, y-axis ticks and the hidden table. */
  valueFormatter?: (value: number) => string;
  /** Formats x-axis tick labels (default: the category label itself). */
  xTickFormatter?: (label: string) => string;
  /** Fully custom tooltip content. Prefer the `Tooltip` slot. */
  renderTooltip?: (context: DataChartTooltipContext) => React.ReactNode;
  /** viewBox width (default 640) — rendered size is responsive. */
  width?: number;
  /** viewBox height (default 240). */
  height?: number;
  /** Approximate number of y-axis ticks (default 4). */
  yTickCount?: number;
  /** Show the series legend (default: only for 2+ series). */
  showLegend?: boolean;
  /** Show the tooltip on hover and keyboard focus (default true). */
  showTooltip?: boolean;
  /** Column header of the hidden table's category column (default "Label"). */
  categoryHeader?: string;
  /** Text shown when there is no plottable data. */
  emptyLabel?: string;
  /** True while the data loads: a placeholder of the chart's size replaces it. */
  loading?: boolean;
  /** Replaces the Tooltip, Legend, Empty or Loading; see DataChartSlots. */
  slots?: Partial<DataChartSlots>;
  className?: string;
}

const SERIES_STROKE = [
  "stroke-chart-1",
  "stroke-chart-2",
  "stroke-chart-3",
  "stroke-chart-4",
  "stroke-chart-5",
] as const;

const SERIES_FILL = [
  "fill-chart-1",
  "fill-chart-2",
  "fill-chart-3",
  "fill-chart-4",
  "fill-chart-5",
] as const;

const SERIES_SWATCH = [
  "bg-chart-1",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
] as const;

function seriesClass(classes: readonly string[], index: number): string {
  const value = classes[index % classes.length];
  // The modulo keeps the index in range; the fallback only satisfies strict
  // indexing and never triggers at runtime.
  return value ?? classes[0] ?? "";
}

const MARGIN = { top: 8, right: 12, bottom: 28, left: 48 } as const;
/** Tick label size in viewBox units, as drawn when the chart renders at its viewBox size or larger. */
const TICK_FONT = 10;
/** The smallest tick label, in CSS pixels, a narrow chart scales its labels up to. */
const MIN_TICK_PX = 11;

function niceNum(range: number, round: boolean): number {
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / 10 ** exponent;
  let niceFraction: number;
  if (round) {
    niceFraction = fraction < 1.5 ? 1 : fraction < 3 ? 2 : fraction < 7 ? 5 : 10;
  } else {
    niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  }
  return niceFraction * 10 ** exponent;
}

function niceTicks(min: number, max: number, count: number): number[] {
  const span = max > min ? max - min : 1;
  const step = niceNum(niceNum(span, false) / Math.max(1, count), true);
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = start; value <= end + step / 2; value += step) {
    // Trim float noise (0.30000000000000004 → 0.3).
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

interface NormalizedChart {
  categories: readonly string[];
  seriesNames: readonly string[];
  /** matrix[seriesIndex][categoryIndex] — null when missing/non-finite. */
  matrix: ReadonlyArray<ReadonlyArray<number | null>>;
}

function normalize(
  data: readonly DataChartPoint[] | undefined,
  series: readonly DataChartSeries[] | undefined,
): NormalizedChart {
  const resolved: readonly DataChartSeries[] =
    series ?? (data !== undefined ? [{ name: "Value", data }] : []);

  const categories: string[] = [];
  const seen = new Set<string>();
  for (const s of resolved) {
    for (const point of s.data) {
      if (!seen.has(point.label)) {
        seen.add(point.label);
        categories.push(point.label);
      }
    }
  }

  const matrix = resolved.map((s) => {
    const byLabel = new Map<string, number>();
    for (const point of s.data) {
      if (Number.isFinite(point.value)) {
        byLabel.set(point.label, point.value);
      }
    }
    return categories.map((label) => byLabel.get(label) ?? null);
  });

  return { categories, seriesNames: resolved.map((s) => s.name), matrix };
}

function defaultValueFormatter(value: number): string {
  return value.toLocaleString();
}

/** "Line chart, Jan to Jun. Signups: lowest 120 (Jan), highest 300 (May)." */
function describeChart(
  kind: DataChartKind,
  chart: NormalizedChart,
  format: (value: number) => string,
): string {
  const { categories, seriesNames, matrix } = chart;
  const span =
    categories.length > 1
      ? `${categories[0] ?? ""} to ${categories[categories.length - 1] ?? ""}`
      : (categories[0] ?? "");
  const parts = [`${kind === "line" ? "Line" : "Bar"} chart, ${span}.`];
  matrix.forEach((row, seriesIndex) => {
    let low = -1;
    let high = -1;
    for (let index = 0; index < row.length; index += 1) {
      const value = row[index] ?? null;
      if (value === null) continue;
      if (low === -1 || value < (row[low] ?? value)) low = index;
      if (high === -1 || value > (row[high] ?? value)) high = index;
    }
    if (low === -1 || high === -1) return;
    const prefix = matrix.length > 1 ? `${seriesNames[seriesIndex] ?? ""}: lowest` : "Lowest";
    parts.push(
      `${prefix} ${format(row[low] ?? 0)} (${categories[low] ?? ""}), highest ${format(row[high] ?? 0)} (${categories[high] ?? ""}).`,
    );
  });
  return parts.join(" ");
}

function DefaultTooltip({
  label,
  points,
  valueFormatter,
}: DataChartTooltipProps): React.ReactElement {
  return (
    <>
      <p className="mb-1 font-medium">{label}</p>
      {points.map((point) => (
        <p key={point.seriesName} className="flex items-center gap-1.5">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", point.swatchClassName)} />
          <span className="text-muted-foreground">{point.seriesName}</span>
          <span className="ml-auto font-medium">{valueFormatter(point.value)}</span>
        </p>
      ))}
    </>
  );
}

function DefaultLegend({ series }: DataChartLegendProps): React.ReactElement {
  return (
    <div aria-hidden="true" className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
      {series.map(({ name, swatchClassName }) => (
        <span key={name} className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className={cn("h-2 w-2 rounded-full", swatchClassName)} />
          {name}
        </span>
      ))}
    </div>
  );
}

function DefaultEmpty({ title, label }: DataChartEmptyProps): React.ReactElement {
  return (
    <div className="flex w-full items-center justify-center rounded-lg border border-dashed border-border px-6 py-10 text-sm text-muted-foreground">
      <span className="sr-only">{title}: </span>
      {label}
    </div>
  );
}

function DefaultLoading({ title, width, height }: DataChartLoadingProps): React.ReactElement {
  return (
    <>
      <Skeleton
        className="w-full"
        style={{ aspectRatio: `${String(width)} / ${String(height)}` }}
      />
      <span className="sr-only">Loading {title}</span>
    </>
  );
}

/** The default pieces of the chart, for wrapping one. */
export const defaultDataChartSlots: DataChartSlots = {
  Tooltip: DefaultTooltip,
  Legend: DefaultLegend,
  Empty: DefaultEmpty,
  Loading: DefaultLoading,
};

/** The rendered width of an element, tracked as it resizes (null before the first measure). */
function useRenderedWidth(ref: React.RefObject<Element | null>, active: boolean): number | null {
  const [width, setWidth] = React.useState<number | null>(null);
  React.useEffect(() => {
    const element = ref.current;
    if (!active || element === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width;
      if (measured !== undefined && measured > 0) setWidth(measured);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, active]);
  return width;
}

/**
 * Minimal line/bar chart driven by `{label, value}` points or named series.
 *
 * Keyboard and screen readers: the chart is an image named by `title`,
 * described by `description` and a generated summary, with every value in a
 * visually-hidden table. Tab focuses it; the arrow keys (Home, End) move the
 * tooltip from category to category and announce each one; Escape hides it.
 *
 * Escape hatches: `slots` replaces the Tooltip, Legend, Empty or Loading
 * pieces; `valueFormatter`/`xTickFormatter`, `summary`, `renderTooltip`,
 * `width`/`height`/`yTickCount`, legend and tooltip toggles, `className`
 * (merged via cn()). Colors are only themeable through the
 * --karni-chart-1..5 CSS variables.
 */
export function DataChart({
  kind,
  data,
  series,
  title,
  description,
  summary,
  valueFormatter = defaultValueFormatter,
  xTickFormatter,
  renderTooltip,
  width = 640,
  height = 240,
  yTickCount = 4,
  showLegend,
  showTooltip = true,
  categoryHeader = "Label",
  emptyLabel = "No data",
  loading = false,
  slots,
  className,
}: DataChartProps): React.ReactElement {
  const { Tooltip, Legend, Empty, Loading } = { ...defaultDataChartSlots, ...slots };
  const titleId = React.useId();
  const descId = React.useId();
  const summaryId = React.useId();
  const [hovered, setHoveredState] = React.useState<number | null>(null);
  // The latest index, for key presses that arrive before a re-render.
  const hoveredRef = React.useRef<number | null>(null);
  const setHovered = React.useCallback((index: number | null) => {
    hoveredRef.current = index;
    setHoveredState(index);
  }, []);
  // What the live region says: set by the keyboard only, so hovering stays quiet.
  const [announcement, setAnnouncement] = React.useState("");
  const svgRef = React.useRef<SVGSVGElement>(null);

  const chart = React.useMemo(() => normalize(data, series), [data, series]);
  const { categories, seriesNames, matrix } = chart;

  const values = matrix.flat().filter((value): value is number => value !== null);
  const plottable = !loading && categories.length > 0 && values.length > 0;
  const renderedWidth = useRenderedWidth(svgRef, plottable);

  if (loading) {
    return (
      <div aria-busy="true" className={cn("w-full", className)}>
        <Loading title={title} width={width} height={height} />
      </div>
    );
  }

  if (!plottable) {
    return (
      <div className={cn("w-full", className)}>
        <Empty title={title} label={emptyLabel} />
      </div>
    );
  }

  // A chart drawn narrower than its viewBox would shrink its labels below
  // legibility: keep them at MIN_TICK_PX, and the lines visible, on phones.
  const scale = renderedWidth === null ? 1 : renderedWidth / width;
  const fontSize = renderedWidth === null ? TICK_FONT : Math.max(TICK_FONT, MIN_TICK_PX / scale);
  const strokeWidth = Math.max(2, 1.5 / scale);
  const pointRadius = Math.max(3, 2.5 / scale);

  // scales
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  const ticks = niceTicks(rawMin, rawMax, yTickCount);
  const domainMin = ticks[0] ?? rawMin;
  const domainMax = ticks[ticks.length - 1] ?? rawMax;
  const domainSpan = domainMax - domainMin || 1;

  const longestTick = Math.max(...ticks.map((tick) => valueFormatter(tick).length));
  const margin = {
    top: Math.max(MARGIN.top, fontSize * 0.6),
    right: MARGIN.right,
    // Room for the y labels (about 0.6em a character) and the x labels.
    left: Math.max(MARGIN.left, Math.ceil(longestTick * fontSize * 0.6) + 6),
    bottom: Math.max(MARGIN.bottom, Math.ceil(fontSize * 2)),
  };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const yScale = (value: number): number =>
    margin.top + ((domainMax - value) / domainSpan) * plotHeight;
  const bandWidth = plotWidth / categories.length;
  const bandCenter = (index: number): number => margin.left + (index + 0.5) * bandWidth;
  const zeroY = yScale(Math.max(domainMin, Math.min(domainMax, 0)));

  // marks
  const seriesCount = Math.max(1, matrix.length);
  const groupWidth = bandWidth * 0.7;
  const barWidth = groupWidth / seriesCount;

  const marks = matrix.map((row, seriesIndex) => {
    if (kind === "bar") {
      return (
        <g key={seriesIndex} className={seriesClass(SERIES_FILL, seriesIndex)}>
          {row.map((value, categoryIndex) => {
            if (value === null) {
              return null;
            }
            const x = bandCenter(categoryIndex) - groupWidth / 2 + seriesIndex * barWidth;
            const y = Math.min(yScale(value), zeroY);
            const barHeight = Math.abs(yScale(value) - zeroY);
            return (
              <rect
                key={categoryIndex}
                x={x}
                y={y}
                width={Math.max(1, barWidth - 2)}
                height={barHeight}
                rx={2}
              />
            );
          })}
        </g>
      );
    }

    const points = row
      .map((value, categoryIndex) =>
        value === null ? null : ([bandCenter(categoryIndex), yScale(value)] as const),
      )
      .filter((point): point is readonly [number, number] => point !== null);

    return (
      <g key={seriesIndex}>
        <polyline
          className={seriesClass(SERIES_STROKE, seriesIndex)}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          points={points.map(([x, y]) => `${String(x)},${String(y)}`).join(" ")}
        />
        {points.map(([x, y], pointIndex) => (
          <circle
            key={pointIndex}
            className={seriesClass(SERIES_FILL, seriesIndex)}
            cx={x}
            cy={y}
            r={pointRadius}
          />
        ))}
      </g>
    );
  });

  const pointsAt = (index: number): DataChartTooltipContext["points"] =>
    matrix
      .map((row, seriesIndex) => ({
        seriesName: seriesNames[seriesIndex] ?? "",
        value: row[index] ?? null,
        swatchClassName: seriesClass(SERIES_SWATCH, seriesIndex),
      }))
      .filter(
        (entry): entry is { seriesName: string; value: number; swatchClassName: string } =>
          entry.value !== null,
      );

  // tooltip geometry (percentages of the rendered box)
  const pct = (value: number, total: number): string => `${String((value / total) * 100)}%`;
  const hoveredPoints = hovered === null ? [] : pointsAt(hovered);
  const hoveredLabel = hovered === null ? undefined : categories[hovered];

  const select = (index: number | null): void => {
    setHovered(index);
    if (index === null) {
      setAnnouncement("");
      return;
    }
    const spoken = pointsAt(index)
      .map((point) =>
        matrix.length > 1
          ? `${point.seriesName} ${valueFormatter(point.value)}`
          : valueFormatter(point.value),
      )
      .join(", ");
    setAnnouncement(`${categories[index] ?? ""}: ${spoken}`);
  };

  const onKeyDown = (event: React.KeyboardEvent<SVGSVGElement>): void => {
    const last = categories.length - 1;
    const current = hoveredRef.current;
    let next: number | null | undefined;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = current === null ? 0 : Math.min(last, current + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = current === null ? last : Math.max(0, current - 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = last;
        break;
      case "Escape":
        next = null;
        break;
      default:
        return;
    }
    event.preventDefault();
    select(next);
  };

  const generatedSummary =
    summary ??
    `${describeChart(kind, chart, valueFormatter)}${
      showTooltip ? " Use the arrow keys to read each value." : ""
    }`;
  const describedBy =
    [description !== undefined ? descId : null, generatedSummary !== "" ? summaryId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  const defaultLegend = seriesNames.length > 1;

  return (
    <div className={cn("w-full", className)}>
      <div className="relative w-full rounded-md ring-offset-background has-[svg:focus-visible]:ring-2 has-[svg:focus-visible]:ring-ring has-[svg:focus-visible]:ring-offset-2">
        <svg
          ref={svgRef}
          role="img"
          aria-label={title}
          aria-labelledby={titleId}
          aria-describedby={describedBy}
          tabIndex={showTooltip ? 0 : undefined}
          onKeyDown={showTooltip ? onKeyDown : undefined}
          onBlur={showTooltip ? () => select(null) : undefined}
          viewBox={`0 0 ${String(width)} ${String(height)}`}
          className="block h-auto w-full text-muted-foreground focus-visible:outline-none"
        >
          <title id={titleId}>{title}</title>
          {description !== undefined && <desc id={descId}>{description}</desc>}

          {/* y grid + tick labels */}
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={yScale(tick)}
                y2={yScale(tick)}
                stroke="currentColor"
                strokeOpacity={tick === 0 ? 0.6 : 0.2}
              />
              <text
                x={margin.left - 6}
                y={yScale(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={fontSize}
                fill="currentColor"
              >
                {valueFormatter(tick)}
              </text>
            </g>
          ))}

          {/* x tick labels */}
          {categories.map((category, index) => (
            <text
              key={category}
              x={bandCenter(index)}
              y={height - margin.bottom + fontSize * 1.4}
              textAnchor="middle"
              fontSize={fontSize}
              fill="currentColor"
            >
              {xTickFormatter ? xTickFormatter(category) : category}
            </text>
          ))}

          {marks}
        </svg>

        {/* Hover affordance + tooltip: visual only, OUTSIDE the role="img"
            element and hidden from assistive tech (contract D10). */}
        {showTooltip && (
          <div aria-hidden="true" className="absolute inset-0">
            <div
              className="absolute flex"
              style={{
                left: pct(margin.left, width),
                width: pct(plotWidth, width),
                top: pct(margin.top, height),
                height: pct(plotHeight, height),
              }}
              onMouseLeave={() => {
                setHovered(null);
              }}
            >
              {categories.map((category, index) => (
                <div
                  key={category}
                  data-karni-chart-hit={index}
                  className="h-full flex-1"
                  onMouseEnter={() => {
                    setHovered(index);
                  }}
                />
              ))}
            </div>
            {hovered !== null && hoveredLabel !== undefined && hoveredPoints.length > 0 && (
              <div
                data-karni-chart-tooltip=""
                className="pointer-events-none absolute z-raised min-w-24 -translate-x-1/2 rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
                style={{
                  left: pct(bandCenter(hovered), width),
                  top: pct(margin.top, height),
                }}
              >
                {renderTooltip ? (
                  renderTooltip({ label: hoveredLabel, points: hoveredPoints })
                ) : (
                  <Tooltip
                    label={hoveredLabel}
                    points={hoveredPoints}
                    valueFormatter={valueFormatter}
                  />
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {(showLegend ?? defaultLegend) && (
        <Legend
          series={seriesNames.map((name, index) => ({
            name,
            swatchClassName: seriesClass(SERIES_SWATCH, index),
          }))}
        />
      )}

      {/* The accessible data surface (contract D10). */}
      <VisuallyHidden.Root asChild>
        <div>
          {generatedSummary !== "" && <p id={summaryId}>{generatedSummary}</p>}
          <p role="status">{announcement}</p>
          <table>
            <caption>{title}</caption>
            <thead>
              <tr>
                <th scope="col">{categoryHeader}</th>
                {seriesNames.map((name) => (
                  <th key={name} scope="col">
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((category, categoryIndex) => (
                <tr key={category}>
                  <th scope="row">{category}</th>
                  {matrix.map((row, seriesIndex) => {
                    const value = row[categoryIndex] ?? null;
                    return (
                      <td key={seriesIndex}>{value === null ? "—" : valueFormatter(value)}</td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </VisuallyHidden.Root>
    </div>
  );
}
