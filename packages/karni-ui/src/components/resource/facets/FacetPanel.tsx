/**
 * Experimental. FacetPanel: how many rows each node of a taxonomy counts,
 * as a list of checkboxes that filter the list (`GET /<resource>/facets/`).
 */
import { HEADING_TAGS, type HeadingLevel } from "../../../lib/heading";
import * as React from "react";
import {
  useResourceFacets,
  type FacetNode,
  type FacetsResponse,
} from "../../../hooks/useResourceFacets";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import type { KarniQueryValue } from "../../../schema/client";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { Checkbox } from "../../primitives/checkbox";
import { Skeleton } from "../../primitives/skeleton";

registerComponentRole("facet-panel", "FacetPanel");

/** Experimental. What the `Empty` slot of FacetPanel receives. */
export interface FacetPanelEmptyProps {
  /** The panel's heading ("Region"). */
  label: string;
}

/** Experimental. The replaceable parts of FacetPanel (`slots`). */
export interface FacetPanelSlots {
  /** While the counts load. */
  Loading: React.ComponentType<{ rows: number }>;
  /** No node counts a row under the current filters. */
  Empty: React.ComponentType<FacetPanelEmptyProps>;
  /** The counts could not be loaded, with retry when it can help. */
  Error: React.ComponentType<ErrorSlotProps>;
}

/** Experimental. The props of FacetPanel. */
export interface FacetPanelProps {
  /** The panel heading's level. Default 2, the level under a page's `<h1>`. */
  headingLevel?: HeadingLevel;
  /** The tagged resource: "products". */
  resource: string;
  /** The taxonomy key: "region" (`class Karni: taxonomies`). */
  taxonomy: string;
  /** The chosen node ids. */
  value: ReadonlyArray<string | number>;
  /** Called with the new choice when a node is ticked or cleared. */
  onChange: (value: Array<string | number>) => void;
  /**
   * The list's other query parameters (filters, `search`), so the counts are
   * those of the rows the list shows. Leave this taxonomy's own parameters
   * out, or each node counts only the rows already chosen.
   */
  query?: Readonly<Record<string, KarniQueryValue>>;
  /** True (default): a node counts the rows tagged with it or below it, each row once. */
  rollup?: boolean;
  /** The heading. Default: the taxonomy key, capitalised. */
  label?: string;
  /** Replace the loading, empty or error state. */
  slots?: Partial<FacetPanelSlots>;
  className?: string;
}

function capitalised(text: string): string {
  const spaced = text.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function FacetPanelLoading({ rows }: { rows: number }): React.ReactElement {
  return (
    <div aria-hidden="true" className="flex flex-col gap-2 py-1">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className={cn("h-3.5", index % 2 === 0 ? "w-2/3" : "w-1/2")} />
      ))}
    </div>
  );
}

function FacetPanelEmpty({ label }: FacetPanelEmptyProps): React.ReactElement {
  return (
    <p className="py-2 text-sm text-muted-foreground">
      No {label.toLowerCase()} counts a row here.
    </p>
  );
}

function FacetPanelError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState variant="inline" {...props} />;
}

/** Experimental. FacetPanel's own slot components, for wrapping rather than rewriting. */
export const defaultFacetPanelSlots: FacetPanelSlots = {
  Loading: FacetPanelLoading,
  Empty: FacetPanelEmpty,
  Error: FacetPanelError,
};

/** The nodes in the answer's order, each with its depth among the counted nodes. */
export function facetRows(nodes: readonly FacetNode[]): Array<FacetNode & { depth: number }> {
  const byId = new Map(nodes.map((node) => [String(node.id), node]));
  const depths = new Map<string, number>();
  const depthOf = (node: FacetNode, seen: Set<string>): number => {
    const key = String(node.id);
    const known = depths.get(key);
    if (known !== undefined) return known;
    const parent = node.parent === null ? undefined : byId.get(String(node.parent));
    const depth = parent === undefined || seen.has(key) ? 0 : depthOf(parent, seen.add(key)) + 1;
    depths.set(key, depth);
    return depth;
  };
  return nodes.map((node) => ({ ...node, depth: depthOf(node, new Set()) }));
}

/**
 * Experimental. The facet filter of a list tagged to a tree: each counted
 * node with its count, nested under its parent, and a checkbox that chooses
 * it. The counts come from `facets/` with the list's other filters, so they
 * say how many rows each choice would show. ResourceTable shows one per
 * taxonomy with `facets`, and keeps the choice in its URL state.
 *
 * Escape hatches: `slots` (loading, empty, error), `query` (what the counts
 * follow) and `rollup`.
 */
export function FacetPanel(props: FacetPanelProps): React.ReactElement {
  const {
    resource,
    taxonomy,
    value,
    onChange,
    query,
    rollup = true,
    headingLevel = 2,
    slots,
    className,
  } = props;
  const Heading = HEADING_TAGS[headingLevel];
  const label = props.label ?? capitalised(taxonomy);
  const Slots: FacetPanelSlots = { ...defaultFacetPanelSlots, ...slots };
  const headingId = React.useId();
  const facets = useResourceFacets(resource, { taxonomy, rollup, query }, { retry: false });
  const chosen = React.useMemo(() => new Set(value.map(String)), [value]);
  const shown = React.useRef<FacetsResponse | undefined>(undefined);
  if (facets.data !== undefined) shown.current = facets.data;
  const data = facets.data ?? shown.current;

  const toggle = (node: FacetNode, on: boolean): void => {
    const rest = value.filter((id) => String(id) !== String(node.id));
    onChange(on ? [...rest, node.id] : rest);
  };

  let body: React.ReactNode;
  if (data === undefined && facets.isError) {
    body = (
      <Slots.Error
        error={facets.error}
        context={{ action: "count", resource: label.toLowerCase() }}
        onRetry={() => void facets.refetch()}
        retrying={facets.isFetching}
      />
    );
  } else if (data === undefined) {
    body = <Slots.Loading rows={4} />;
  } else if (data.results.length === 0) {
    body = <Slots.Empty label={label} />;
  } else {
    body = (
      <ul className="flex flex-col gap-1">
        {facetRows(data.results).map((node) => {
          const id = `${headingId}-${String(node.id)}`;
          return (
            <li
              key={String(node.id)}
              className="flex items-center gap-2 text-sm"
              style={{ paddingInlineStart: `${node.depth * 1}rem` }}
            >
              <Checkbox
                id={id}
                checked={chosen.has(String(node.id))}
                onCheckedChange={(state) => toggle(node, state === true)}
              />
              <label htmlFor={id} className="flex min-w-0 flex-1 items-center gap-2">
                <span className="min-w-0 flex-1 truncate">{node.label}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{node.count}</span>
              </label>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      aria-busy={facets.isFetching}
      className={cn("flex w-full min-w-0 flex-col gap-2 rounded-md border p-3", className)}
    >
      <div className="flex items-center justify-between gap-2">
        <Heading id={headingId} className="text-sm font-medium">
          {label}
        </Heading>
        {value.length > 0 ? (
          <button
            type="button"
            className="rounded-sm text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onChange([])}
          >
            Clear {label.toLowerCase()}
          </button>
        ) : null}
      </div>
      <div className="max-h-72 overflow-y-auto">{body}</div>
    </section>
  );
}
