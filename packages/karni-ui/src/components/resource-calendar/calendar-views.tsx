/**
 * The three ways ResourceCalendar draws its items: a time grid (day and
 * week), a month grid and a list. Internal to @karni/ui: the public surface
 * is ResourceCalendar.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import {
  layoutLanes,
  moveSpan,
  resizeSpan,
  segmentsForDay,
  snapMinutes,
  type CalendarItem,
  type CalendarRange,
  type DaySegment,
  type Span,
} from "./calendar-model";
import {
  addDays,
  atMinutes,
  dayKey,
  formatDay,
  formatFullDay,
  formatTime,
  zoneName,
  zonedParts,
} from "./calendar-time";

type Row = Readonly<Record<string, unknown>>;

/** Experimental. The colour of an event's left edge: a chart colour, or a plain tone. */
export type CalendarTone = "1" | "2" | "3" | "4" | "5" | "primary" | "destructive" | "muted";

const TONE_CLASS: Record<CalendarTone, string> = {
  "1": "border-l-chart-1",
  "2": "border-l-chart-2",
  "3": "border-l-chart-3",
  "4": "border-l-chart-4",
  "5": "border-l-chart-5",
  primary: "border-l-primary",
  destructive: "border-l-destructive",
  muted: "border-l-muted-foreground",
};

/** Experimental. What `renderEvent` receives besides the row. */
export interface CalendarEventContext<T> {
  item: CalendarItem<T>;
  /** "10:00 AM – 11:00 AM", in the zone the calendar shows. */
  time: string;
  /** The state in words, or null without a state field. */
  stateLabel: string | null;
  /** "3 free", "Full" or null without a capacity mapping. */
  capacityLabel: string | null;
  /** True in a month cell or a short block: one line only. */
  compact: boolean;
}

/** What the views share. */
export interface ViewShared<T extends object> {
  items: readonly CalendarItem<T>[];
  /** Open and full slots of the availability source, drawn behind the events. */
  slots: readonly CalendarItem<Row>[];
  range: CalendarRange;
  timeZone: string;
  /** The viewer's zone, for the other time in a tooltip. */
  otherZone: string | null;
  locale: string | undefined;
  slotMinutes: number;
  hours: { start: number; end: number };
  now: number;
  toneOf: (item: CalendarItem<T>) => CalendarTone;
  stateLabelOf: (item: CalendarItem<T>) => string | null;
  labelOf: (row: T) => string;
  renderEvent: ((row: T, context: CalendarEventContext<T>) => React.ReactNode) | undefined;
  canEdit: (item: CalendarItem<T>) => boolean;
  /** Keys of items whose move is being saved. */
  saving: ReadonlySet<string>;
  onOpen: ((row: T) => void) | undefined;
  /** Present when the caller can create: an empty time, or an open slot, was chosen. */
  onCreate: ((span: Span & { allDay: boolean; slot?: Row }) => void) | undefined;
  onReschedule: (item: CalendarItem<T>, span: Span) => void;
  onOpenDay: (day: number) => void;
  onStep: (step: number) => void;
}

function capacityLabelOf<T>(item: CalendarItem<T>): string | null {
  if (item.capacity === null) return null;
  if (item.free === null) return `${item.capacity} places`;
  return item.full ? "Full" : `${item.free} free`;
}

function timeText(ms: number, end: number, timeZone: string, locale: string | undefined): string {
  return `${formatTime(ms, timeZone, locale)} – ${formatTime(end, timeZone, locale)}`;
}

/** Both zones' times, for a tooltip, when the viewer's zone differs. */
function otherTime<T extends object>(
  shared: ViewShared<T>,
  start: number,
  end: number,
): string | undefined {
  if (shared.otherZone === null) return undefined;
  const there = `${timeText(start, end, shared.otherZone, shared.locale)} ${zoneName(start, shared.otherZone, shared.locale)}`;
  const here = `${timeText(start, end, shared.timeZone, shared.locale)} ${zoneName(start, shared.timeZone, shared.locale)}`;
  return `${here} · ${there}`;
}

// --- dragging ---------------------------------------------------------------

type DragMode = "move" | "resize";

interface DragPreview {
  key: string;
  mode: DragMode;
  days: number;
  minutes: number;
}

