/**
 * ResourceBoard: a resource's rows in columns by a state field.
 *
 * A pipeline is a board, not a table: deals by stage, orders by status,
 * bookings by state. One column per choice of the state field, in the order
 * the state machine flows (from the initial state along the transitions,
 * closed states last, the declared order of the choices only breaking ties),
 * a card per row, and the count (and the sum of a money field) of each column
 * in its header:
 *
 *   <ResourceBoard<Deal>
 *     resource="deals"
 *     field="stage"
 *     totalField="value"
 *     renderCard={(deal) => <DealCard deal={deal} />}
 *     onOpen={(deal) => navigate(`/deals/${deal.id}`)}
 *   />
 *
 * A card moves only where the schema lets it: the states `x-karni-transitions`
 * lists for its current state, through the declared row action
 * (`x-karni-actions`) that makes the move when there is one, else a PATCH of
 * the field. A move shows at once and rolls back when the server refuses,
 * with the server's own sentence. Drag a card to a column, or use the keyboard
 * (arrows move between cards, Shift+Left and Shift+Right move the card, Enter
 * opens it) or the "Move to" menu of each card (the way on a phone).
 *
 * Override / escape hatch: `renderCard` is the card body, `canMove` narrows
 * the legal moves, `columns` picks and orders the columns, `slots` replaces
 * the Loading, Empty (a column with no cards), Error and ColumnHeader, and
 * `onMove` hears every move that succeeded.
 */
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { AuthContext } from "../../auth/provider";
import { karniKeys } from "../../hooks/keys";
import { detailPath } from "../../hooks/params";
import type { FilterValue } from "../../hooks/types";
import { useResourceList } from "../../hooks/useResourceList";
import { useResourceMutations } from "../../hooks/useResourceMutations";
import { cn } from "../../lib/cn";
import { formatMoney } from "../../lib/money";
import { registerComponentRole } from "../../lib/roles";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import type { FieldDef } from "../../schema/types";
import { useSchema } from "../../schema/useSchema";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { TransitionFailure, transitionError } from "../resource/detail/transitions";
import { displayLabel } from "../resource/displayLabel";
import { moneyCurrency } from "../resource/number-value";
import { Skeleton } from "../primitives/skeleton";
import {
  boardColumns,
  boardField,
  resolveMove,
  sumField,
  type BoardColumnDef,
  type BoardMove,
} from "./board-model";

registerComponentRole("resource-board", "ResourceBoard");

type Row = Record<string, unknown>;

/** What `renderCard` receives besides the row. */
export interface ResourceBoardCardContext {
  column: BoardColumnDef;
  /** True while this card's move is being saved. */
  moving: boolean;
}

/** What the `ColumnHeader` slot receives. */
export interface ResourceBoardHeaderProps {
  column: BoardColumnDef;
  /** Rows in the column (all of them, not only the loaded ones). */
  count: number;
  /** The formatted sum of `totalField` over the loaded rows, or null without `totalField`. */
  total: string | null;
  /** True when more rows exist than are loaded, so the total covers only some. */
  partial: boolean;
}

/** What the `Empty` slot (a column without cards) receives. */
export interface ResourceBoardEmptyProps {
  column: BoardColumnDef;
}

/** What the `Loading` slot receives. */
export interface ResourceBoardLoadingProps {
  /** How many columns to draw placeholders for. */
  columns: number;
}

/** The replaceable parts of ResourceBoard. */
export interface ResourceBoardSlots {
  Loading: React.ComponentType<ResourceBoardLoadingProps>;
  Empty: React.ComponentType<ResourceBoardEmptyProps>;
  Error: React.ComponentType<ErrorSlotProps>;
  ColumnHeader: React.ComponentType<ResourceBoardHeaderProps>;
}

/** Props of ResourceBoard. */
export interface ResourceBoardProps<T extends object> {
  /** The router prefix of the resource (`deals`). */
  resource: string;
  /** The state field the columns come from. Default: the first field with transitions. */
  field?: string;
  /** The card body of one row. */
  renderCard: (row: T, context: ResourceBoardCardContext) => React.ReactNode;
  /** A row's key. Default: its `id`. */
  getRowKey?: (row: T) => string;
  /** The card's name for assistive technology. Default: the row's name, title or id. */
  getCardLabel?: (row: T) => string;
  /** Show only these states, in this order. Default: every choice. */
  columns?: readonly string[];
  /** A money (or number) field whose sum each column's header shows. */
  totalField?: string;
  /** Fixed list parameters the page decides: an owner, a date range. */
  filters?: Record<string, FilterValue>;
  /** Relation paths to expand. */
  expand?: readonly string[];
  /** Cards loaded per column before "Show more". Default 25. */
  pageSize?: number;
  /** Narrows the legal moves further (the schema's rules always apply). */
  canMove?: (row: T, from: string, to: string) => boolean;
  /** Called after a move the server accepted. */
  onMove?: (row: T, from: string, to: string) => void;
  /** Called when a card is activated (Enter, or a click on its open button). */
  onOpen?: (row: T) => void;
  /** The board's name for assistive technology. Default "Board". */
  label?: string;
  className?: string;
  slots?: Partial<ResourceBoardSlots>;
}

