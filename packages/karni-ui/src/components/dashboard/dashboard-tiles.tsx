/**
 * <DashboardTiles>: the home tiles the signed-in person sees.
 *
 * Reads `GET /dashboard/` (Django's `karni.tiles`): the tiles each installed
 * part declares, in code or in karni.yaml's `dashboard:`, filtered on the
 * server by who may see them. Each tile is a card in a DashboardGrid:
 *
 * - `stat` on a `resource`: the number of its rows matching `filters`, asked
 *   of its list endpoint (`page_size=1`), so the row scope applies.
 * - `stat` with `data.values`: the figures the server worked out (money in
 *   the tile's currency).
 * - `list` on a `resource`: its first `limit` rows matching `filters`, with
 *   `columns`. With `data.rows`: the rows the server gave.
 * - `chart` with `data.points`: a bar or line chart (ChartCard).
 * - `custom`: the component registered for its key (`registerTile`).
 *
 * Escape hatches: `registerTile(key, Component)` draws one tile your way,
 * `registerTileKind(kind, Component)` a whole kind (a project with
 * karni-charts draws `chart` with its own component), `tiles` rewrites the
 * list before it renders, and a home page can compose Stat and
 * ResourceTable itself.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import * as React from "react";
import { AuthContext } from "../../auth/provider";
import { karniKeys } from "../../hooks/keys";
import type { FilterValue } from "../../hooks/types";
import { useResourceList } from "../../hooks/useResourceList";
import { cn } from "../../lib/cn";
import { formatMoney } from "../../lib/money";
import { registerComponentRole } from "../../lib/roles";
import { useKarniClient } from "../../schema/provider";
import { useSchema } from "../../schema/useSchema";
import { describeError } from "../../states/describe-error";
import { ChartCard } from "../dashboard-grid/chart-card";
import { DashboardCard, DashboardGrid } from "../dashboard-grid/dashboard-grid";
import { Button } from "../primitives/button";
import { ResourceTable, type ResourceColumn } from "../resource/ResourceTable";
import { Stat } from "../stat/stat";
import { resolveRelativeDate } from "./dashboard";

registerComponentRole("dashboard-tiles", "DashboardTiles");

/** One figure of a stat tile the server worked out. */
export interface TileValue {
  label: string;
  value: string | number;
  /** `money` (in the tile's currency) or `number`. */
  format: string;
  link: string | null;
}

/** One home tile, as `GET /dashboard/` answers it. */
export interface DashboardTileDef {
  key: string;
  title: string;
  kind: "stat" | "list" | "chart" | "custom";
  size: "third" | "half" | "full";
  order: number;
  description: string;
  link: string | null;
  resource: string | null;
  filters: Record<string, FilterValue>;
  columns: string[];
  limit: number;
  data: Record<string, unknown> | null;
}

/** The body of `GET /dashboard/`. */
export interface DashboardTilesBody {
  tiles: DashboardTileDef[];
}

/** What a tile component receives. */
export interface TileProps {
  tile: DashboardTileDef;
  /** Opens an app path (a tile's link, a row's link). */
  onOpen: ((href: string) => void) | undefined;
  /** Today, for relative dates in filters. */
  now: Date;
}

export const DASHBOARD_PATH = "/dashboard/";

/** The home tiles of the signed-in person (`GET /dashboard/`), cached per user. */
export function useDashboardTiles(): UseQueryResult<DashboardTilesBody> {
  const client = useKarniClient();
  const auth = React.useContext(AuthContext);
  const user = auth?.status === "authenticated" ? (auth.user?.id ?? null) : null;
  return useQuery<DashboardTilesBody>({
    enabled: auth?.status !== "loading",
    queryKey: karniKeys.dashboardTiles(user),
    queryFn: ({ signal }) => client.request<DashboardTilesBody>(DASHBOARD_PATH, { signal }),
  });
}

const BY_KEY = new Map<string, React.ComponentType<TileProps>>();
const BY_KIND = new Map<string, React.ComponentType<TileProps>>();

/** Draw the tile `key` with `Component` (a `custom` tile, or any tile your way). */
export function registerTile(key: string, Component: React.ComponentType<TileProps>): void {
  BY_KEY.set(key, Component);
}

/** Draw every tile of `kind` with `Component` (a chart library of your own). */
export function registerTileKind(kind: string, Component: React.ComponentType<TileProps>): void {
  BY_KIND.set(kind, Component);
}

/** Forget what `registerTile` or `registerTileKind` set (tests). */
export function unregisterTile(key: string): void {
  BY_KEY.delete(key);
  BY_KIND.delete(key);
}

const SPANS = { third: 1, half: 2, full: "full" } as const;

