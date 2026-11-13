/**
 * The pure part of ResourceCalendar: rows to items, the visible range of a
 * view, items to the day segments a column draws, overlap lanes, and the
 * arithmetic of moving and resizing. Internal to @karni/ui.
 */
import {
  DAY,
  MINUTE,
  addDays,
  addMonths,
  atMinutes,
  minutesIntoDay,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from "./calendar-time";

type Row = Readonly<Record<string, unknown>>;

/** Experimental. The views of ResourceCalendar. */
export type CalendarView = "day" | "week" | "month" | "list";

/** Experimental. Which fields of a row hold how many it takes and how many are taken. */
export interface CalendarCapacity {
  /** The field with how many it holds (a number). */
  capacity: string;
  /** The field with how many are taken. */
  taken?: string;
  /** The field with how many are left (used when there is no `taken`). */
  remaining?: string;
}

/** One row placed in time. */
export interface CalendarItem<T> {
  key: string;
  row: T;
  start: number;
  end: number;
  state: string | null;
  /** Set when the calendar was given a `capacity` mapping. */
  capacity: number | null;
  taken: number | null;
  free: number | null;
  full: boolean;
}

export interface ItemConfig {
  startField: string;
  endField?: string | undefined;
  durationField?: string | undefined;
  defaultDurationMinutes: number;
  stateField?: string | undefined;
  capacity?: CalendarCapacity | undefined;
  getKey: (row: never) => string;
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Rows with a readable start become items. A row without an end lasts its duration, else the default. */
export function toItems<T extends object>(
  rows: readonly T[],
  config: ItemConfig,
): CalendarItem<T>[] {
  const items: CalendarItem<T>[] = [];
  for (const row of rows) {
    const record = row as Row;
    const startRaw = record[config.startField];
    const start = typeof startRaw === "string" ? Date.parse(startRaw) : Number.NaN;
    if (!Number.isFinite(start)) continue;
    let end = Number.NaN;
    if (config.endField !== undefined) {
      const endRaw = record[config.endField];
      end = typeof endRaw === "string" ? Date.parse(endRaw) : Number.NaN;
    }
    if (!Number.isFinite(end) && config.durationField !== undefined) {
      const minutes = toNumber(record[config.durationField]);
      if (minutes !== null) end = start + minutes * MINUTE;
    }
    if (!Number.isFinite(end) || end <= start) end = start + config.defaultDurationMinutes * MINUTE;
    const stateRaw = config.stateField !== undefined ? record[config.stateField] : undefined;
    let capacity: number | null = null;
    let taken: number | null = null;
    let free: number | null = null;
    if (config.capacity !== undefined) {
      capacity = toNumber(record[config.capacity.capacity]);
      if (config.capacity.taken !== undefined) {
        taken = toNumber(record[config.capacity.taken]);
        if (capacity !== null && taken !== null) free = Math.max(0, capacity - taken);
      } else if (config.capacity.remaining !== undefined) {
        free = toNumber(record[config.capacity.remaining]);
        if (capacity !== null && free !== null) taken = Math.max(0, capacity - free);
      }
    }
    items.push({
      key: config.getKey(row as never),
      row,
      start,
      end,
      state: typeof stateRaw === "string" ? stateRaw : null,
      capacity,
      taken,
      free,
      full: free !== null && free <= 0,
    });
  }
  return items.sort((a, b) => a.start - b.start || a.end - b.end);
}

/** What a view shows: its first moment, the moment after its last, and the days it draws. */
export interface CalendarRange {
  start: number;
  end: number;
  /** The midnight of each day drawn, in order. */
  days: number[];
}

/** The range a view shows around `anchor`. A month view draws whole weeks, so the days of the next and last month show. */
export function rangeFor(
  view: CalendarView,
  anchor: number,
  timeZone: string,
  weekStartsOn: number,
): CalendarRange {
  let first: number;
  let count: number;
  if (view === "day") {
    first = startOfDay(anchor, timeZone);
    count = 1;
  } else if (view === "month") {
    const month = startOfMonth(anchor, timeZone);
    first = startOfWeek(month, timeZone, weekStartsOn);
    const next = addMonths(month, 1, timeZone);
    const last = addDays(
      startOfWeek(addDays(next, -1, timeZone), timeZone, weekStartsOn),
      7,
      timeZone,
    );
    count = Math.round((last - first) / DAY);
  } else {
    first = startOfWeek(anchor, timeZone, weekStartsOn);
    count = 7;
  }
  const days: number[] = [];
  for (let index = 0; index < count; index += 1) days.push(addDays(first, index, timeZone));
  return { start: first, end: addDays(first, count, timeZone), days };
}

/** The anchor one step on (or back, with a negative `step`) in a view. */
export function stepAnchor(
  view: CalendarView,
  anchor: number,
  step: number,
  timeZone: string,
): number {
  if (view === "day") return addDays(anchor, step, timeZone);
  if (view === "month") return addMonths(anchor, step, timeZone);
  return addDays(anchor, step * 7, timeZone);
}

/** An item's share of one day. */
export interface DaySegment<T> {
  item: CalendarItem<T>;
  /** The midnight of the day. */
  day: number;
  /** Minutes since midnight where it begins and ends on this day (0 to 1440). */
  startMinute: number;
  endMinute: number;
  /** It began on an earlier day, or goes on to a later one. */
  continuesBefore: boolean;
  continuesAfter: boolean;
}

/** The items' pieces that fall on the day starting at `day`. */
export function segmentsForDay<T>(
  items: readonly CalendarItem<T>[],
  day: number,
  timeZone: string,
): DaySegment<T>[] {
  const next = addDays(day, 1, timeZone);
  const found: DaySegment<T>[] = [];
  for (const item of items) {
    if (item.start >= next || item.end <= day) {
      // A zero-length item cannot happen (toItems gives every item a duration).
      continue;
    }
    const before = item.start < day;
    const after = item.end > next;
    found.push({
      item,
      day,
      startMinute: before ? 0 : minutesIntoDay(item.start, timeZone),
      endMinute: after ? 1440 : Math.max(minutesIntoDay(item.end, timeZone), 1),
      continuesBefore: before,
      continuesAfter: after,
    });
  }
  return found.sort((a, b) => a.startMinute - b.startMinute || a.endMinute - b.endMinute);
}

/** A segment with the lane it sits in and how many lanes share its time. */
export interface LaidOut<T> extends DaySegment<T> {
  lane: number;
  lanes: number;
}

/** Side-by-side lanes for overlapping segments of one day, so none hides another. */
export function layoutLanes<T>(segments: readonly DaySegment<T>[]): LaidOut<T>[] {
  const out: LaidOut<T>[] = [];
  let cluster: LaidOut<T>[] = [];
  let clusterEnd = -1;
  const laneEnds: number[] = [];
  const flush = (): void => {
    for (const placed of cluster) placed.lanes = Math.max(1, laneEnds.length);
    out.push(...cluster);
    cluster = [];
    laneEnds.length = 0;
  };
  for (const segment of segments) {
    if (cluster.length > 0 && segment.startMinute >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= segment.startMinute);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(segment.endMinute);
    } else {
      laneEnds[lane] = segment.endMinute;
    }
    cluster.push({ ...segment, lane, lanes: 1 });
    clusterEnd = cluster.length === 1 ? segment.endMinute : Math.max(clusterEnd, segment.endMinute);
  }
  flush();
  return out;
}

/** A new start and end. */
export interface Span {
  start: number;
  end: number;
}

/**
 * Moves an item by whole days and minutes, keeping its length. The days move
 * on the zone's wall clock, so a 9:00 item stays at 9:00 over a clock change.
 */
export function moveSpan(span: Span, days: number, minutes: number, timeZone: string): Span {
  const length = span.end - span.start;
  const day = addDays(span.start, days, timeZone);
  const start = atMinutes(day, minutesIntoDay(span.start, timeZone) + minutes, timeZone);
  return { start, end: start + length };
}

/** Moves the end by `minutes`, never above the start plus `minimum` minutes. */
export function resizeSpan(span: Span, minutes: number, minimum: number): Span {
  return {
    start: span.start,
    end: Math.max(span.start + minimum * MINUTE, span.end + minutes * MINUTE),
  };
}

/** Rounds `minutes` to the nearest multiple of `step`. */
export function snapMinutes(minutes: number, step: number): number {
  return Math.round(minutes / step) * step;
}