const COLUMN_WIDTH = "w-72";

function DefaultLoading({ columns }: ResourceBoardLoadingProps): React.ReactElement {
  return (
    <div aria-hidden="true" className="flex gap-3 overflow-hidden">
      {Array.from({ length: columns }, (_unused, index) => (
        <div
          key={index}
          className={cn(COLUMN_WIDTH, "shrink-0 space-y-3 rounded-lg border border-border p-3")}
        >
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ))}
    </div>
  );
}

function DefaultEmpty(): React.ReactElement {
  return <p className="px-1 py-4 text-center text-sm text-muted-foreground">Nothing here</p>;
}

function DefaultError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} />;
}

function DefaultColumnHeader({
  column,
  count,
  total,
  partial,
}: ResourceBoardHeaderProps): React.ReactElement {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="min-w-0 truncate text-sm font-semibold text-foreground">{column.label}</span>
      <span className="shrink-0 text-xs text-muted-foreground">
        <span>{count.toLocaleString()}</span>
        {total !== null ? (
          <span>
            {" "}
            · {total}
            {partial ? "+" : ""}
          </span>
        ) : null}
      </span>
    </div>
  );
}

/** Karni's own slots, to wrap one instead of rewriting it. */
export const defaultResourceBoardSlots: ResourceBoardSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: DefaultError,
  ColumnHeader: DefaultColumnHeader,
};

function rowKeyOf(row: unknown): string {
  if (row && typeof row === "object" && "id" in row) return String((row as { id: unknown }).id);
  return JSON.stringify(row);
}

/** The sentence a refused move is shown with: the server's `detail`, a field's message, or plain words. */
function moveErrorMessage(error: unknown, fieldName: string): string {
  if (error instanceof KarniApiError && typeof error.data === "object" && error.data !== null) {
    const detail = (error.data as Record<string, unknown>)["detail"];
    if (typeof detail === "string" && detail.trim() !== "") {
      return detail.replace(/\s*See https?:\/\/\S+\s*$/, "").replace(/^[A-Z]+\d+:\s*/, "");
    }
  }
  return transitionError(error, fieldName);
}

interface Pending {
  from: string;
  to: string;
  row: Row;
}

interface DragState {
  key: string;
  row: Row;
  from: string;
}

interface ColumnProps<T extends object> {
  column: BoardColumnDef;
  resource: string;
  field: FieldDef;
  totalField: FieldDef | undefined;
  filters: Record<string, FilterValue> | undefined;
  expand: readonly string[] | undefined;
  pageSize: number;
  pending: ReadonlyMap<string, Pending>;
  moveOf: (row: Row, target: string) => BoardMove | null;
  targetsOf: (row: Row) => BoardColumnDef[];
  drag: DragState | null;
  setDrag: (drag: DragState | null) => void;
  onDropTo: (row: Row, target: string) => void;
  moveTo: (row: Row, target: string) => void;
  tabKey: string | null;
  setTabKey: (key: string) => void;
  renderCard: ResourceBoardProps<T>["renderCard"];
  getRowKey: (row: T) => string;
  getCardLabel: (row: T) => string;
  onOpen: ((row: T) => void) | undefined;
  onCardKey: (event: React.KeyboardEvent<HTMLElement>, row: Row) => void;
  slots: ResourceBoardSlots;
}

