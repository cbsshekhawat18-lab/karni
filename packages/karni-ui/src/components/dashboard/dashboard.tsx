/**
 * <Dashboard>: the staff app's home page, from the models that opt in.
 *
 * A model declares `class Karni: dashboard = {...}` and the server publishes
 * the normalized declaration as `x-karni-dashboard` on its list operation.
 * This component reads every such resource from the schema and renders one
 * section per model: a `Stat` tile per count (every row, the new ones, one
 * per state, the named counts) and a `ResourceTable` of the newest rows.
 *
 * Every number is a list request with `page_size=1` and the count's filters,
 * so the API's row scope, access rules and field visibility apply unchanged.
 * A resource the signed-in user may not list is left out. A count whose
 * filter the list endpoint does not declare says so instead of showing a
 * wrong number.
 *
 * Escape hatches: `resources` picks the sections, `sections` rewrites them
 * (labels, order, counts) before rendering, every part is a slot (`Section`,
 * `Counts`, `Count`, `Recent`, `Empty`, `Loading`, `Error`), and a home page
 * can compose `Stat` and `ResourceTable` by hand instead.
 */
import * as React from "react";
import { AuthContext } from "../../auth/provider";
import { useResourceList } from "../../hooks/useResourceList";
import type { FilterValue } from "../../hooks/types";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { useParsedSchema } from "../../schema/useSchema";
import type { DashboardDef, FieldDef, ResourceSchema } from "../../schema/types";
import { describeError } from "../../states/describe-error";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { useDelayedFlag } from "../../states/hooks";
import { EmptyState } from "../empty-state/empty-state";
import { Button } from "../primitives/button";
import { Skeleton } from "../primitives/skeleton";
import { evaluateAccess } from "../resource/table/access";
import { ResourceTable, type ResourceColumn } from "../resource/ResourceTable";
import { Stat } from "../stat/stat";

registerComponentRole("dashboard", "Dashboard");

type Row = Record<string, unknown>;

/** One number on the dashboard: what it counts and the list filters that count it. */
export interface DashboardCount {
  /** Stable within the section: "total", "new", "by:<value>" or "count:<label>". */
  key: string;
  label: string;
  /** The list query parameters, relative dates already resolved. */
  params: Readonly<Record<string, FilterValue>>;
  /** Clicking the tile opens the list with these filters (`onOpenList`). */
  filters: Readonly<Record<string, FilterValue>>;
}

/** One model's part of the dashboard, resolved from its declaration. */
export interface DashboardSection {
  resource: string;
  schema: ResourceSchema;
  declaration: DashboardDef;
  label: string;
  order: number;
  counts: readonly DashboardCount[];
  /** How many of the newest rows the table shows (0: none). */
  recent: number;
  /** The table's ordering ("-created_at"), or undefined for the API's default. */
  ordering: string | undefined;
  columns: readonly string[] | null;
}

/** What the `Count` slot receives. */
export interface DashboardCountProps {
  section: DashboardSection;
  count: DashboardCount;
  /** The number, once loaded. */
  value: number | undefined;
  loading: boolean;
  /** The failed request's error, when it failed. */
  error: unknown;
  /** The count cannot be asked for: the list endpoint has no such filter. */
  unavailable: string | undefined;
  /** Opens the list with the count's filters, when the page offers it. */
  onOpen: (() => void) | undefined;
}

/** What the `Counts` slot receives: the tiles of one section, already rendered. */
export interface DashboardCountsProps {
  section: DashboardSection;
  children: React.ReactNode;
}

/** What the `Recent` slot receives: the newest rows of one section. */
export interface DashboardRecentProps {
  section: DashboardSection;
  onOpen: ((row: Row) => void) | undefined;
  onOpenList: (() => void) | undefined;
}

/** What the `Section` slot receives: one model's heading, tiles and table. */
export interface DashboardSectionProps {
  section: DashboardSection;
  /** The `Counts` slot, rendered. */
  counts: React.ReactNode;
  /** The `Recent` slot, rendered, or null when the section shows no rows. */
  recent: React.ReactNode;
  onOpenList: (() => void) | undefined;
}

/** What the `Empty` slot receives: no model opts in (or none the user may see). */
export interface DashboardEmptyProps {
  /** Resources the schema has, none with a declaration. */
  resources: readonly string[];
}

