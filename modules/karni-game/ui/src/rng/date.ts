import { hashSeed } from "./rng";

/** Today's seed and where the date came from. */
export interface DailySeed {
  /** The day, `YYYY-MM-DD`. */
  date: string;
  seed: number;
  /**
   * "server": the game server's date and seed, the same for every player and
   * accepted by its daily board. "device": the device's clock, for offline
   * play; a player can change it, so it suits practice, not the shared board.
   */
  source: "server" | "device";
}

/** The day of `date` in a time zone, as `YYYY-MM-DD`. Default UTC, the server's default clock. */
export function dayKey(date: Date = new Date(), timeZone = "UTC"): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const part = (type: string): string => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** A seed from a day and an optional salt (the game's slug), the same everywhere. */
export function dateSeed(day: string, salt = ""): number {
  return hashSeed(`${salt}:${day}`);
}

/** Today's seed from the device's clock, for when the server cannot be reached. */
export function deviceDailySeed(
  options: { salt?: string; timeZone?: string; now?: () => Date } = {},
): DailySeed {
  const date = dayKey((options.now ?? (() => new Date()))(), options.timeZone);
  return { date, seed: dateSeed(date, options.salt), source: "device" };
}
