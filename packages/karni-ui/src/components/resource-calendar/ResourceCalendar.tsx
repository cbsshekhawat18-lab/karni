/**
 * Experimental. ResourceCalendar: a resource's rows on a day, week or month
 * calendar, or as a list.
 *
 * Anything with a start and an end (or a start and a duration) is a calendar:
 * bookings, appointments, shifts, sessions, deliveries, activities due.
 *
 *   <ResourceCalendar<Slot>
 *     resource="slots"
 *     startField="starts_at"
 *     endField="ends_at"
 *     stateField="status"
 *     capacity={{ capacity: "capacity", remaining: "remaining" }}
 *     timeZone="Europe/Berlin"
 *     onSelectEvent={(slot) => navigate(`/slots/${slot.id}`)}
 *     onCreate={({ start, end }) => openNewBooking(start, end)}
 *   />
 *
 * It reads one range of `GET /<resource>/` for the view's dates, through the
 * list's `<startField>__lte` and `<endField>__gte` filters (the start field
 * alone, widened by a day, without an end field). Events carry the colour of
 * their state field's value and its label in words. With `capacity`, each
 * event says how many places are free and a full one is marked Full. With
 * `availability` a second resource's slots (a capacity and what is taken)
 * show behind the events: open ones can be clicked to create.
 *
 * Time zones: `timeZone` is the business zone the times are shown in
 * (default: the viewer's). When the viewer's zone differs a switch changes
 * between the two and a tooltip gives both times.
 *
 * Clicking an empty time calls `onCreate`. Clicking an event calls
 * `onSelectEvent`. Dragging an event moves it and dragging its bottom edge
 * resizes it, when the caller may: `canEdit`, else the schema (the start
 * field is writable and the update rule does not refuse, or the declared row
 * action `rescheduleAction` is open for the row). The change is PATCHed (or
 * handed to `onReschedule`), shows at once and rolls back with the server's
 * own sentence when it is refused. Keyboard: Tab to an event, Shift and the
 * arrows move it, Alt with Up and Down resizes it, Enter opens it. In the
 * time grid the arrows walk the empty times, Enter creates, Page Up and Page
 * Down change the period. At phone width the calendar is a list.
 *
 * Override / escape hatch: `renderEvent` is the event body, `onReschedule`
 * replaces the PATCH, `canEdit` replaces the permission check, `stateTones`
 * picks the colours, `slots` replaces Loading, Empty and Error, and `view`,
 * `date` are controlled when given.
 */
import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { AuthContext } from "../../auth/provider";
import { karniKeys } from "../../hooks/keys";
import { detailPath } from "../../hooks/params";
import type { FilterValue } from "../../hooks/types";
import { useResourceList } from "../../hooks/useResourceList";
import { useResourceMutations } from "../../hooks/useResourceMutations";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { rowActionOpen } from "../../schema/parse";
import { useResourceSchemaIfKnown } from "../../schema/useSchema";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { Button } from "../primitives/button";
import { Skeleton } from "../primitives/skeleton";
import { EmptyState } from "../empty-state/empty-state";
import { TransitionFailure } from "../resource/detail/transitions";
import { displayLabel, relationLabel } from "../resource/displayLabel";
import { singularNoun } from "../resource/nouns";
import { evaluateAccess } from "../resource/table/access";
import { useContainerWidth } from "../resource/table/use-container-width";
import {
  rangeFor,
  stepAnchor,
  toItems,
  type CalendarCapacity,
  type CalendarItem,
  type CalendarView,
  type Span,
} from "./calendar-model";
import {
  DAY,
  formatMonth,
  formatFullDay,
  isValidTimeZone,
  startOfDay,
  viewerTimeZone,
  zoneName,
} from "./calendar-time";
import {
  ListView,
  MonthGrid,
  TimeGrid,
  type CalendarEventContext,
  type CalendarTone,
  type ViewShared,
} from "./calendar-views";

registerComponentRole("resource-calendar", "ResourceCalendar");

export type { CalendarCapacity, CalendarView } from "./calendar-model";
export type { CalendarEventContext, CalendarTone } from "./calendar-views";

type Row = Record<string, unknown>;