/** What the `Loading` slot receives. */
export interface DashboardLoadingProps {
  /** True once loading has taken longer than SLOW_AFTER_MS: draw the placeholder now. */
  slow: boolean;
}

export interface DashboardSlots {
  Section: React.ComponentType<DashboardSectionProps>;
  Counts: React.ComponentType<DashboardCountsProps>;
  Count: React.ComponentType<DashboardCountProps>;
  Recent: React.ComponentType<DashboardRecentProps>;
  Empty: React.ComponentType<DashboardEmptyProps>;
  Loading: React.ComponentType<DashboardLoadingProps>;
  Error: React.ComponentType<ErrorSlotProps>;
}

export interface DashboardProps {
  /** The resources to show, in this order. Default: every resource with a declaration, by its `order`. */
  resources?: readonly string[];
  /** Rewrites the resolved sections before they render (drop one, rename, add a count). */
  sections?: (sections: readonly DashboardSection[]) => readonly DashboardSection[];
  /** Opens one row (a click in the table). */
  onOpen?: (resource: string, row: Row) => void;
  /** Opens a resource's list, with the filters of the tile that was clicked. */
  onOpenList?: (resource: string, filters: Readonly<Record<string, FilterValue>>) => void;
  /** Today, for relative dates. Default: now. */
  now?: () => Date;
  slots?: Partial<DashboardSlots>;
  className?: string;
}

// relative dates

const RELATIVE_DATE = /^today(?:([+-])(\d+))?$/;