function BoardColumn<T extends object>(props: ColumnProps<T>): React.ReactElement {
  const { column, resource, field, totalField, pending, drag, slots } = props;
  const [limit, setLimit] = React.useState(props.pageSize);
  const list = useResourceList<T>(resource, {
    pageSize: limit,
    filters: { ...props.filters, [field.name]: column.value },
    expand: props.expand,
  });
  const loaded = (list.data?.results ?? []) as T[];
  const arriving: T[] = [];
  const leaving = new Set<string>();
  for (const [key, move] of pending) {
    if (move.from === column.value) leaving.add(key);
    if (move.to === column.value) arriving.push(move.row as T);
  }
  const arrivingKeys = new Set(arriving.map((row) => props.getRowKey(row)));
  const rows: T[] = [
    ...arriving,
    ...loaded.filter((row) => {
      const key = props.getRowKey(row);
      return !leaving.has(key) && !arrivingKeys.has(key);
    }),
  ];
  const count = Math.max(
    0,
    (list.data?.count ?? 0) +
      arriving.length -
      loaded.filter((r) => leaving.has(props.getRowKey(r))).length,
  );
  const partial = list.data !== undefined && list.data.count > loaded.length;
  const currency =
    totalField?.money !== undefined
      ? moneyCurrency(totalField, rows[0] as Row | undefined)
      : undefined;
  let total: string | null = null;
  if (totalField !== undefined) {
    const sum = sumField(rows as Row[], totalField.name);
    total =
      currency !== undefined
        ? formatMoney(sum, currency)
        : sum.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  const dragAllowed = drag !== null && props.moveOf(drag.row, column.value) !== null;
  const dragHere = drag !== null && drag.from !== column.value;
  const Header = slots.ColumnHeader;
  const Empty = slots.Empty;

  let body: React.ReactNode;
  if (list.isPending) {
    body = <Skeleton className="h-16 w-full" />;
  } else if (list.isError && list.data === undefined) {
    body = (
      <slots.Error
        error={list.error}
        context={{ action: "view", resource }}
        onRetry={() => void list.refetch()}
        retrying={list.isFetching}
      />
    );
  } else if (rows.length === 0) {
    body = <Empty column={column} />;
  } else {
    body = (
      <ul aria-label={column.label} className="space-y-2">
        {rows.map((row, index) => {
          const key = props.getRowKey(row);
          const cardLabel = props.getCardLabel(row);
          const targets = props.targetsOf(row as Row);
          const moving = pending.has(key);
          const tabbable = props.tabKey === null ? index === 0 : props.tabKey === key;
          return (
            <li key={key}>
              <article
                data-card=""
                data-card-key={key}
                data-column-value={column.value}
                aria-label={cardLabel}
                aria-busy={moving || undefined}
                tabIndex={tabbable ? 0 : -1}
                draggable={targets.length > 0 && !moving}
                onFocus={(event) => {
                  if (event.target === event.currentTarget) props.setTabKey(key);
                }}
                onKeyDown={(event) => props.onCardKey(event, row as Row)}
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", key);
                  props.setDrag({ key, row: row as Row, from: column.value });
                }}
                onDragEnd={() => props.setDrag(null)}
                className={cn(
                  "space-y-2 rounded-md border border-border bg-card p-3 text-sm text-card-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  targets.length > 0 && "cursor-grab",
                  moving && "opacity-60",
                  drag?.key === key && "opacity-50",
                )}
              >
                {props.renderCard(row, { column, moving })}
                {props.onOpen !== undefined || targets.length > 0 ? (
                  <div className="flex items-center gap-2">
                    {props.onOpen !== undefined ? (
                      <button
                        type="button"
                        className="text-xs font-medium text-foreground underline underline-offset-4"
                        onClick={() => props.onOpen?.(row)}
                      >
                        Open
                        <span className="sr-only"> {cardLabel}</span>
                      </button>
                    ) : null}
                    {targets.length > 0 ? (
                      <select
                        aria-label={`Move ${cardLabel} to`}
                        value=""
                        disabled={moving}
                        className="ml-auto h-7 max-w-40 rounded-md border border-input bg-background px-1 text-xs"
                        onChange={(event) => {
                          if (event.target.value !== "")
                            props.moveTo(row as Row, event.target.value);
                        }}
                      >
                        <option value="">Move to…</option>
                        {targets.map((target) => (
                          <option key={target.value} value={target.value}>
                            {target.label}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </div>
                ) : null}
              </article>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section
      aria-label={column.label}
      data-column={column.value}
      data-drop={drag === null ? undefined : dragAllowed ? "allowed" : "refused"}
      onDragOver={(event) => {
        if (drag === null) return;
        if (dragAllowed && dragHere) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        } else {
          event.dataTransfer.dropEffect = "none";
        }
      }}
      onDrop={(event) => {
        if (drag === null || !dragHere) return;
        event.preventDefault();
        props.onDropTo(drag.row, column.value);
        props.setDrag(null);
      }}
      className={cn(
        COLUMN_WIDTH,
        "flex max-h-[var(--karni-board-max-height)] shrink-0 snap-start flex-col gap-2 rounded-lg border border-border bg-muted-subtle p-3",
        drag !== null && dragHere && dragAllowed && "ring-2 ring-ring",
        drag !== null && dragHere && !dragAllowed && "opacity-50",
      )}
    >
      <Header column={column} count={count} total={total} partial={partial} />
      <div
        className="min-h-0 flex-1 space-y-2 overflow-y-auto"
        aria-busy={list.isFetching || undefined}
      >
        {body}
        {partial ? (
          <button
            type="button"
            className="w-full rounded-md border border-border py-1 text-xs text-muted-foreground hover:bg-muted"
            disabled={list.isFetching}
            onClick={() => setLimit((current) => current + props.pageSize)}
          >
            Show more
            <span className="sr-only"> {column.label}</span>
          </button>
        ) : null}
      </div>
    </section>
  );
}

/** Experimental. A resource's rows in columns by a state field, with legal moves by drag, keyboard or menu. */
export function ResourceBoard<T extends object>(props: ResourceBoardProps<T>): React.ReactElement {
  const {
    resource,
    renderCard,
    getRowKey = rowKeyOf,
    columns,
    totalField: totalName,
    filters,
    expand,
    pageSize = 25,
    canMove,
    onMove,
    onOpen,
    label = "Board",
    className,
  } = props;
  const slots: ResourceBoardSlots = { ...defaultResourceBoardSlots, ...props.slots };
  const schemaResult = useSchema(resource);
  const schema = schemaResult.data;
  const { update } = useResourceMutations(resource);
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const auth = React.useContext(AuthContext);
  const authStatus = auth?.status;
  const authUser = auth?.user ?? null;
  const identity = React.useMemo(
    () => (authStatus === undefined ? null : { status: authStatus, user: authUser }),
    [authStatus, authUser],
  );

  const field = schema !== undefined ? boardField(schema, props.field) : undefined;
  const columnDefs = React.useMemo(
    () => (field !== undefined ? boardColumns(field, columns) : []),
    [field, columns],
  );
  const totalField =
    totalName !== undefined
      ? schema?.fields.find((candidate) => candidate.name === totalName)
      : undefined;

  const [pending, setPending] = React.useState<ReadonlyMap<string, Pending>>(new Map());
  const [drag, setDrag] = React.useState<DragState | null>(null);
  const [tabKey, setTabKey] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<{
    kind: "failure" | "done";
    title: string;
    message: string;
  } | null>(null);
  const root = React.useRef<HTMLDivElement>(null);
  const focusKey = React.useRef<string | null>(null);

  const getCardLabel =
    props.getCardLabel ?? ((row: T): string => displayLabel(row as Row) || getRowKey(row));

  const moveOf = (row: Row, target: string): BoardMove | null => {
    if (schema === undefined || field === undefined) return null;
    const from = row[field.name];
    if (typeof from !== "string") return null;
    if (canMove !== undefined && !canMove(row as T, from, target)) return null;
    return resolveMove(schema, field, row, target, identity);
  };
  const targetsOf = (row: Row): BoardColumnDef[] =>
    columnDefs.filter((column) => moveOf(row, column.value) !== null);

  // After a card is moved from the keyboard, keep focus on it in its new column.
  React.useLayoutEffect(() => {
    const key = focusKey.current;
    if (key === null) return;
    const element = Array.from(
      root.current?.querySelectorAll<HTMLElement>("[data-card-key]") ?? [],
    ).find((node) => node.dataset["cardKey"] === key);
    if (element !== undefined) {
      focusKey.current = null;
      element.focus();
    }
  });

  const moveTo = async (row: Row, target: string): Promise<void> => {
    if (field === undefined) return;
    const from = String(row[field.name]);
    const move = moveOf(row, target);
    const name = getCardLabel(row as T);
    const targetLabel = columnDefs.find((column) => column.value === target)?.label ?? target;
    if (move === null) {
      const fromLabel = columnDefs.find((column) => column.value === from)?.label ?? from;
      setNotice({
        kind: "failure",
        title: `Couldn't move ${name} to ${targetLabel}`,
        message: `It can't move from ${fromLabel} to ${targetLabel}.`,
      });
      return;
    }
    const key = getRowKey(row as T);
    setNotice(null);
    setPending((previous) =>
      new Map(previous).set(key, { from, to: target, row: { ...row, [field.name]: target } }),
    );
    try {
      if (move.via === "action") {
        await client.request(`${detailPath(resource, key)}${encodeURIComponent(move.action)}/`, {
          method: "POST",
        });
        await queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) });
      } else {
        await update.mutateAsync({ id: key, values: { [field.name]: target } });
      }
      setNotice({ kind: "done", title: "", message: `Moved ${name} to ${targetLabel}.` });
      onMove?.(row as T, from, target);
    } catch (error) {
      setNotice({
        kind: "failure",
        title: `Couldn't move ${name} to ${targetLabel}`,
        message: moveErrorMessage(error, field.name),
      });
    } finally {
      setPending((previous) => {
        const next = new Map(previous);
        next.delete(key);
        return next;
      });
    }
  };

  const handleCardKey = (event: React.KeyboardEvent<HTMLElement>, row: Row): void => {
    const target = event.currentTarget;
    if (event.target !== target) return;
    const current = target.dataset["columnValue"] ?? "";
    const cards = (value: string): HTMLElement[] =>
      Array.from(
        root.current?.querySelectorAll<HTMLElement>(
          `[data-column="${CSS.escape(value)}"] [data-card]`,
        ) ?? [],
      );
    const here = cards(current);
    const index = here.indexOf(target);
    const focusCard = (node: HTMLElement | undefined): void => {
      if (node === undefined) return;
      event.preventDefault();
      node.focus();
    };
    const values = columnDefs.map((column) => column.value);
    const at = values.indexOf(current);
    switch (event.key) {
      case "ArrowDown":
        focusCard(here[index + 1]);
        return;
      case "ArrowUp":
        focusCard(here[index - 1]);
        return;
      case "Home":
        focusCard(here[0]);
        return;
      case "End":
        focusCard(here[here.length - 1]);
        return;
      case "Enter":
        if (onOpen !== undefined) {
          event.preventDefault();
          onOpen(row as T);
        }
        return;
      case "ArrowLeft":
      case "ArrowRight": {
        const step = event.key === "ArrowLeft" ? -1 : 1;
        if (event.shiftKey) {
          event.preventDefault();
          for (let i = at + step; i >= 0 && i < values.length; i += step) {
            const candidate = values[i] as string;
            if (moveOf(row, candidate) !== null) {
              focusKey.current = getRowKey(row as T);
              void moveTo(row, candidate);
              return;
            }
          }
          return;
        }
        for (let i = at + step; i >= 0 && i < values.length; i += step) {
          const there = cards(values[i] as string);
          if (there.length > 0) {
            focusCard(there[Math.min(index, there.length - 1)]);
            return;
          }
        }
        return;
      }
      default:
        return;
    }
  };

  if (schemaResult.error != null && schema === undefined) {
    return (
      <slots.Error
        error={schemaResult.error}
        context={{ action: "view", resource }}
        onRetry={schemaResult.refetch}
        retrying={schemaResult.isFetching}
      />
    );
  }
  if (schema === undefined) return <slots.Loading columns={4} />;
  if (field === undefined || columnDefs.length === 0) {
    return (
      <div
        role="alert"
        className="rounded-md border border-border p-4 text-sm text-muted-foreground"
      >
        {props.field !== undefined
          ? `${resource} has no field "${props.field}" with choices, so it cannot be shown as a board.`
          : `${resource} has no state field, so it cannot be shown as a board.`}
      </div>
    );
  }

  return (
    <div className={cn("min-w-0 max-w-full space-y-3", className)}>
      {notice?.kind === "failure" ? (
        <TransitionFailure title={notice.title} message={notice.message} />
      ) : null}
      <div
        ref={root}
        role="group"
        aria-label={label}
        // relative: the cards' hidden labels (sr-only, absolute) are clipped here, never widen the page
        className="relative flex max-w-full snap-x gap-3 overflow-x-auto overscroll-x-contain pb-2"
      >
        {columnDefs.map((column) => (
          <BoardColumn<T>
            key={column.value}
            column={column}
            resource={resource}
            field={field}
            totalField={totalField}
            filters={filters}
            expand={expand}
            pageSize={pageSize}
            pending={pending}
            moveOf={moveOf}
            targetsOf={targetsOf}
            drag={drag}
            setDrag={setDrag}
            onDropTo={(row, to) => void moveTo(row, to)}
            moveTo={(row, to) => void moveTo(row, to)}
            tabKey={tabKey}
            setTabKey={setTabKey}
            renderCard={renderCard}
            onCardKey={handleCardKey}
            getRowKey={getRowKey}
            getCardLabel={getCardLabel}
            onOpen={onOpen}
            slots={slots}
          />
        ))}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {notice?.kind === "done" ? notice.message : ""}
      </span>
    </div>
  );
}
