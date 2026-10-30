/**
 * The charts API's shapes (karni-charts, experimental).
 *
 * `GET /charts/<slug>/data/` answers `{ chart, data }`: the saved definition
 * and the source resource's aggregate, which `@karni/ui`'s `DataChart` reads.
 */
import type { AggregateMetric, AggregateResult } from "@karni/ui";

/** Experimental. One saved chart, as the admin defines it. */
export interface SavedChartDefinition {
  id: string;
  name: string;
  slug: string;
  description: string;
  /** The resource the chart reads (`products`). */
  source: string;
  kind: "bar" | "line";
  x_field: string;
  x_bucket: string;
  x_label: string;
  y_metric: AggregateMetric;
  y_value: string;
  y_label: string;
  z_field: string;
  z_bucket: string;
  z_mode: "stack" | "series";
  top: number | null;
  default_filters: Record<string, unknown>;
  /** The list filters a viewer may add. */
  allowed_filters: string[];
  position: number;
}

/** Experimental. The answer of `GET /charts/<slug>/data/`. */
export interface SavedChartData {
  chart: SavedChartDefinition;
  data: AggregateResult;
}