function isoDate(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function daysAgo(now: Date, days: number): Date {
  const date = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  date.setDate(date.getDate() - days);
  return date;
}

type Scalar = string | number | boolean;

function resolveScalar(value: Scalar, now: Date): Scalar {
  if (typeof value !== "string") return value;
  const match = RELATIVE_DATE.exec(value);
  if (match === null) return value;
  const days = match[2] === undefined ? 0 : Number(match[2]) * (match[1] === "-" ? 1 : -1);
  return isoDate(daysAgo(now, days));
}

/**
 * A declared filter value: `"today"`, `"today-7"` and `"today+1"` become the
 * date they name (local time, `YYYY-MM-DD`); anything else is returned as is.
 */
export function resolveRelativeDate(value: FilterValue, now: Date): FilterValue {
  if (Array.isArray(value)) return value.map((item) => resolveScalar(item, now));
  if (value === null || value === undefined) return value;
  return resolveScalar(value as Scalar, now);
}

// sections

function stateLabel(field: FieldDef | undefined, value: string): string {
  const known = field?.enumLabels?.[value];
  if (known !== undefined) return known;
  if (field?.kind === "boolean") return value === "true" ? "Yes" : "No";
  const spaced = value.replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The counts and table of one resource, from its declaration (exported for tests and overrides). */
export function resolveSection(
  resource: string,
  schema: ResourceSchema,
  declaration: DashboardDef,
  now: Date,
): DashboardSection {
  const fields = new Map(schema.fields.map((field) => [field.name, field]));
  const counts: DashboardCount[] = [];
  if (declaration.total) counts.push({ key: "total", label: "All", params: {}, filters: {} });
  if (declaration.newDays > 0 && declaration.dateField !== null) {
    const field = fields.get(declaration.dateField);
    const since = daysAgo(now, declaration.newDays);
    const value = field?.kind === "date" ? isoDate(since) : since.toISOString();
    const params = { [`${declaration.dateField}__gte`]: value };
    counts.push({
      key: "new",
      label: declaration.newDays === 1 ? "New today" : `New in ${declaration.newDays} days`,
      params,
      filters: params,
    });
  }
  if (declaration.by !== null) {
    const field = fields.get(declaration.by);
    for (const value of declaration.values) {
      const params = { [declaration.by]: field?.kind === "boolean" ? value === "true" : value };
      counts.push({ key: `by:${value}`, label: stateLabel(field, value), params, filters: params });
    }
  }
  for (const count of declaration.counts) {
    const params: Record<string, FilterValue> = {};
    for (const [name, value] of Object.entries(count.params)) {
      params[name] = resolveRelativeDate(value, now);
    }
    counts.push({ key: `count:${count.label}`, label: count.label, params, filters: params });
  }
  return {
    resource,
    schema,
    declaration,
    label: declaration.label,
    order: declaration.order,
    counts,
    recent: declaration.recent,
    ordering: declaration.dateField === null ? undefined : `-${declaration.dateField}`,
    columns: declaration.columns,
  };
}

/** The filter the list endpoint does not declare, if any (a count with one would be wrong). */
function undeclaredFilter(section: DashboardSection, count: DashboardCount): string | undefined {
  const declared = section.schema.operations.list?.queryParams;
  if (declared === undefined) return undefined;
  return Object.keys(count.params).find((name) => !declared.includes(name));
}

// default slots

function DefaultCount(props: DashboardCountProps): React.ReactElement | null {
  const { count, value, loading, error, unavailable, onOpen } = props;
  const described = error !== undefined && error !== null ? describeError(error) : undefined;
  if (described?.kind === "forbidden") return null;
  const tile = (
    <Stat
      label={count.label}
      loading={loading}
      value={
        unavailable !== undefined || described !== undefined
          ? "–"
          : (value?.toLocaleString() ?? "–")
      }
      delta={
        unavailable !== undefined ? (
          <span>
            Not a filter of this list: <code className="font-mono text-xs">{unavailable}</code>
          </span>
        ) : described !== undefined ? (
          <span>{described.title}</span>
        ) : undefined
      }
      className={cn("h-full", onOpen !== undefined && "transition-colors hover:bg-accent")}
    />
  );
  if (onOpen === undefined || unavailable !== undefined || described !== undefined) return tile;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      aria-label={`${count.label}: ${value?.toLocaleString() ?? "loading"}. Open the list`}
    >
      {tile}
    </button>
  );
}

function DefaultCounts({ children }: DashboardCountsProps): React.ReactElement {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}

function DefaultRecent({ section, onOpen, onOpenList }: DashboardRecentProps): React.ReactElement {
  const columns = React.useMemo<ReadonlyArray<ResourceColumn> | undefined>(() => {
    if (section.columns === null) return undefined;
    const shown = new Set(section.columns);
    return section.schema.fields
      .filter((field) => !field.writeOnly)
      .map((field) => ({ field: field.name, hidden: !shown.has(field.name) }));
  }, [section]);
  const sorting = React.useMemo(
    () =>
      section.ordering === undefined
        ? undefined
        : [{ id: section.ordering.replace(/^-/, ""), desc: section.ordering.startsWith("-") }],
    [section.ordering],
  );
  return (
    <ResourceTable
      resource={section.resource}
      pageSize={section.recent}
      pageSizeOptions={[section.recent]}
      initialSorting={sorting}
      columns={columns}
      filters={false}
      exportFormats={false}
      viewOptions={false}
      syncUrl={false}
      caption={`Newest ${section.label.toLowerCase()}`}
      onRowClick={onOpen === undefined ? undefined : (row) => onOpen(row)}
      slots={{ Pagination: NoPagination }}
      footer={
        onOpenList !== undefined ? (
          <div className="flex justify-end">
            <Button variant="link" size="sm" onClick={onOpenList}>
              All {section.label.toLowerCase()}
            </Button>
          </div>
        ) : undefined
      }
    />
  );
}

function NoPagination(): null {
  return null;
}

function DefaultSection(props: DashboardSectionProps): React.ReactElement {
  const { section, counts, recent } = props;
  const headingId = React.useId();
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <h2 id={headingId} className="text-lg font-semibold tracking-tight">
        {section.label}
      </h2>
      {counts}
      {recent}
    </section>
  );
}

function DefaultEmpty({ resources }: DashboardEmptyProps): React.ReactElement {
  return (
    <EmptyState
      title="Nothing on the dashboard yet"
      description={
        resources.length === 0
          ? "No model is routed through the API yet. Add one, and give it class Karni: dashboard = True to count and list it here."
          : `Put a model here with class Karni: dashboard = True (${resources.join(", ")}).`
      }
    />
  );
}

function DefaultLoading({ slow }: DashboardLoadingProps): React.ReactElement {
  return (
    <div
      className={cn("space-y-4", !slow && "invisible")}
      aria-hidden="true"
      data-testid="dashboard-skeleton"
    >
      <Skeleton className="h-6 w-32" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-24 w-full" />
        ))}
      </div>
    </div>
  );
}