/** Experimental. A second resource whose rows are open or full slots, drawn behind the events. */
export interface CalendarAvailability extends CalendarCapacity {
  /** The slots' resource (`slots`). */
  resource: string;
  startField: string;
  endField?: string;
  /** Fixed list parameters for the slots (a room, a service). */
  filters?: Record<string, FilterValue>;
}

/** Experimental. What `onCreate` receives: an empty time, or an open slot of `availability`. */
export interface CalendarCreateRequest {
  start: Date;
  end: Date;
  /** True for a click on a month cell: the whole day. */
  allDay: boolean;
  /** The availability row, when an open slot was clicked. */
  slot?: Row;
}

/** Experimental. What the `Empty` slot receives. */
export interface CalendarEmptyProps {
  /** The range shown, in words ("March 2026"). */
  period: string;
}

/** Experimental. What the `Loading` slot receives. */
export interface CalendarLoadingProps {
  view: CalendarView;
}

/** Experimental. The replaceable parts of ResourceCalendar. */
export interface ResourceCalendarSlots {
  Loading: React.ComponentType<CalendarLoadingProps>;
  Empty: React.ComponentType<CalendarEmptyProps>;
  Error: React.ComponentType<ErrorSlotProps>;
}

/** Experimental. Props of ResourceCalendar. */
export interface ResourceCalendarProps<T extends object> {
  /** The router prefix of the resource (`bookings`). */
  resource: string;
  /** The field with the start (a datetime). */
  startField: string;
  /** The field with the end. Without one, `durationField`, else `defaultDurationMinutes`. */
  endField?: string;
  /** A field with the length in minutes, used when a row has no end. */
  durationField?: string;
  /** How long a row lasts when it has neither. Default 60. */
  defaultDurationMinutes?: number;
  /** A state field: events show its label and take a colour from its value. */
  stateField?: string;
  /** Colours by state value. Default: the chart colours in the order of the field's choices. */
  stateTones?: Readonly<Record<string, CalendarTone>>;
  /** Fields with how many places a row holds and how many are taken or left. */
  capacity?: CalendarCapacity;
  /** Slots of another resource, drawn behind the events. */
  availability?: CalendarAvailability;
  /** Fixed list parameters the page decides: a room, a staff member. */
  filters?: Record<string, FilterValue>;
  /** Relation paths to expand. */
  expand?: readonly string[];
  /** The business zone times are shown in (an IANA name). Default: the viewer's. */
  timeZone?: string;
  /** Locale of dates and times. Default: the browser's. */
  locale?: string;
  /** The view (controlled). */
  view?: CalendarView;
  onViewChange?: (view: CalendarView) => void;
  /** The first view. Default "week". */
  defaultView?: CalendarView;
  /** Which views the switch offers. Default day, week, month and list. */
  views?: readonly CalendarView[];
  /** A day in the period shown (controlled). */
  date?: Date;
  onDateChange?: (date: Date) => void;
  /** 0 is Sunday, 1 is Monday. Default 1. */
  weekStartsOn?: 0 | 1;
  /** Minutes one empty cell, and one step of a move or resize, spans. Default 30. */
  slotMinutes?: 15 | 30 | 60;
  /** The hours the time grid shows. Default 0 to 24. */
  hours?: { start: number; end: number };
  /** Most rows loaded for one range. Default 200. */
  limit?: number;
  /** The event body. */
  renderEvent?: (row: T, context: CalendarEventContext<T>) => React.ReactNode;
  /**
   * An event's name. Default: its name or title, an expanded relation's (a slot's
   * resource), else the resource in words (never its key).
   */
  getEventLabel?: (row: T) => string;
  /** A row's key. Default: its `id`. */
  getRowKey?: (row: T) => string;
  /** Called when an event is clicked or opened with Enter. */
  onSelectEvent?: (row: T) => void;
  /** Called when an empty time, a month cell or an open slot is chosen. Without it nothing can be created. */
  onCreate?: (request: CalendarCreateRequest) => void;
  /** The label of the toolbar's create button. Default "New". */
  createLabel?: string;
  /** Whether the caller may move or resize this row. Default: from the schema. */
  canEdit?: (row: T) => boolean;
  /** Called to move or resize a row, instead of the PATCH. Throw to refuse: the change rolls back. */
  onReschedule?: (row: T, change: { start: Date; end: Date }) => void | Promise<void>;
  /** A declared row action (`x-karni-actions`) that reschedules: POSTed with the new start and end. */
  rescheduleAction?: string;
  /** More controls in the toolbar. */
  toolbar?: React.ReactNode;
  /** The calendar's name for assistive technology. Default "Calendar". */
  label?: string;
  className?: string;
  slots?: Partial<ResourceCalendarSlots>;
}

