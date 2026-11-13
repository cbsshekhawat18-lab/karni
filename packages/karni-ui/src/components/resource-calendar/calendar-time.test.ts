import { describe, expect, it } from "vitest";
import {
  addDays,
  addMonths,
  atMinutes,
  dayKey,
  formatTime,
  isValidTimeZone,
  minutesIntoDay,
  startOfDay,
  startOfMonth,
  startOfWeek,
  zonedParts,
  zonedTimeToUtc,
  DAY,
} from "./calendar-time";

const BERLIN = "Europe/Berlin";
const NEW_YORK = "America/New_York";

describe("calendar time zones", () => {
  it("reads the wall clock of a zone", () => {
    const ms = Date.UTC(2026, 0, 15, 12, 30);
    expect(zonedParts(ms, BERLIN)).toMatchObject({ day: 15, hour: 13, minute: 30, weekday: 4 });
    expect(zonedParts(ms, NEW_YORK)).toMatchObject({ day: 15, hour: 7, minute: 30 });
  });

  it("turns a wall clock back into an instant, in winter and in summer", () => {
    expect(zonedTimeToUtc(2026, 1, 15, 9, 0, BERLIN)).toBe(Date.UTC(2026, 0, 15, 8, 0));
    expect(zonedTimeToUtc(2026, 7, 15, 9, 0, BERLIN)).toBe(Date.UTC(2026, 6, 15, 7, 0));
  });

  it("keeps a day 23 or 25 hours long where the clocks change", () => {
    const spring = startOfDay(Date.UTC(2026, 2, 8, 12), NEW_YORK);
    expect(addDays(spring, 1, NEW_YORK) - spring).toBe(23 * 60 * 60_000);
    const autumn = startOfDay(Date.UTC(2026, 10, 1, 12), NEW_YORK);
    expect(addDays(autumn, 1, NEW_YORK) - autumn).toBe(25 * 60 * 60_000);
    const plain = startOfDay(Date.UTC(2026, 5, 10, 12), NEW_YORK);
    expect(addDays(plain, 1, NEW_YORK) - plain).toBe(DAY);
  });

  it("puts 9:00 on the wall clock the morning after the change", () => {
    const day = startOfDay(Date.UTC(2026, 2, 9, 12), NEW_YORK);
    expect(minutesIntoDay(atMinutes(day, 9 * 60, NEW_YORK), NEW_YORK)).toBe(540);
  });

  it("finds the day, the week and the month a moment belongs to in that zone", () => {
    const late = Date.UTC(2026, 0, 15, 23, 30);
    expect(dayKey(late, BERLIN)).toBe("2026-01-16");
    expect(dayKey(late, NEW_YORK)).toBe("2026-01-15");
    const monday = startOfWeek(Date.UTC(2026, 0, 15, 12), BERLIN, 1);
    expect(dayKey(monday, BERLIN)).toBe("2026-01-12");
    expect(dayKey(startOfWeek(Date.UTC(2026, 0, 15, 12), BERLIN, 0), BERLIN)).toBe("2026-01-11");
    expect(dayKey(startOfMonth(Date.UTC(2026, 0, 31, 23, 30), BERLIN), BERLIN)).toBe("2026-02-01");
    expect(dayKey(addMonths(Date.UTC(2026, 11, 15), 1, BERLIN), BERLIN)).toBe("2027-01-01");
    expect(dayKey(addMonths(Date.UTC(2026, 0, 15), -1, BERLIN), BERLIN)).toBe("2025-12-01");
  });

  it("formats a time in the zone asked for, and knows a bad zone", () => {
    const ms = Date.UTC(2026, 0, 15, 12, 30);
    expect(formatTime(ms, BERLIN, "en-US")).toMatch(/1:30\s?PM/);
    expect(formatTime(ms, NEW_YORK, "en-US")).toMatch(/7:30\s?AM/);
    expect(isValidTimeZone("Mars/Olympus")).toBe(false);
    expect(isValidTimeZone(BERLIN)).toBe(true);
  });
});
