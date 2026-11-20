/**
 * Time zone arithmetic for ResourceCalendar, with `Intl` and no library.
 *
 * Every instant is a number of milliseconds since the epoch. A "day" is a day
 * in a named IANA zone, so a day can be 23 or 25 hours long where the clocks
 * change. Internal to @karni/ui.
 */

export const MINUTE = 60_000;
export const DAY = 24 * 60 * MINUTE;

/** A moment as the wall clock of a zone shows it. */
export interface ZonedParts {
  year: number;
  /** 1 to 12. */
  month: number;
  day: number;
  hour: number;
  minute: number;
  /** 0 is Sunday. */
  weekday: number;
}

const WEEKDAYS: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(timeZone: string): Intl.DateTimeFormat {
  let found = formatters.get(timeZone);
  if (found === undefined) {
    found = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      weekday: "short",
    });
    formatters.set(timeZone, found);
  }
  return found;
}

/** Whether `timeZone` is a zone this browser knows. */
export function isValidTimeZone(timeZone: string): boolean {
  try {
    formatterFor(timeZone);
    return true;
  } catch {
    return false;
  }
}

/** The viewer's own zone. */
export function viewerTimeZone(): string {
  try {
    return new Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** The wall clock of `timeZone` at the instant `ms`. */
export function zonedParts(ms: number, timeZone: string): ZonedParts {
  const parts = formatterFor(timeZone).formatToParts(new Date(ms));
  const value = (type: string): string => parts.find((part) => part.type === type)?.value ?? "0";
  return {
    year: Number(value("year")),
    month: Number(value("month")),
    day: Number(value("day")),
    hour: Number(value("hour")) % 24,
    minute: Number(value("minute")),
    weekday: WEEKDAYS[value("weekday")] ?? 0,
  };
}

function offsetAt(ms: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - Math.floor(ms / MINUTE) * MINUTE;
}

/** The instant at which a zone's wall clock reads this date and time. Month and day may overflow (day 32 is next month). */
export function zonedTimeToUtc(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): number {
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  const first = guess - offsetAt(guess, timeZone);
  const second = guess - offsetAt(first, timeZone);
  return second;
}

/** `2026-03-08`: the day `ms` falls on in the zone. */
export function dayKey(ms: number, timeZone: string): string {
  const p = zonedParts(ms, timeZone);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

/** Midnight at the start of the zone's day that holds `ms`. */
export function startOfDay(ms: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return zonedTimeToUtc(p.year, p.month, p.day, 0, 0, timeZone);
}

/** Midnight `days` calendar days after the day holding `ms` (negative: before). */
export function addDays(ms: number, days: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return zonedTimeToUtc(p.year, p.month, p.day + days, 0, 0, timeZone);
}

/** The first day of the week holding `ms`. `weekStartsOn` is 0 (Sunday) or 1 (Monday). */
export function startOfWeek(ms: number, timeZone: string, weekStartsOn: number): number {
  const p = zonedParts(ms, timeZone);
  const back = (p.weekday - weekStartsOn + 7) % 7;
  return zonedTimeToUtc(p.year, p.month, p.day - back, 0, 0, timeZone);
}

/** The first day of the month holding `ms`. */
export function startOfMonth(ms: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return zonedTimeToUtc(p.year, p.month, 1, 0, 0, timeZone);
}

/** The first day of the month `months` after the one holding `ms`. */
export function addMonths(ms: number, months: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return zonedTimeToUtc(p.year, p.month + months, 1, 0, 0, timeZone);
}

/** Minutes since the zone's midnight (wall clock). */
export function minutesIntoDay(ms: number, timeZone: string): number {
  const p = zonedParts(ms, timeZone);
  return p.hour * 60 + p.minute;
}

/** The instant `minutes` after the zone's midnight of the day holding `dayMs` (wall clock, so DST-safe). */
export function atMinutes(dayMs: number, minutes: number, timeZone: string): number {
  const p = zonedParts(dayMs, timeZone);
  return zonedTimeToUtc(p.year, p.month, p.day, 0, minutes, timeZone);
}

/** The time of day, as people read it in `locale` ("9:00 AM"). */
export function formatTime(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(ms));
}

/** A day, as a heading ("Mon, Mar 9"). */
export function formatDay(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(ms));
}

/** A month and year ("March 2026"). */
export function formatMonth(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, month: "long", year: "numeric" }).format(
    new Date(ms),
  );
}

/** A full date with weekday ("Monday, March 9, 2026"). */
export function formatFullDay(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, dateStyle: "full" }).format(new Date(ms));
}

/** A zone's short name at an instant ("CET", "GMT+1"), for a note beside a time. */
export function zoneName(ms: number, timeZone: string, locale?: string): string {
  const part = new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "short" })
    .formatToParts(new Date(ms))
    .find((item) => item.type === "timeZoneName");
  return part?.value ?? timeZone;
}