const ALL_VIEWS: readonly CalendarView[] = ["day", "week", "month", "list"];
const VIEW_LABEL: Record<CalendarView, string> = {
  day: "Day",
  week: "Week",
  month: "Month",
  list: "List",
};
const PHONE_WIDTH = 640;

function DefaultLoading({ view }: CalendarLoadingProps): React.ReactElement {
  return (
    <div aria-hidden="true" data-view={view} className="space-y-2">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function DefaultEmpty({ period }: CalendarEmptyProps): React.ReactElement {
  return <EmptyState title="Nothing scheduled" description={`Nothing falls in ${period}.`} />;
}

function DefaultError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} />;
}

/** Experimental. Karni's own slots, to wrap one instead of rewriting it. */
export const defaultResourceCalendarSlots: ResourceCalendarSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: DefaultError,
};

function rowKeyOf(row: unknown): string {
  if (row && typeof row === "object" && "id" in row) return String((row as { id: unknown }).id);
  return JSON.stringify(row);
}

/** The sentence a refused change is shown with. */
function scheduleError(error: unknown, fields: readonly string[]): string {
  if (error instanceof KarniApiError && typeof error.data === "object" && error.data !== null) {
    const data = error.data as Record<string, unknown>;
    for (const name of [...fields, "detail", "non_field_errors"]) {
      const found = data[name];
      const first = Array.isArray(found) ? found[0] : found;
      if (typeof first === "string" && first.trim() !== "") {
        return first.replace(/\s*See https?:\/\/\S+\s*$/, "").replace(/^[A-Z]+\d+:\s*/, "");
      }
    }
  }
  return error instanceof Error && !(error instanceof KarniApiError)
    ? error.message
    : "The server refused the change.";
}

function useMaybeControlled<V>(
  given: V | undefined,
  initial: V,
  onChange?: (value: V) => void,
): [V, (value: V) => void] {
  const [own, setOwn] = React.useState<V>(given ?? initial);
  const set = React.useCallback(
    (next: V) => {
      setOwn(next);
      onChange?.(next);
    },
    [onChange],
  );
  return [given ?? own, set];
}

const TONE_ORDER: readonly CalendarTone[] = ["1", "2", "3", "4", "5"];

