import type { GameStorage } from "../save/storage";
import type {
  Achievement,
  Balance,
  BoardEntry,
  BoardResponse,
  BuyResponse,
  CheckInResponse,
  ClaimResponse,
  CurrencyInfo,
  EquipResponse,
  LedgerEntry,
  OwnedItem,
  Period,
  ProgressEvent,
  ProgressResponse,
  Streak,
  WalletResponse,
} from "./types";

/**
 * What a game declares for play without a server: the same shapes the server
 * declares, so a game moves to a server without changing its calls.
 */
export interface LocalGameSetup {
  boards?: Record<string, { title?: string; order?: "asc" | "desc"; keep?: number }>;
  currencies?: CurrencyInfo[];
  shop?: {
    key: string;
    title: string;
    slot?: string;
    price: { currency: string; amount: number };
  }[];
  rewards?: {
    key: string;
    title: string;
    kind: "daily" | "ad";
    currency: string;
    amount: number;
    /** How many claims a day (ad rewards). Default no limit. */
    perDay?: number;
  }[];
  achievements?: {
    key: string;
    title: string;
    description?: string;
    counter: string;
    goal: number;
  }[];
  /** Days a streak may skip and go on. Default 1, as the server's `streak_grace_days`. */
  streakGraceDays?: number;
}

export class LocalRuleError extends Error {
  readonly code: string;
  readonly data: Record<string, unknown>;
  constructor(code: string, message: string, data: Record<string, unknown> = {}) {
    super(`${code}: ${message}`);
    this.name = "LocalRuleError";
    this.code = code;
    this.data = data;
  }
}

interface LocalScore {
  value: number;
  at: string;
  day: string;
  week: string;
}

interface LocalState {
  balances: Record<string, number>;
  items: Record<string, { slot?: string; equipped: boolean; acquired_at: string }>;
  /** The days each ad reward was claimed on, today's only. */
  claims: Record<string, string[]>;
  streak: { current: number; best: number; last_day: string | null };
  ledger: LedgerEntry[];
  counters: Record<string, number>;
  unlocked: Record<string, string>;
}

const emptyState = (): LocalState => ({
  balances: {},
  items: {},
  claims: {},
  streak: { current: 0, best: 0, last_day: null },
  ledger: [],
  counters: {},
  unlocked: {},
});

/** The Monday of a day's week, as `YYYY-MM-DD` (the server's weeks start on Monday). */
export function weekStart(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  const offset = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - offset);
  return date.toISOString().slice(0, 10);
}

const daysBetween = (from: string, to: string): number =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);

export interface LocalGame {
  /** Record a score on this device's board and say which periods it improved. */
  addScore(board: string, value: number): { improved: Period[] };
  board(board: string, period: Period, handle: string, limit?: number): BoardResponse;
  wallet(): WalletResponse;
  ledger(): LedgerEntry[];
  /** Add currency earned in play. Only for a game with no server: these balances never reach one. */
  grant(currency: string, amount: number, reference?: string): Balance;
  buy(item: string): BuyResponse;
  equip(item: string, equipped: boolean): EquipResponse;
  claim(reward: string): ClaimResponse;
  checkIn(): CheckInResponse;
  streak(): Streak;
  progress(events: ProgressEvent[]): ProgressResponse;
  achievements(): Achievement[];
}