export const defaultDashboardSlots: DashboardSlots = {
  Section: DefaultSection,
  Counts: DefaultCounts,
  Count: DefaultCount,
  Recent: DefaultRecent,
  Empty: DefaultEmpty,
  Loading: DefaultLoading,
  Error: ErrorState,
};

// one count = one list query with page_size=1

function CountTile(props: {
  section: DashboardSection;
  count: DashboardCount;
  Count: React.ComponentType<DashboardCountProps>;
  onOpenList: DashboardProps["onOpenList"];
}): React.ReactElement | null {
  const { section, count, Count, onOpenList } = props;
  const unavailable = undeclaredFilter(section, count);
  const query = useResourceList(
    section.resource,
    { pageSize: 1, filters: count.params },
    { enabled: unavailable === undefined, retry: false },
  );
  return (
    <Count
      section={section}
      count={count}
      value={query.data?.count}
      loading={unavailable === undefined && query.isPending}
      error={query.error}
      unavailable={unavailable}
      onOpen={
        onOpenList === undefined ? undefined : () => onOpenList(section.resource, count.filters)
      }
    />
  );
}

/** The staff app's home page: a Stat per count and the newest rows of every model that opts in with `Karni.dashboard`. */
export function Dashboard(props: DashboardProps): React.ReactElement {
  const { resources, sections: rewrite, onOpen, onOpenList, now, slots, className } = props;
  const Slots: DashboardSlots = { ...defaultDashboardSlots, ...slots };
  const schemaQuery = useParsedSchema();
  const auth = React.useContext(AuthContext);
  const authStatus = auth?.status;
  const authUser = auth?.user ?? null;
  const identity = React.useMemo(
    () => (authStatus === undefined ? null : { status: authStatus, user: authUser }),
    [authStatus, authUser],
  );
  const parsed = schemaQuery.data;
  const loading = parsed === undefined && schemaQuery.error === null;
  const slow = useDelayedFlag(loading);
  const [today] = React.useState(() => (now ?? (() => new Date()))());

  const sections = React.useMemo<readonly DashboardSection[]>(() => {
    if (parsed === undefined) return [];
    const names = resources ?? Object.keys(parsed.resources);
    const found: DashboardSection[] = [];
    for (const name of names) {
      const schema = parsed.resources[name];
      if (schema?.dashboard === undefined) continue;
      if (evaluateAccess(schema.operations.list?.access, identity) === false) continue;
      found.push(resolveSection(name, schema, schema.dashboard, today));
    }
    if (resources === undefined) {
      found.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
    }
    return rewrite === undefined ? found : rewrite(found);
  }, [parsed, resources, identity, today, rewrite]);

  if (schemaQuery.error !== null && parsed === undefined) {
    return (
      <div className={className}>
        <Slots.Error
          error={schemaQuery.error}
          context={{ action: "load", resource: "the dashboard" }}
          onRetry={() => void schemaQuery.refetch()}
          retrying={schemaQuery.isFetching}
        />
      </div>
    );
  }
  if (parsed === undefined) {
    return (
      <div className={className} aria-busy="true">
        <span role="status" className="sr-only">
          {slow ? "Loading the dashboard…" : ""}
        </span>
        <Slots.Loading slow={slow} />
      </div>
    );
  }
  if (sections.length === 0) {
    return (
      <div className={className}>
        <Slots.Empty resources={Object.keys(parsed.resources).sort()} />
      </div>
    );
  }
  return (
    <div className={cn("space-y-8", className)}>
      {sections.map((section) => {
        const openList =
          onOpenList === undefined ? undefined : () => onOpenList(section.resource, {});
        return (
          <Slots.Section
            key={section.resource}
            section={section}
            onOpenList={openList}
            counts={
              section.counts.length > 0 ? (
                <Slots.Counts section={section}>
                  {section.counts.map((count) => (
                    <CountTile
                      key={count.key}
                      section={section}
                      count={count}
                      Count={Slots.Count}
                      onOpenList={onOpenList}
                    />
                  ))}
                </Slots.Counts>
              ) : null
            }
            recent={
              section.recent > 0 ? (
                <Slots.Recent
                  section={section}
                  onOpen={onOpen === undefined ? undefined : (row) => onOpen(section.resource, row)}
                  onOpenList={openList}
                />
              ) : null
            }
          />
        );
      })}
    </div>
  );
}