/** Experimental. A resource's rows on a day, week or month calendar, with free and full slots, moves and resizes. */
export function ResourceCalendar<T extends object>(
  props: ResourceCalendarProps<T>,
): React.ReactElement {
  const {
    resource,
    startField,
    endField,
    durationField,
    defaultDurationMinutes = 60,
    stateField,
    capacity,
    availability,
    filters,
    expand,
    locale,
    weekStartsOn = 1,
    slotMinutes = 30,
    limit = 200,
    getRowKey = rowKeyOf,
    onSelectEvent,
    onCreate,
    createLabel = "New",
    rescheduleAction,
    label = "Calendar",
    className,
  } = props;
  const slots: ResourceCalendarSlots = { ...defaultResourceCalendarSlots, ...props.slots };
  const hours = props.hours ?? { start: 0, end: 24 };
  const viewerZone = React.useMemo(() => viewerTimeZone(), []);
  const businessZone =
    props.timeZone !== undefined && isValidTimeZone(props.timeZone) ? props.timeZone : viewerZone;
  const zonesDiffer = businessZone !== viewerZone;
  const [zoneChoice, setZoneChoice] = React.useState<"business" | "viewer">("business");
  const timeZone = zonesDiffer && zoneChoice === "viewer" ? viewerZone : businessZone;
  const otherZone = zonesDiffer ? (timeZone === businessZone ? viewerZone : businessZone) : null;

  const allowed = props.views ?? ALL_VIEWS;
  const [chosen, setView] = useMaybeControlled<CalendarView>(
    props.view,
    props.defaultView ?? "week",
    props.onViewChange,
  );
  const [anchorDate, setAnchorDate] = useMaybeControlled<Date>(
    props.date,
    new Date(),
    props.onDateChange,
  );
  const anchor = anchorDate.getTime();

  const frame = React.useRef<HTMLDivElement>(null);
  const width = useContainerWidth(frame);
  const phone = width !== undefined && width < PHONE_WIDTH;
  const shownView: CalendarView = phone ? "list" : chosen;
  // A list reads a week, a phone reads the period of the view the person chose.
  const rangeView: CalendarView =
    shownView === "list" ? (phone && chosen !== "list" ? chosen : "week") : shownView;
  const range = React.useMemo(
    () => rangeFor(rangeView, anchor, timeZone, weekStartsOn),
    [rangeView, anchor, timeZone, weekStartsOn],
  );

  const schema = useResourceSchemaIfKnown(resource);
  const stateDef =
    stateField !== undefined
      ? schema?.fields.find((field) => field.name === stateField)
      : undefined;
  const now = Date.now();

  // --- data ---------------------------------------------------------------
  const rangeFilters = (start: string, end: string | undefined): Record<string, FilterValue> => {
    const lower = new Date(range.start - (end === undefined ? DAY : 0)).toISOString();
    return {
      [`${start}__lte`]: new Date(range.end).toISOString(),
      [`${end ?? start}__gte`]: lower,
    };
  };
  const list = useResourceList<T>(
    resource,
    {
      pageSize: limit,
      ordering: startField,
      filters: { ...filters, ...rangeFilters(startField, endField) },
      expand,
    },
    { placeholderData: keepPreviousData },
  );
  const slotList = useResourceList<Row>(
    availability?.resource ?? resource,
    {
      pageSize: limit,
      ordering: availability?.startField ?? startField,
      filters: {
        ...availability?.filters,
        ...rangeFilters(availability?.startField ?? startField, availability?.endField),
      },
    },
    { enabled: availability !== undefined, placeholderData: keepPreviousData },
  );

  // --- rescheduling -------------------------------------------------------
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { update } = useResourceMutations(resource);
  const [overrides, setOverrides] = React.useState<ReadonlyMap<string, Span>>(new Map());
  const [failure, setFailure] = React.useState<{ title: string; message: string } | null>(null);
  const [announcement, setAnnouncement] = React.useState("");
  const auth = React.useContext(AuthContext);
  const authStatus = auth?.status;
  const authUser = auth?.user ?? null;
  const identity = React.useMemo(
    () => (authStatus === undefined ? null : { status: authStatus, user: authUser }),
    [authStatus, authUser],
  );

  // A row's own name, else an expanded relation's (a slot's resource), else the resource in
  // words: never a raw key, which says nothing to a person (the state shows beside it).
  const defaultLabel = (row: T): string => {
    const record = row as Row;
    const own = displayLabel({ ...record, id: undefined });
    if (own !== "") return own;
    for (const field of schema?.fields ?? []) {
      const value = record[field.name];
      if (field.relation !== undefined && value !== null && typeof value === "object") {
        const named = relationLabel(field, value as Row);
        if (named !== "") return named;
      }
    }
    const noun = singularNoun(resource);
    return noun.charAt(0).toUpperCase() + noun.slice(1);
  };
  const getLabel = props.getEventLabel ?? defaultLabel;
  const itemConfig = {
    startField,
    endField,
    durationField,
    defaultDurationMinutes,
    stateField,
    capacity,
    getKey: getRowKey as (row: never) => string,
  };
  const baseItems = React.useMemo(
    () => toItems<T>(list.data?.results ?? [], itemConfig),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- itemConfig is rebuilt from these
    [
      list.data,
      startField,
      endField,
      durationField,
      defaultDurationMinutes,
      stateField,
      capacity,
      getRowKey,
    ],
  );
  const items: CalendarItem<T>[] = baseItems.map((item) => {
    const over = overrides.get(item.key);
    return over === undefined ? item : { ...item, start: over.start, end: over.end };
  });
  const slotItems = React.useMemo(
    () =>
      availability === undefined
        ? []
        : toItems<Row>(slotList.data?.results ?? [], {
            startField: availability.startField,
            endField: availability.endField,
            defaultDurationMinutes,
            capacity: availability,
            getKey: rowKeyOf as (row: never) => string,
          }),
    [availability, slotList.data, defaultDurationMinutes],
  );

  const canEditItem = (item: CalendarItem<T>): boolean => {
    if (props.canEdit !== undefined) return props.canEdit(item.row);
    if (schema === undefined) return false;
    const row = item.row as Row;
    if (rescheduleAction !== undefined) {
      const declared = schema.rowActions?.[rescheduleAction];
      if (declared === undefined) return false;
      if (rowActionOpen(schema, rescheduleAction, row) === false) return false;
      return declared.by === null || evaluateAccess(declared.by, identity, row) !== false;
    }
    if (props.onReschedule !== undefined) return true;
    const fields = [startField, endField ?? durationField].filter(
      (name): name is string => name !== undefined,
    );
    const writable = fields.every(
      (name) => schema.fields.find((field) => field.name === name)?.readOnly === false,
    );
    return writable && evaluateAccess(schema.operations.update?.access, identity, row) !== false;
  };

  const reschedule = async (item: CalendarItem<T>, span: Span): Promise<void> => {
    if (span.start === item.start && span.end === item.end) return;
    const name = getLabel(item.row);
    const change = { start: new Date(span.start), end: new Date(span.end) };
    setFailure(null);
    setOverrides((previous) => new Map(previous).set(item.key, span));
    try {
      if (props.onReschedule !== undefined) {
        await props.onReschedule(item.row, change);
      } else if (rescheduleAction !== undefined) {
        const body: Row = { [startField]: change.start.toISOString() };
        if (endField !== undefined) body[endField] = change.end.toISOString();
        else if (durationField !== undefined)
          body[durationField] = Math.round((span.end - span.start) / 60_000);
        await client.request(
          `${detailPath(resource, item.key)}${encodeURIComponent(rescheduleAction)}/`,
          {
            method: "POST",
            body,
          },
        );
        await queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) });
      } else {
        const values: Row = { [startField]: change.start.toISOString() };
        if (endField !== undefined) values[endField] = change.end.toISOString();
        else if (durationField !== undefined)
          values[durationField] = Math.round((span.end - span.start) / 60_000);
        await update.mutateAsync({ id: item.key, values });
      }
      setAnnouncement(`Moved ${name} to ${formatFullDay(span.start, timeZone, locale)}.`);
    } catch (error) {
      setFailure({
        title: `Couldn't change ${name}`,
        message: scheduleError(error, [startField, endField ?? durationField ?? startField]),
      });
    } finally {
      setOverrides((previous) => {
        const next = new Map(previous);
        next.delete(item.key);
        return next;
      });
    }
  };

  // --- navigation ---------------------------------------------------------
  const step = (direction: number): void =>
    setAnchorDate(new Date(stepAnchor(rangeView, anchor, direction, timeZone)));
  const openDay = (day: number): void => {
    setAnchorDate(new Date(day));
    if (allowed.includes("day")) setView("day");
  };
  const period =
    rangeView === "month"
      ? formatMonth(anchor, timeZone, locale)
      : rangeView === "day"
        ? formatFullDay(anchor, timeZone, locale)
        : `${formatFullDay(range.start, timeZone, locale)} to ${formatFullDay(range.end - DAY / 2, timeZone, locale)}`;

  // --- what each event looks like -------------------------------------------
  const toneOf = (item: CalendarItem<T>): CalendarTone => {
    if (item.state === null) return "primary";
    const given = props.stateTones?.[item.state];
    if (given !== undefined) return given;
    const index = stateDef?.enumValues?.map(String).indexOf(item.state) ?? -1;
    return TONE_ORDER[(index < 0 ? 0 : index) % TONE_ORDER.length] ?? "1";
  };
  const stateLabelOf = (item: CalendarItem<T>): string | null => {
    if (item.state === null) return null;
    const known = stateDef?.enumLabels?.[item.state];
    if (known !== undefined) return known;
    const spaced = item.state.replace(/[_-]+/g, " ");
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  };

  const shared: ViewShared<T> = {
    items,
    slots: slotItems,
    range,
    timeZone,
    otherZone,
    locale,
    slotMinutes,
    hours,
    now,
    toneOf,
    stateLabelOf,
    labelOf: getLabel,
    renderEvent: props.renderEvent,
    canEdit: canEditItem,
    saving: new Set(overrides.keys()),
    onOpen: onSelectEvent,
    onCreate:
      onCreate === undefined
        ? undefined
        : (request) =>
            onCreate({
              start: new Date(request.start),
              end: new Date(request.end),
              allDay: request.allDay,
              ...(request.slot !== undefined ? { slot: request.slot as Row } : {}),
            }),
    onReschedule: (item, span) => void reschedule(item, span),
    onOpenDay: openDay,
    onStep: step,
  };

  // --- body ---------------------------------------------------------------
  const failed = list.isError && list.data === undefined;
  let body: React.ReactNode;
  if (failed) {
    body = (
      <slots.Error
        error={list.error}
        context={{ action: "view", resource }}
        onRetry={() => void list.refetch()}
        retrying={list.isFetching}
      />
    );
  } else if (list.isPending) {
    body = <slots.Loading view={shownView} />;
  } else if (shownView === "list") {
    body =
      items.length === 0 && slotItems.length === 0 ? (
        <slots.Empty period={period} />
      ) : (
        <ListView {...shared} />
      );
  } else if (shownView === "month") {
    body = <MonthGrid {...shared} />;
  } else {
    body = <TimeGrid {...shared} />;
  }

  const total = list.data?.count ?? 0;
  const loaded = list.data?.results.length ?? 0;
  const startOfToday = startOfDay(now, timeZone);

  return (
    <div
      ref={frame}
      className={cn("min-w-0 max-w-full space-y-3", className)}
      aria-busy={list.isFetching || undefined}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Period" className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={() => step(-1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAnchorDate(new Date(startOfToday))}>
            Today
          </Button>
          <Button variant="outline" size="sm" onClick={() => step(1)}>
            Next
          </Button>
        </div>
        <h2 className="min-w-0 flex-1 text-base font-semibold" aria-live="polite">
          {period}
        </h2>
        {allowed.length > 1 ? (
          <div role="group" aria-label="View" className="flex items-center gap-1">
            {allowed.map((name) => (
              <Button
                key={name}
                size="sm"
                variant={chosen === name ? "default" : "outline"}
                aria-pressed={chosen === name}
                onClick={() => setView(name)}
              >
                {VIEW_LABEL[name]}
              </Button>
            ))}
          </div>
        ) : null}
        {onCreate !== undefined ? (
          <Button
            size="sm"
            onClick={() => {
              const start = startOfDay(Math.max(anchor, now), timeZone) + 9 * 60 * 60_000;
              onCreate({
                start: new Date(start),
                end: new Date(start + slotMinutes * 60_000),
                allDay: false,
              });
            }}
          >
            {createLabel}
          </Button>
        ) : null}
        {props.toolbar}
      </div>
      {zonesDiffer ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>
            Times in {timeZone.replace(/_/g, " ")} ({zoneName(now, timeZone, locale)})
          </span>
          <div role="group" aria-label="Time zone" className="flex items-center gap-1">
            <Button
              size="sm"
              variant={zoneChoice === "business" ? "default" : "outline"}
              aria-pressed={zoneChoice === "business"}
              onClick={() => setZoneChoice("business")}
            >
              Business time
            </Button>
            <Button
              size="sm"
              variant={zoneChoice === "viewer" ? "default" : "outline"}
              aria-pressed={zoneChoice === "viewer"}
              onClick={() => setZoneChoice("viewer")}
            >
              My time
            </Button>
          </div>
        </div>
      ) : null}
      {failure !== null ? (
        <TransitionFailure title={failure.title} message={failure.message} />
      ) : null}
      <div role="region" aria-label={label}>
        {body}
      </div>
      {!failed && total > loaded ? (
        <p className="text-xs text-muted-foreground">
          Showing the first {loaded.toLocaleString()} of {total.toLocaleString()}. Narrow the period
          or add a filter to see the rest.
        </p>
      ) : null}
      <span className="sr-only" role="status" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}