interface Geometry {
  /** Pixels one day is wide. */
  perDay: number;
  /** Time grid: pixels one minute is tall. Month grid: pixels one week row is tall. */
  perUnit: number;
}

interface DragStart {
  key: string;
  mode: DragMode;
  x: number;
  y: number;
  geometry: Geometry;
  moved: boolean;
}

const DRAG_THRESHOLD = 4;

/**
 * Pointer and keyboard moves of an item. `kind` "time" moves by days and
 * snapped minutes, "month" by days and weeks. A drag shows a preview and
 * commits on release. Keys: Shift and the arrows move, Alt with Up and Down
 * resizes the end (time grid only).
 */
function useScheduleDrag<T extends object>(
  shared: ViewShared<T>,
  kind: "time" | "month",
  measure: () => Geometry | null,
) {
  const { slotMinutes, timeZone, onReschedule } = shared;
  const [preview, setPreview] = React.useState<DragPreview | null>(null);
  const start = React.useRef<DragStart | null>(null);
  const suppressClick = React.useRef(false);

  const spanFor = (item: CalendarItem<T>, drag: DragPreview): Span => {
    const base = { start: item.start, end: item.end };
    return drag.mode === "resize"
      ? resizeSpan(base, drag.minutes, slotMinutes)
      : moveSpan(base, drag.days, drag.minutes, timeZone);
  };

  const delta = (event: React.PointerEvent, from: DragStart): { days: number; minutes: number } => {
    const dx = event.clientX - from.x;
    const dy = event.clientY - from.y;
    if (kind === "month") {
      const weeks = from.geometry.perUnit > 0 ? Math.round(dy / from.geometry.perUnit) : 0;
      return { days: Math.round(dx / from.geometry.perDay) + weeks * 7, minutes: 0 };
    }
    const minutes =
      from.geometry.perUnit > 0 ? snapMinutes(dy / from.geometry.perUnit, slotMinutes) : 0;
    return { days: from.mode === "move" ? Math.round(dx / from.geometry.perDay) : 0, minutes };
  };

  const pointerProps = (item: CalendarItem<T>): React.HTMLAttributes<HTMLElement> => {
    if (!shared.canEdit(item)) return {};
    return {
      onPointerDown: (event) => {
        if (event.button !== 0) return;
        const geometry = measure();
        if (geometry === null || geometry.perDay <= 0) return;
        const target = event.target as HTMLElement;
        const mode: DragMode =
          kind === "time" && target.closest("[data-resize]") !== null ? "resize" : "move";
        start.current = {
          key: item.key,
          mode,
          x: event.clientX,
          y: event.clientY,
          geometry,
          moved: false,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      },
      onPointerMove: (event) => {
        const from = start.current;
        if (from === null || from.key !== item.key) return;
        if (
          !from.moved &&
          Math.hypot(event.clientX - from.x, event.clientY - from.y) < DRAG_THRESHOLD
        )
          return;
        from.moved = true;
        const { days, minutes } = delta(event, from);
        setPreview({ key: item.key, mode: from.mode, days, minutes });
      },
      onPointerUp: (event) => {
        const from = start.current;
        start.current = null;
        if (from === null || from.key !== item.key || !from.moved) return;
        const { days, minutes } = delta(event, from);
        suppressClick.current = true;
        window.setTimeout(() => {
          suppressClick.current = false;
        }, 0);
        setPreview(null);
        if (days !== 0 || minutes !== 0) {
          onReschedule(item, spanFor(item, { key: item.key, mode: from.mode, days, minutes }));
        }
      },
      onPointerCancel: () => {
        start.current = null;
        setPreview(null);
      },
      onKeyDown: (event) => {
        if (event.target !== event.currentTarget) return;
        const step = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
        const side = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
        if (step === 0 && side === 0) return;
        if (event.altKey && kind === "time" && step !== 0) {
          event.preventDefault();
          onReschedule(item, resizeSpan(item, step * slotMinutes, slotMinutes));
        } else if (event.shiftKey) {
          event.preventDefault();
          const span =
            kind === "month"
              ? moveSpan(item, side + step * 7, 0, timeZone)
              : moveSpan(item, side, step * slotMinutes, timeZone);
          onReschedule(item, span);
        }
      },
    };
  };

  return {
    preview,
    spanOf: (item: CalendarItem<T>): Span =>
      preview !== null && preview.key === item.key ? spanFor(item, preview) : item,
    pointerProps,
    /** True right after a drag, so the click that follows it does not open the item. */
    clickWasDrag: (): boolean => suppressClick.current,
  };
}

// --- one event --------------------------------------------------------------

interface EventButtonProps<T extends object> {
  shared: ViewShared<T>;
  item: CalendarItem<T>;
  span: Span;
  compact: boolean;
  className?: string;
  style?: React.CSSProperties;
  resizable?: boolean;
  drag: ReturnType<typeof useScheduleDrag<T>>;
}

function EventButton<T extends object>(props: EventButtonProps<T>): React.ReactElement {
  const { shared, item, span, compact, drag } = props;
  const time = timeText(span.start, span.end, shared.timeZone, shared.locale);
  const stateLabel = shared.stateLabelOf(item);
  const capacityLabel = capacityLabelOf(item);
  const label = shared.labelOf(item.row);
  const editable = shared.canEdit(item);
  const saving = shared.saving.has(item.key);
  const context: CalendarEventContext<T> = { item, time, stateLabel, capacityLabel, compact };
  return (
    <button
      type="button"
      data-event=""
      data-event-key={item.key}
      title={otherTime(shared, span.start, span.end)}
      aria-busy={saving || undefined}
      aria-keyshortcuts={
        editable ? "Shift+ArrowUp Shift+ArrowDown Alt+ArrowUp Alt+ArrowDown" : undefined
      }
      {...drag.pointerProps(item)}
      onClick={() => {
        if (drag.clickWasDrag()) return;
        shared.onOpen?.(item.row);
      }}
      style={props.style}
      className={cn(
        "relative block w-full touch-none overflow-hidden rounded-md border border-l-2 border-border bg-card px-1.5 py-0.5 text-left text-xs text-card-foreground shadow-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
        TONE_CLASS[shared.toneOf(item)],
        item.full && "text-muted-foreground",
        saving && "opacity-60",
        editable && "cursor-grab",
        props.className,
      )}
    >
      {shared.renderEvent !== undefined ? (
        shared.renderEvent(item.row, context)
      ) : compact ? (
        <span className="block truncate">
          <span className="font-medium">
            {formatTime(span.start, shared.timeZone, shared.locale)}
          </span>{" "}
          {label}
          {capacityLabel !== null ? (
            <span className="text-muted-foreground"> · {capacityLabel}</span>
          ) : null}
        </span>
      ) : (
        <>
          <span className="block truncate font-medium">{time}</span>
          <span className="block truncate">{label}</span>
          {stateLabel !== null ? (
            <span className="block truncate text-muted-foreground">{stateLabel}</span>
          ) : null}
          {capacityLabel !== null ? (
            <span className="block truncate text-muted-foreground">{capacityLabel}</span>
          ) : null}
        </>
      )}
      {props.resizable === true && editable ? (
        <span
          data-resize=""
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 h-1.5 cursor-ns-resize"
        />
      ) : null}
    </button>
  );
}

// --- time grid (day and week) ----------------------------------------------

function slotCount(shared: { hours: { start: number; end: number }; slotMinutes: number }): number {
  return Math.round(((shared.hours.end - shared.hours.start) * 60) / shared.slotMinutes);
}

/** Experimental. The day and week views: a column per day, a block per item, an open cell per time. */
export function TimeGrid<T extends object>(props: ViewShared<T>): React.ReactElement {
  const { range, timeZone, locale, hours, slotMinutes, items, slots, now } = props;
  const columns = React.useRef<HTMLDivElement>(null);
  const startMinute = hours.start * 60;
  const spanMinutes = (hours.end - hours.start) * 60;
  const cellCount = slotCount(props);
  const [focused, setFocused] = React.useState<{ day: number; slot: number } | null>(null);
  const drag = useScheduleDrag<T>(props, "time", () => {
    const element = columns.current;
    if (element === null) return null;
    const box = element.getBoundingClientRect();
    return { perDay: box.width / range.days.length, perUnit: box.height / spanMinutes };
  });
  const todayKey = dayKey(now, timeZone);
  const defaultSlot = Math.min(
    cellCount - 1,
    Math.max(0, Math.round((8 * 60 - startMinute) / slotMinutes)),
  );
  const tab = focused ?? { day: 0, slot: defaultSlot };
  const creatable = props.onCreate !== undefined;

  const move = (event: React.KeyboardEvent<HTMLButtonElement>, day: number, slot: number): void => {
    let nextDay = day;
    let nextSlot = slot;
    switch (event.key) {
      case "ArrowUp":
        nextSlot -= 1;
        break;
      case "ArrowDown":
        nextSlot += 1;
        break;
      case "ArrowLeft":
        nextDay -= 1;
        break;
      case "ArrowRight":
        nextDay += 1;
        break;
      case "Home":
        nextSlot = 0;
        break;
      case "End":
        nextSlot = cellCount - 1;
        break;
      case "PageUp":
        event.preventDefault();
        props.onStep(-1);
        return;
      case "PageDown":
        event.preventDefault();
        props.onStep(1);
        return;
      default:
        return;
    }
    event.preventDefault();
    if (nextDay < 0 || nextDay >= range.days.length || nextSlot < 0 || nextSlot >= cellCount)
      return;
    setFocused({ day: nextDay, slot: nextSlot });
    const target = columns.current?.querySelector<HTMLElement>(
      `[data-cell][data-day="${nextDay}"][data-slot="${nextSlot}"]`,
    );
    target?.focus();
  };

  return (
    <div className="relative flex max-h-[var(--karni-calendar-max-height)] min-w-0 overflow-auto rounded-md border border-border bg-background">
      <div
        aria-hidden="true"
        className="sticky left-0 z-raised w-16 shrink-0 bg-background pt-9 text-right text-xs text-muted-foreground"
      >
        {Array.from({ length: hours.end - hours.start }, (_unused, index) => (
          <div key={index} className="h-[var(--karni-calendar-hour-height)] whitespace-nowrap pr-2">
            {formatTime(
              atMinutes(range.days[0] as number, (hours.start + index) * 60, timeZone),
              timeZone,
              locale,
            )}
          </div>
        ))}
      </div>
      <div
        ref={columns}
        className="grid min-w-0 flex-1"
        style={{ gridTemplateColumns: `repeat(${range.days.length}, minmax(7rem, 1fr))` }}
      >
        {range.days.map((day, dayIndex) => {
          const segments = segmentsForDay(items, day, timeZone).filter(
            (segment) =>
              segment.endMinute > startMinute && segment.startMinute < startMinute + spanMinutes,
          );
          const placed = layoutLanes(segments);
          const daySlots = segmentsForDay(slots, day, timeZone);
          const isToday = dayKey(day, timeZone) === todayKey;
          const nowMinute = isToday
            ? zonedParts(now, timeZone).hour * 60 + zonedParts(now, timeZone).minute
            : null;
          return (
            <section
              key={day}
              aria-label={formatFullDay(day, timeZone, locale)}
              className="min-w-0 border-l border-border first:border-l-0"
            >
              <h3
                className={cn(
                  "sticky top-0 z-raised flex h-9 items-center justify-center bg-background text-sm font-medium",
                  isToday && "text-primary",
                )}
              >
                {range.days.length > 1 ? (
                  <button
                    type="button"
                    className="rounded-sm px-1 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => props.onOpenDay(day)}
                  >
                    {formatDay(day, timeZone, locale)}
                  </button>
                ) : (
                  formatDay(day, timeZone, locale)
                )}
              </h3>
              <div
                className="relative h-[calc(var(--karni-calendar-hour-height)*var(--karni-calendar-hours))]"
                style={{ ["--karni-calendar-hours" as string]: hours.end - hours.start }}
              >
                {Array.from({ length: cellCount }, (_unused, slot) => {
                  const minute = startMinute + slot * slotMinutes;
                  const from = atMinutes(day, minute, timeZone);
                  const cellStyle = {
                    height: `calc(var(--karni-calendar-hour-height) * ${slotMinutes / 60})`,
                  };
                  const hourLine = minute % 60 === 0;
                  return creatable ? (
                    <button
                      key={slot}
                      type="button"
                      data-cell=""
                      data-day={dayIndex}
                      data-slot={slot}
                      tabIndex={tab.day === dayIndex && tab.slot === slot ? 0 : -1}
                      aria-label={`New at ${formatTime(from, timeZone, locale)} on ${formatFullDay(day, timeZone, locale)}`}
                      style={cellStyle}
                      onFocus={() => setFocused({ day: dayIndex, slot })}
                      onKeyDown={(event) => move(event, dayIndex, slot)}
                      onClick={() =>
                        props.onCreate?.({
                          start: from,
                          end: atMinutes(day, minute + slotMinutes, timeZone),
                          allDay: false,
                        })
                      }
                      className={cn(
                        "block w-full border-t border-border outline-none hover:bg-muted-subtle focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                        !hourLine && "border-dashed",
                      )}
                    />
                  ) : (
                    <div
                      key={slot}
                      aria-hidden="true"
                      style={cellStyle}
                      className={cn("border-t border-border", !hourLine && "border-dashed")}
                    />
                  );
                })}
                {daySlots
                  .filter(
                    (segment) =>
                      segment.endMinute > startMinute &&
                      segment.startMinute < startMinute + spanMinutes,
                  )
                  .map((segment) => (
                    <SlotBand
                      key={segment.item.key}
                      shared={props}
                      segment={segment}
                      top={startMinute}
                      span={spanMinutes}
                    />
                  ))}
                <ul
                  aria-label={`Events, ${formatFullDay(day, timeZone, locale)}`}
                  className="pointer-events-none absolute inset-0"
                >
                  {placed.map((segment) => {
                    const span = drag.spanOf(segment.item);
                    const live = drag.preview !== null && drag.preview.key === segment.item.key;
                    const shown = live ? clipToDay(span, day, timeZone) : segment;
                    const top = Math.max(0, shown.startMinute - startMinute);
                    const bottom = Math.min(spanMinutes, shown.endMinute - startMinute);
                    return (
                      <li
                        key={segment.item.key}
                        className="pointer-events-auto absolute px-0.5"
                        style={{
                          top: `${(top / spanMinutes) * 100}%`,
                          height: `${(Math.max(bottom - top, slotMinutes / 2) / spanMinutes) * 100}%`,
                          left: `${(segment.lane / segment.lanes) * 100}%`,
                          width: `${100 / segment.lanes}%`,
                        }}
                      >
                        <EventButton
                          shared={props}
                          item={segment.item}
                          span={span}
                          compact={bottom - top <= slotMinutes}
                          resizable={!segment.continuesAfter}
                          drag={drag}
                          className="h-full"
                        />
                      </li>
                    );
                  })}
                </ul>
                {nowMinute !== null &&
                nowMinute >= startMinute &&
                nowMinute < startMinute + spanMinutes ? (
                  <div
                    aria-hidden="true"
                    data-now=""
                    className="pointer-events-none absolute inset-x-0 border-t-2 border-destructive"
                    style={{ top: `${((nowMinute - startMinute) / spanMinutes) * 100}%` }}
                  />
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** A preview span cut to one day, as minutes since its midnight. */
function clipToDay(
  span: Span,
  day: number,
  timeZone: string,
): { startMinute: number; endMinute: number } {
  const next = addDays(day, 1, timeZone);
  const startMs = Math.max(span.start, day);
  const endMs = Math.min(span.end, next);
  const base = zonedParts(day, timeZone);
  const minutes = (ms: number): number => {
    const p = zonedParts(ms, timeZone);
    return ms >= next ? 1440 : p.day === base.day ? p.hour * 60 + p.minute : 0;
  };
  return {
    startMinute: minutes(startMs),
    endMinute: Math.max(minutes(endMs), minutes(startMs) + 1),
  };
}

function SlotBand<T extends object>(props: {
  shared: ViewShared<T>;
  segment: DaySegment<Row>;
  top: number;
  span: number;
}): React.ReactElement {
  const { shared, segment } = props;
  const item = segment.item;
  const start = Math.max(0, segment.startMinute - props.top);
  const end = Math.min(props.span, segment.endMinute - props.top);
  const label = capacityLabelOf(item);
  const text = `${formatTime(item.start, shared.timeZone, shared.locale)} ${label ?? "Open"}`;
  const inner = <span className="block truncate px-1 text-xs text-muted-foreground">{text}</span>;
  const common = {
    style: {
      top: `${(start / props.span) * 100}%`,
      height: `${((end - start) / props.span) * 100}%`,
    },
    className: cn(
      "absolute inset-x-0 overflow-hidden border-l-2 text-left",
      item.full ? "border-l-muted-foreground bg-muted" : "border-l-chart-2 bg-muted-subtle",
    ),
  };
  if (shared.onCreate === undefined || item.full) {
    return (
      <div aria-hidden="true" data-slot-band={item.full ? "full" : "open"} {...common}>
        {inner}
      </div>
    );
  }
  return (
    <button
      type="button"
      data-slot-band="open"
      onClick={() =>
        shared.onCreate?.({ start: item.start, end: item.end, allDay: false, slot: item.row })
      }
      {...common}
      className={cn(
        common.className,
        "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <span className="sr-only">New at </span>
      {inner}
    </button>
  );
}

// --- month grid -------------------------------------------------------------

const MAX_PER_CELL = 3;

/** Experimental. The month view: a cell per day with its items, a few at a time. */
export function MonthGrid<T extends object>(props: ViewShared<T>): React.ReactElement {
  const { range, timeZone, locale, items, slots, now } = props;
  const grid = React.useRef<HTMLDivElement>(null);
  const weeks = range.days.length / 7;
  const drag = useScheduleDrag<T>(props, "month", () => {
    const element = grid.current;
    if (element === null) return null;
    const box = element.getBoundingClientRect();
    return { perDay: box.width / 7, perUnit: box.height / weeks };
  });
  const [focused, setFocused] = React.useState(0);
  const todayKey = dayKey(now, timeZone);
  const focusedIndex = Math.min(focused, range.days.length - 1);
  const month = zonedParts(
    range.days[Math.min(10, range.days.length - 1)] as number,
    timeZone,
  ).month;

  const onCellKey = (event: React.KeyboardEvent<HTMLDivElement>, index: number): void => {
    if (event.target !== event.currentTarget) return;
    let next = index;
    switch (event.key) {
      case "ArrowLeft":
        next -= 1;
        break;
      case "ArrowRight":
        next += 1;
        break;
      case "ArrowUp":
        next -= 7;
        break;
      case "ArrowDown":
        next += 7;
        break;
      case "Home":
        next -= index % 7;
        break;
      case "End":
        next += 6 - (index % 7);
        break;
      case "PageUp":
        event.preventDefault();
        props.onStep(-1);
        return;
      case "PageDown":
        event.preventDefault();
        props.onStep(1);
        return;
      case "Enter":
      case " ":
        event.preventDefault();
        activate(index);
        return;
      default:
        return;
    }
    event.preventDefault();
    if (next < 0 || next >= range.days.length) return;
    setFocused(next);
    grid.current?.querySelector<HTMLElement>(`[data-cell="${next}"]`)?.focus();
  };

  const activate = (index: number): void => {
    const day = range.days[index] as number;
    if (props.onCreate !== undefined) {
      props.onCreate({ start: day, end: addDays(day, 1, timeZone), allDay: true });
    } else {
      props.onOpenDay(day);
    }
  };

  const headings = range.days.slice(0, 7);
  return (
    <div className="relative min-w-0 overflow-x-auto rounded-md border border-border bg-background">
      <div role="grid" aria-label="Month" className="min-w-[var(--karni-calendar-month-min-width)]">
        <div role="row" className="grid grid-cols-7 border-b border-border">
          {headings.map((day) => (
            <div
              key={day}
              role="columnheader"
              className="px-2 py-1 text-center text-xs font-medium text-muted-foreground"
            >
              {new Intl.DateTimeFormat(locale, { timeZone, weekday: "short" }).format(
                new Date(day),
              )}
            </div>
          ))}
        </div>
        <div ref={grid}>
          {Array.from({ length: weeks }, (_unused, week) => (
            <div key={week} role="row" className="grid grid-cols-7">
              {range.days.slice(week * 7, week * 7 + 7).map((day, offset) => {
                const index = week * 7 + offset;
                const segments = segmentsForDay(items, day, timeZone);
                const open = segmentsForDay(slots, day, timeZone).filter(
                  (segment) => !segment.item.full,
                );
                const parts = zonedParts(day, timeZone);
                const shown = segments.slice(0, MAX_PER_CELL);
                const hidden = segments.length - shown.length;
                return (
                  <div
                    key={day}
                    role="gridcell"
                    data-cell={index}
                    data-today={dayKey(day, timeZone) === todayKey ? "" : undefined}
                    tabIndex={index === focusedIndex ? 0 : -1}
                    aria-label={`${formatFullDay(day, timeZone, locale)}, ${segments.length === 1 ? "1 event" : `${segments.length} events`}`}
                    onFocus={(event) => {
                      if (event.target === event.currentTarget) setFocused(index);
                    }}
                    onKeyDown={(event) => onCellKey(event, index)}
                    onClick={(event) => {
                      if (event.target === event.currentTarget) activate(index);
                    }}
                    className={cn(
                      "min-h-24 space-y-1 border-b border-l border-border p-1 outline-none first:border-l-0 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      parts.month !== month && "bg-muted-subtle text-muted-foreground",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={`Open ${formatFullDay(day, timeZone, locale)}`}
                        onClick={() => props.onOpenDay(day)}
                        className={cn(
                          "flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-xs hover:bg-muted",
                          dayKey(day, timeZone) === todayKey &&
                            "bg-primary text-primary-foreground hover:bg-primary-hover",
                        )}
                      >
                        {parts.day}
                      </button>
                      {open.length > 0 ? (
                        <span className="text-xs text-muted-foreground">{open.length} open</span>
                      ) : null}
                    </div>
                    <ul className="space-y-1">
                      {shown.map((segment) => (
                        <li key={segment.item.key}>
                          <EventButton
                            shared={props}
                            item={segment.item}
                            span={drag.spanOf(segment.item)}
                            compact
                            drag={drag}
                          />
                        </li>
                      ))}
                    </ul>
                    {hidden > 0 ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        className="text-xs text-muted-foreground underline underline-offset-4"
                        onClick={() => props.onOpenDay(day)}
                      >
                        {hidden} more
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- list -------------------------------------------------------------------

/** Experimental. The list view, and the phone layout: items by day, in time order, with open slots. */
export function ListView<T extends object>(props: ViewShared<T>): React.ReactElement | null {
  const { range, timeZone, locale, items, slots } = props;
  const days = range.days
    .map((day) => ({
      day,
      segments: segmentsForDay(items, day, timeZone),
      open: segmentsForDay(slots, day, timeZone),
    }))
    .filter((entry) => entry.segments.length > 0 || entry.open.length > 0);
  if (days.length === 0) return null;
  const drag = noDrag<T>();
  return (
    <div className="space-y-4">
      {days.map(({ day, segments, open }) => (
        <section key={day} aria-label={formatFullDay(day, timeZone, locale)} className="space-y-2">
          <h3 className="text-sm font-semibold">{formatFullDay(day, timeZone, locale)}</h3>
          <ul className="space-y-2">
            {segments.map((segment) => (
              <li key={segment.item.key}>
                <EventButton
                  shared={props}
                  item={segment.item}
                  span={segment.item}
                  compact={false}
                  drag={drag}
                />
              </li>
            ))}
            {open.map((segment) => {
              const slot = segment.item;
              const label = capacityLabelOf(slot);
              const text = `${timeText(slot.start, slot.end, timeZone, locale)} ${label ?? "Open"}`;
              return (
                <li key={`slot-${slot.key}`}>
                  {props.onCreate !== undefined && !slot.full ? (
                    <button
                      type="button"
                      data-slot-band="open"
                      className="w-full rounded-md border border-dashed border-border px-2 py-1.5 text-left text-xs hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() =>
                        props.onCreate?.({
                          start: slot.start,
                          end: slot.end,
                          allDay: false,
                          slot: slot.row,
                        })
                      }
                    >
                      <span className="sr-only">New at </span>
                      {text}
                    </button>
                  ) : (
                    <p
                      data-slot-band={slot.full ? "full" : "open"}
                      className="px-2 py-1 text-xs text-muted-foreground"
                    >
                      {text}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** A drag controller that never drags: the list has no moves. */
function noDrag<T extends object>(): ReturnType<typeof useScheduleDrag<T>> {
  return {
    preview: null,
    spanOf: (item: CalendarItem<T>): Span => item,
    pointerProps: () => ({}),
    clickWasDrag: () => false,
  };
}
