import { describe, expect, it } from "vitest";
import {
  layoutLanes,
  moveSpan,
  rangeFor,
  resizeSpan,
  segmentsForDay,
  snapMinutes,
  stepAnchor,
  toItems,
  type CalendarItem,
} from "./calendar-model";
import { addDays, dayKey, startOfDay, MINUTE } from "./calendar-time";

const TZ = "Europe/Berlin";
const at = (iso: string): number => Date.parse(iso);

const config = {
  startField: "starts_at",
  endField: "ends_at",
  defaultDurationMinutes: 60,
  stateField: "status",
  getKey: (row: { id: number }) => String(row.id),
};

describe("toItems", () => {
  it("reads start and end, a start and a duration, and a bare start", () => {
    const items = toItems(
      [
        {
          id: 1,
          starts_at: "2026-03-02T09:00:00Z",
          ends_at: "2026-03-02T10:30:00Z",
          status: "open",
        },
        { id: 2, starts_at: "2026-03-02T08:00:00Z", length: 45 },
        { id: 3, starts_at: "2026-03-02T07:00:00Z" },
        { id: 4, starts_at: "not a date" },
      ],
      { ...config, durationField: "length" },
    );
    expect(items.map((item) => [item.key, (item.end - item.start) / MINUTE])).toEqual([
      ["3", 60],
      ["2", 45],
      ["1", 90],
    ]);
    expect(items[2]?.state).toBe("open");
  });

  it("reads capacity from taken or from remaining, and marks a full slot", () => {
    const rows = [
      { id: 1, starts_at: "2026-03-02T09:00:00Z", cap: 4, booked: 4, left: 0 },
      { id: 2, starts_at: "2026-03-02T10:00:00Z", cap: 4, booked: 1, left: 3 },
    ];
    const byTaken = toItems(rows, { ...config, capacity: { capacity: "cap", taken: "booked" } });
    expect(byTaken.map((item) => [item.free, item.full])).toEqual([
      [0, true],
      [3, false],
    ]);
    const byLeft = toItems(rows, { ...config, capacity: { capacity: "cap", remaining: "left" } });
    expect(byLeft.map((item) => [item.taken, item.full])).toEqual([
      [4, true],
      [1, false],
    ]);
  });
});

describe("ranges", () => {
  it("draws seven days in a week from Monday, and whole weeks in a month", () => {
    const week = rangeFor("week", at("2026-03-04T12:00:00Z"), TZ, 1);
    expect(week.days).toHaveLength(7);
    expect(dayKey(week.days[0] as number, TZ)).toBe("2026-03-02");
    const month = rangeFor("month", at("2026-03-04T12:00:00Z"), TZ, 1);
    expect(dayKey(month.days[0] as number, TZ)).toBe("2026-02-23");
    expect(month.days.length % 7).toBe(0);
    expect(dayKey(month.days[month.days.length - 1] as number, TZ)).toBe("2026-04-05");
    expect(rangeFor("day", at("2026-03-04T12:00:00Z"), TZ, 1).days).toHaveLength(1);
  });

  it("steps by a day, a week or a month", () => {
    const anchor = at("2026-01-31T12:00:00Z");
    expect(dayKey(stepAnchor("day", anchor, 1, TZ), TZ)).toBe("2026-02-01");
    expect(dayKey(stepAnchor("week", anchor, -1, TZ), TZ)).toBe("2026-01-24");
    expect(dayKey(stepAnchor("month", anchor, 1, TZ), TZ)).toBe("2026-02-01");
  });
});

describe("day segments and lanes", () => {
  const items = toItems(
    [
      { id: 1, starts_at: "2026-03-02T08:00:00Z", ends_at: "2026-03-02T10:00:00Z" },
      { id: 2, starts_at: "2026-03-02T09:00:00Z", ends_at: "2026-03-02T11:00:00Z" },
      { id: 3, starts_at: "2026-03-02T12:00:00Z", ends_at: "2026-03-02T13:00:00Z" },
      { id: 4, starts_at: "2026-03-02T22:00:00Z", ends_at: "2026-03-03T02:00:00Z" },
    ],
    config,
  ) as CalendarItem<{ id: number }>[];

  it("splits an item that crosses midnight into one segment per day", () => {
    const monday = startOfDay(at("2026-03-02T12:00:00Z"), TZ);
    const first = segmentsForDay(items, monday, TZ).find((s) => s.item.key === "4");
    expect(first?.continuesAfter).toBe(true);
    expect(first?.endMinute).toBe(1440);
    const tuesday = addDays(monday, 1, TZ);
    const second = segmentsForDay(items, tuesday, TZ).find((s) => s.item.key === "4");
    expect(second?.continuesBefore).toBe(true);
    expect(second?.startMinute).toBe(0);
    expect(second?.endMinute).toBe(3 * 60);
  });

  it("ends an item that stops at midnight (Berlin) at the end of its day, and puts nothing on the next", () => {
    const late = toItems(
      [{ id: 9, starts_at: "2026-03-02T22:00:00Z", ends_at: "2026-03-02T23:00:00Z" }],
      config,
    );
    const monday = startOfDay(at("2026-03-02T12:00:00Z"), TZ);
    const [only] = segmentsForDay(late, monday, TZ);
    expect([only?.startMinute, only?.endMinute, only?.continuesAfter]).toEqual([
      23 * 60,
      1440,
      false,
    ]);
    expect(segmentsForDay(late, addDays(monday, 1, TZ), TZ)).toEqual([]);
  });

  it("puts overlapping items side by side and a lone item alone", () => {
    const monday = startOfDay(at("2026-03-02T12:00:00Z"), TZ);
    const laid = layoutLanes(segmentsForDay(items, monday, TZ));
    const by = (key: string) => laid.find((s) => s.item.key === key);
    expect([by("1")?.lane, by("1")?.lanes]).toEqual([0, 2]);
    expect([by("2")?.lane, by("2")?.lanes]).toEqual([1, 2]);
    expect([by("3")?.lane, by("3")?.lanes]).toEqual([0, 1]);
  });
});

describe("moving and resizing", () => {
  it("moves by days and minutes keeping the length, and keeps the wall clock over a clock change", () => {
    const span = { start: at("2026-03-27T08:00:00Z"), end: at("2026-03-27T09:30:00Z") };
    const moved = moveSpan(span, 3, 30, TZ);
    expect(moved.end - moved.start).toBe(90 * MINUTE);
    // 2026-03-27 09:00 CET to 2026-03-30 09:30 CEST (the clocks went forward on the 29th)
    expect(moved.start).toBe(at("2026-03-30T07:30:00Z"));
  });

  it("resizes the end but never below the minimum", () => {
    const span = { start: at("2026-03-02T09:00:00Z"), end: at("2026-03-02T10:00:00Z") };
    expect(resizeSpan(span, 30, 15).end).toBe(at("2026-03-02T10:30:00Z"));
    expect(resizeSpan(span, -120, 15).end).toBe(at("2026-03-02T09:15:00Z"));
  });

  it("snaps minutes to the step", () => {
    expect(snapMinutes(37, 30)).toBe(30);
    expect(snapMinutes(46, 30)).toBe(60);
    expect(snapMinutes(-20, 15)).toBe(-15);
  });
});
