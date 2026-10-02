import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("chart", "DataChart");

/**
 * In-house SVG chart (contract: no chart dependency).
 *
 * Accessibility model (contract D10): the SVG is a labelled image
 * (role="img" + aria-label + <title>/<desc>); the REAL accessible data
 * surface is a visually-hidden <table> rendered next to it. The hover
 * tooltip is a visual-only affordance rendered OUTSIDE the role="img"
 * element and hidden from assistive tech.
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
  /** Formats values in the tooltip, y-axis ticks and the hidden table. */
  valueFormatter?: (value: number) => string;
  /** Formats x-axis tick labels (default: the category label itself). */
  xTickFormatter?: (label: string) => string;
  /** Escape hatch: fully custom tooltip content. */
  renderTooltip?: (context: DataChartTooltipContext) => React.ReactNode;
  /** viewBox width (default 640) — rendered size is responsive. */
  width?: number;
  /** viewBox height (default 240). */
  height?: number;
  /** Approximate number of y-axis ticks (default 4). */
  yTickCount?: number;
  /** Show the series legend (default: only for 2+ series). */
  showLegend?: boolean;
  /** Show the hover tooltip (default true). */
  showTooltip?: boolean;
  /** Column header of the hidden table's category column (default "Label"). */
  categoryHeader?: string;
  /** Text shown when there is no plottable data. */
  emptyLabel?: string;
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

/**
 * Minimal line/bar chart driven by `{label, value}` points or named series.
 *
 * Escape hatches: `valueFormatter`/`xTickFormatter`, `renderTooltip`,
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
  className,
}: DataChartProps): React.ReactElement {
  const titleId = React.useId();
  const descId = React.useId();
  const [hovered, setHovered] = React.useState<number | null>(null);

  const { categories, seriesNames, matrix } = React.useMemo(
    () => normalize(data, series),
    [data, series],
  );

  const values = matrix.flat().filter((value): value is number => value !== null);
  if (categories.length === 0 || values.length === 0) {
    return (
      <div
        className={cn(
          "flex w-full items-center justify-center rounded-lg border border-dashed border-border px-6 py-10 text-sm text-muted-foreground",
          className,
        )}
      >
        {emptyLabel}
      </div>
    );
  }

  // --- scales ---------------------------------------------------------------
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  const ticks = niceTicks(rawMin, rawMax, yTickCount);
  const domainMin = ticks[0] ?? rawMin;
  const domainMax = ticks[ticks.length - 1] ?? rawMax;
  const domainSpan = domainMax - domainMin || 1;

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const yScale = (value: number): number =>
    MARGIN.top + ((domainMax - value) / domainSpan) * plotHeight;
  const bandWidth = plotWidth / categories.length;
  const bandCenter = (index: number): number => MARGIN.left + (index + 0.5) * bandWidth;
  const zeroY = yScale(Math.max(domainMin, Math.min(domainMax, 0)));

  // --- marks ----------------------------------------------------------------
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
          strokeWidth={2}
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
            r={3}
          />
        ))}
      </g>
    );
  });

  // --- tooltip geometry (percentages of the rendered box) -------------------
  const pct = (value: number, total: number): string => `${String((value / total) * 100)}%`;
  const hoveredPoints =
    hovered === null
      ? []
      : matrix
          .map((row, seriesIndex) => ({
            seriesName: seriesNames[seriesIndex] ?? "",
            value: row[hovered] ?? null,
            swatchClassName: seriesClass(SERIES_SWATCH, seriesIndex),
          }))
          .filter(
            (entry): entry is { seriesName: string; value: number; swatchClassName: string } =>
              entry.value !== null,
          );
  const hoveredLabel = hovered === null ? undefined : categories[hovered];

  const defaultLegend = seriesNames.length > 1;

  return (
    <div className={cn("w-full", className)}>
      <div className="relative w-full">
        <svg
          role="img"
          aria-label={title}
          aria-labelledby={titleId}
          aria-describedby={description !== undefined ? descId : undefined}
          viewBox={`0 0 ${String(width)} ${String(height)}`}
          className="block h-auto w-full text-muted-foreground"
        >
          <title id={titleId}>{title}</title>
          {description !== undefined && <desc id={descId}>{description}</desc>}

          {/* y grid + tick labels */}
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={width - MARGIN.right}
                y1={yScale(tick)}
                y2={yScale(tick)}
                stroke="currentColor"
                strokeOpacity={tick === 0 ? 0.6 : 0.2}
              />
              <text
                x={MARGIN.left - 6}
                y={yScale(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={10}
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
              y={height - MARGIN.bottom + 14}
              textAnchor="middle"
              fontSize={10}
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
                left: pct(MARGIN.left, width),
                width: pct(plotWidth, width),
                top: pct(MARGIN.top, height),
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
                className="pointer-events-none absolute z-10 min-w-24 -translate-x-1/2 rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
                style={{
                  left: pct(bandCenter(hovered), width),
                  top: pct(MARGIN.top, height),
                }}
              >
                {renderTooltip ? (
                  renderTooltip({ label: hoveredLabel, points: hoveredPoints })
                ) : (
                  <>
                    <p className="mb-1 font-medium">{hoveredLabel}</p>
                    {hoveredPoints.map((point) => (
                      <p key={point.seriesName} className="flex items-center gap-1.5">
                        <span
                          className={cn("h-2 w-2 shrink-0 rounded-full", point.swatchClassName)}
                        />
                        <span className="text-muted-foreground">{point.seriesName}</span>
                        <span className="ml-auto font-medium">{valueFormatter(point.value)}</span>
                      </p>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {(showLegend ?? defaultLegend) && (
        <div aria-hidden="true" className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          {seriesNames.map((name, index) => (
            <span key={name} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className={cn("h-2 w-2 rounded-full", seriesClass(SERIES_SWATCH, index))} />
              {name}
            </span>
          ))}
        </div>
      )}

      {/* The accessible data surface (contract D10). */}
      <VisuallyHidden.Root asChild>
        <div>
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