/** Boards, wallet, streak and achievements kept on the device, by the same rules as the server. */
export function createLocalGame(
  storage: GameStorage,
  setup: LocalGameSetup,
  today: () => { day: string; now: Date },
): LocalGame {
  const load = (): LocalState => ({
    ...emptyState(),
    ...storage.getJson<LocalState>("local.game"),
  });
  const store = (state: LocalState): void => {
    storage.setJson("local.game", state);
  };
  const currency = (key: string): CurrencyInfo => {
    const found = setup.currencies?.find((c) => c.key === key);
    if (!found) throw new LocalRuleError("GAME021", `no currency "${key}" in the local setup`);
    return found;
  };
  const move = (
    state: LocalState,
    key: string,
    amount: number,
    reason: string,
    reference?: string,
  ): { balance: number; capped: boolean } => {
    const info = currency(key);
    const before = state.balances[key] ?? 0;
    const wanted = before + amount;
    if (wanted < 0) {
      throw new LocalRuleError("GAME016", "not enough of the currency", {
        balance: before,
        needed: -amount,
      });
    }
    const after = Math.min(wanted, info.cap);
    state.balances[key] = after;
    state.ledger.unshift({
      id: `local-${Date.now()}-${state.ledger.length}`,
      currency: key,
      amount: after - before,
      balance_after: after,
      reason,
      reference,
      created_at: today().now.toISOString(),
    });
    state.ledger = state.ledger.slice(0, 200);
    return { balance: after, capped: after < wanted };
  };
  const scores = (board: string): LocalScore[] =>
    storage.getJson<LocalScore[]>(`local.board.${board}`) ?? [];
  const boardSetup = (board: string) => setup.boards?.[board] ?? {};
  const better = (board: string) =>
    boardSetup(board).order === "asc"
      ? (a: number, b: number) => a < b
      : (a: number, b: number) => a > b;
  const inPeriod = (score: LocalScore, period: Period, day: string): boolean =>
    period === "all" || (period === "daily" ? score.day === day : score.week === weekStart(day));

  const streakOf = (state: LocalState): Streak => ({
    ...state.streak,
    checked_in: state.streak.last_day === today().day,
  });

  return {
    addScore(board, value) {
      const { day, now } = today();
      const list = scores(board);
      const wins = better(board);
      const improved = (["all", "daily", "weekly"] as Period[]).filter((period) => {
        const best = list
          .filter((s) => inPeriod(s, period, day))
          .sort((a, b) => (wins(a.value, b.value) ? -1 : 1))[0];
        return !best || wins(value, best.value);
      });
      list.push({ value, at: now.toISOString(), day, week: weekStart(day) });
      const keep = boardSetup(board).keep ?? 50;
      list.sort((a, b) =>
        wins(a.value, b.value) ? -1 : wins(b.value, a.value) ? 1 : a.at.localeCompare(b.at),
      );
      storage.setJson(`local.board.${board}`, list.slice(0, keep));
      return { improved };
    },
    board(board, period, handle, limit = 10) {
      const { day } = today();
      const entries: BoardEntry[] = scores(board)
        .filter((s) => inPeriod(s, period, day))
        .slice(0, limit)
        .map((s, index) => ({
          rank: index + 1,
          handle,
          value: s.value,
          achieved_at: s.at,
          me: true,
        }));
      const first = entries[0];
      return {
        board: {
          key: board,
          title: boardSetup(board).title ?? board,
          order: boardSetup(board).order ?? "desc",
          periods: ["all", "daily", "weekly"],
        },
        period,
        period_start: period === "all" ? null : period === "daily" ? day : weekStart(day),
        entries,
        me: first ? { rank: 1, value: first.value } : null,
        local: true,
      };
    },
    wallet() {
      const state = load();
      const balances: Balance[] = (setup.currencies ?? []).map((c) => ({
        currency: c.key,
        title: c.title,
        balance: state.balances[c.key] ?? 0,
        cap: c.cap,
      }));
      const items: OwnedItem[] = Object.entries(state.items).map(([item, owned]) => ({
        item,
        title: setup.shop?.find((s) => s.key === item)?.title,
        slot: owned.slot,
        equipped: owned.equipped,
        acquired_at: owned.acquired_at,
      }));
      return { balances, items, local: true };
    },
    ledger: () => load().ledger,
    grant(key, amount, reference) {
      if (!Number.isInteger(amount) || amount <= 0) {
        throw new LocalRuleError("GAME024", "a grant is a whole amount above 0");
      }
      const state = load();
      const { balance } = move(state, key, amount, "reward", reference);
      store(state);
      return { currency: key, balance, cap: currency(key).cap };
    },
    buy(key) {
      const item = setup.shop?.find((s) => s.key === key);
      if (!item) throw new LocalRuleError("GAME021", `no item "${key}" for sale`);
      const state = load();
      if (state.items[key]) throw new LocalRuleError("GAME022", "the player owns the item already");
      const { balance } = move(state, item.price.currency, -item.price.amount, "purchase", key);
      state.items[key] = {
        slot: item.slot,
        equipped: false,
        acquired_at: today().now.toISOString(),
      };
      store(state);
      return {
        item: { key, slot: item.slot, equipped: false },
        balance: { currency: item.price.currency, balance },
      };
    },
    equip(key, equipped) {
      const state = load();
      const owned = state.items[key];
      if (!owned) throw new LocalRuleError("GAME023", "the player does not own the item");
      if (equipped && owned.slot) {
        for (const other of Object.values(state.items))
          if (other.slot === owned.slot) other.equipped = false;
      }
      owned.equipped = equipped;
      store(state);
      return { item: key, slot: owned.slot, equipped };
    },
    claim(key) {
      const reward = setup.rewards?.find((r) => r.key === key && r.kind === "ad");
      if (!reward) throw new LocalRuleError("GAME021", `no ad reward "${key}"`);
      const state = load();
      const { day } = today();
      const claims = (state.claims[key] ?? []).filter((claimed) => claimed === day);
      if (reward.perDay !== undefined && claims.length >= reward.perDay) {
        throw new LocalRuleError("GAME017", "the reward is not available now", { next_at: null });
      }
      const { balance, capped } = move(state, reward.currency, reward.amount, "reward", key);
      state.claims[key] = [...claims, day];
      store(state);
      return {
        granted: { currency: reward.currency, amount: reward.amount, balance },
        capped,
        next_at: null,
      };
    },
    checkIn() {
      const state = load();
      const { day } = today();
      if (state.streak.last_day === day)
        return { new_day: false, streak: streakOf(state), granted: [] };
      const grace = setup.streakGraceDays ?? 1;
      const gap = state.streak.last_day ? daysBetween(state.streak.last_day, day) : Infinity;
      const current = gap >= 1 && gap <= 1 + grace ? state.streak.current + 1 : 1;
      state.streak = { current, best: Math.max(state.streak.best, current), last_day: day };
      const granted = (setup.rewards ?? [])
        .filter((r) => r.kind === "daily")
        .map((r) => ({
          reward: r.key,
          currency: r.currency,
          amount: r.amount,
          balance: move(state, r.currency, r.amount, "reward", r.key).balance,
        }));
      store(state);
      return { new_day: true, streak: streakOf(state), granted };
    },
    streak: () => streakOf(load()),
    progress(events) {
      const state = load();
      const unlocked: { key: string; title: string }[] = [];
      for (const event of events) {
        if (!Number.isInteger(event.amount) || event.amount < 1) {
          throw new LocalRuleError("GAME024", "a progress amount is a whole number from 1");
        }
        state.counters[event.counter] = (state.counters[event.counter] ?? 0) + event.amount;
      }
      for (const achievement of setup.achievements ?? []) {
        if (state.unlocked[achievement.key]) continue;
        if ((state.counters[achievement.counter] ?? 0) >= achievement.goal) {
          state.unlocked[achievement.key] = today().now.toISOString();
          unlocked.push({ key: achievement.key, title: achievement.title });
        }
      }
      store(state);
      return { counters: { ...state.counters }, unlocked, completed: [] };
    },
    achievements() {
      const state = load();
      return (setup.achievements ?? []).map((a) => ({
        key: a.key,
        title: a.title,
        description: a.description,
        counter: a.counter,
        goal: a.goal,
        progress: state.counters[a.counter] ?? 0,
        unlocked_at: state.unlocked[a.key] ?? null,
      }));
    },
  };
}