function shown(value: string | number, format: string, currency: string): string {
  if (format === "money" && currency !== "") return formatMoney(value, currency);
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : String(value);
}

function Clickable({
  href,
  onOpen,
  children,
}: {
  href: string | null | undefined;
  onOpen: TileProps["onOpen"];
  children: React.ReactNode;
}): React.ReactElement {
  if (href === null || href === undefined || onOpen === undefined) return <>{children}</>;
  return (
    <button
      type="button"
      onClick={() => onOpen(href)}
      className="block h-full w-full rounded-lg text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}

function resolved(filters: Record<string, FilterValue>, now: Date): Record<string, FilterValue> {
  return Object.fromEntries(
    Object.entries(filters).map(([name, value]) => [name, resolveRelativeDate(value, now)]),
  );
}

function CountTile({ tile, onOpen, now }: TileProps): React.ReactElement {
  const filters = React.useMemo(() => resolved(tile.filters, now), [tile.filters, now]);
  const count = useResourceList(tile.resource ?? "", { filters, pageSize: 1 });
  const failed = count.error !== null && count.error !== undefined;
  return (
    <Clickable href={tile.link} onOpen={onOpen}>
      <Stat
        label={tile.title}
        loading={count.isPending && !failed}
        value={failed ? "–" : (count.data?.count.toLocaleString() ?? "–")}
        delta={
          failed ? <span>{describeError(count.error).title}</span> : tile.description || undefined
        }
        className="h-full"
      />
    </Clickable>
  );
}

function ValuesTile({ tile, onOpen }: TileProps): React.ReactElement {
  const values = (tile.data?.["values"] ?? []) as TileValue[];
  const currency = String(tile.data?.["currency"] ?? "");
  return (
    <DashboardCard
      title={tile.title}
      description={tile.description || undefined}
      span={SPANS[tile.size]}
      actions={
        tile.link !== null && onOpen !== undefined ? (
          <Button variant="link" size="sm" onClick={() => onOpen(tile.link ?? "")}>
            See all
          </Button>
        ) : undefined
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {values.map((value) => (
          <Clickable key={value.label} href={value.link} onOpen={onOpen}>
            <Stat
              label={value.label}
              value={shown(value.value, value.format, currency)}
              className="h-full"
            />
          </Clickable>
        ))}
      </div>
    </DashboardCard>
  );
}

function ResourceListTile({ tile, onOpen, now }: TileProps): React.ReactElement {
  const schema = useSchema(tile.resource ?? "");
  const filters = React.useMemo(() => resolved(tile.filters, now), [tile.filters, now]);
  const columns = React.useMemo<ReadonlyArray<ResourceColumn> | undefined>(() => {
    if (tile.columns.length === 0 || schema.data === undefined) return undefined;
    const wanted = new Set(tile.columns);
    return schema.data.fields
      .filter((field) => !field.writeOnly)
      .map((field) => ({ field: field.name, hidden: !wanted.has(field.name) }));
  }, [tile.columns, schema.data]);
  return (
    <DashboardCard
      title={tile.title}
      description={tile.description || undefined}
      span={SPANS[tile.size]}
    >
      <ResourceTable
        resource={tile.resource ?? ""}
        params={filters as Record<string, string>}
        pageSize={tile.limit}
        pageSizeOptions={[tile.limit]}
        columns={columns}
        filters={false}
        exportFormats={false}
        viewOptions={false}
        syncUrl={false}
        caption={tile.title}
        slots={{ Pagination: () => null }}
        footer={
          tile.link !== null && onOpen !== undefined ? (
            <div className="flex justify-end">
              <Button variant="link" size="sm" onClick={() => onOpen(tile.link ?? "")}>
                See all
              </Button>
            </div>
          ) : undefined
        }
      />
    </DashboardCard>
  );
}

interface DataColumn {
  key: string;
  label: string;
  format: string;
}

function RowsTile({ tile, onOpen }: TileProps): React.ReactElement {
  const columns = (tile.data?.["columns"] ?? []) as DataColumn[];
  const rows = (tile.data?.["rows"] ?? []) as Array<Record<string, unknown>>;
  const currency = String(tile.data?.["currency"] ?? "");
  return (
    <DashboardCard
      title={tile.title}
      description={tile.description || undefined}
      span={SPANS[tile.size]}
      empty={rows.length === 0}
      actions={
        tile.link !== null && onOpen !== undefined ? (
          <Button variant="link" size="sm" onClick={() => onOpen(tile.link ?? "")}>
            See all
          </Button>
        ) : undefined
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{tile.title}</caption>
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn("py-2 pr-3 font-medium", column.format === "money" && "text-right")}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const link = typeof row["link"] === "string" ? row["link"] : null;
              return (
                <tr key={index} className="border-b border-border last:border-0">
                  {columns.map((column, position) => {
                    const raw = row[column.key];
                    const text =
                      raw === null || raw === undefined
                        ? "–"
                        : column.format === "money"
                          ? shown(raw as string, "money", currency)
                          : String(raw);
                    return (
                      <td
                        key={column.key}
                        className={cn(
                          "py-2 pr-3",
                          column.format === "money" && "text-right tabular-nums",
                        )}
                      >
                        {position === 0 && link !== null && onOpen !== undefined ? (
                          <a
                            href={link}
                            className="font-medium text-primary underline-offset-4 hover:underline"
                            onClick={(event) => {
                              event.preventDefault();
                              onOpen(link);
                            }}
                          >
                            {text}
                          </a>
                        ) : (
                          text
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </DashboardCard>
  );
}

interface ChartPoint {
  label: string;
  value: string | number;
}

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A day on a chart's axis: its number, with the month on the first point and each 1st. */
function dayLabel(label: string, index: number): string {
  const match = ISO_DAY.exec(label);
  if (match === null) return label;
  const day = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  if (index === 0 || day.getDate() === 1) {
    return day.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  return String(day.getDate());
}

function ChartTile({ tile }: TileProps): React.ReactElement {
  const money = tile.data?.["format"] === "money";
  const currency = String(tile.data?.["currency"] ?? "");
  const kind = tile.data?.["kind"] === "line" ? "line" : "bar";
  const raw = tile.data?.["points"];
  const data = React.useMemo(
    () =>
      ((raw ?? []) as ChartPoint[]).map((point, index) => ({
        label: dayLabel(point.label, index),
        value: Number(point.value),
      })),
    [raw],
  );
  return (
    <ChartCard
      title={tile.title}
      description={tile.description || undefined}
      kind={kind}
      data={data}
      span={SPANS[tile.size]}
      valueFormatter={
        money && currency !== "" ? (value) => formatMoney(value, currency) : undefined
      }
    />
  );
}

function DefaultTile(props: TileProps): React.ReactElement | null {
  const { tile } = props;
  const Kind = BY_KIND.get(tile.kind);
  if (Kind !== undefined) return <Kind {...props} />;
  if (tile.kind === "stat") {
    if (tile.resource !== null) {
      return (
        <div
          className={cn(
            tile.size === "half" && "md:col-span-2",
            tile.size === "full" && "col-span-full",
          )}
        >
          <CountTile {...props} />
        </div>
      );
    }
    return <ValuesTile {...props} />;
  }
  if (tile.kind === "list") {
    return tile.resource !== null ? <ResourceListTile {...props} /> : <RowsTile {...props} />;
  }
  if (tile.kind === "chart") return <ChartTile {...props} />;
  return null;
}

export interface DashboardTilesProps {
  /** Opens an app path: a tile's or a row's link (default: none, the tiles do not link). */
  onOpen?: (href: string) => void;
  /** Rewrites the tiles before they render (drop one, change its order). */
  tiles?: (tiles: readonly DashboardTileDef[]) => readonly DashboardTileDef[];
  /** Shown when the person sees no tile. */
  empty?: React.ReactNode;
  /** Today, for relative dates. Default: now. */
  now?: () => Date;
  className?: string;
}

/** Experimental. The home tiles of the signed-in person, in a responsive grid. */
export function DashboardTiles(props: DashboardTilesProps): React.ReactElement | null {
  const { onOpen, tiles, empty = null, now, className } = props;
  const query = useDashboardTiles();
  const today = React.useMemo(() => (now ?? (() => new Date()))(), [now]);
  if (query.isPending) {
    return (
      <DashboardGrid columns={4} className={className}>
        <DashboardCard title="Loading" loading span="full" />
      </DashboardGrid>
    );
  }
  if (query.isError) {
    return (
      <DashboardGrid columns={4} className={className}>
        <DashboardCard
          title="Home"
          span="full"
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      </DashboardGrid>
    );
  }
  const list = tiles !== undefined ? tiles(query.data.tiles) : query.data.tiles;
  if (list.length === 0) return <>{empty}</>;
  return (
    <DashboardGrid columns={4} className={className} data-karni-role="dashboard-tiles">
      {list.map((tile) => {
        const Own = BY_KEY.get(tile.key);
        const props: TileProps = { tile, onOpen, now: today };
        return Own !== undefined ? (
          <Own key={tile.key} {...props} />
        ) : (
          <DefaultTile key={tile.key} {...props} />
        );
      })}
    </DashboardGrid>
  );
}
