/**
 * The bodies of the karni-game HTTP contract (docs/game-api.md), as the
 * client reads them. Fields the client does not use are kept as `unknown`
 * extras by the index signatures where the contract allows growth.
 */

export interface Player {
  id: string;
  handle: string;
  guest: boolean;
  created_at?: string;
  /** True for a guest made on this device while no server could be reached. */
  local?: boolean;
}

export interface GuestResponse {
  token: string;
  player: Player;
  /** A retried `intent`: the same guest as the lost answer's, with a new token. */
  replayed?: boolean;
}

export interface UpgradeResponse {
  player: Player;
  merged: {
    adopted: boolean;
    saves: { moved: number; kept_both: string[] };
    scores: number;
    currencies: Record<string, number>;
    items: number;
    unlocks: number;
  };
}

export interface BoardInfo {
  key: string;
  title: string;
  order: "asc" | "desc";
  periods: Period[];
  requires_run?: boolean;
  daily_seed?: boolean;
}

export type Period = "all" | "daily" | "weekly";

export interface CurrencyInfo {
  key: string;
  title: string;
  cap: number;
}

export interface GameBoot {
  game: { slug: string; title: string };
  server: { time: string; date: string; timezone: string; resets_at: string };
  config: Record<string, unknown>;
  flags: Record<string, boolean>;
  save: { schema_version: number; max_bytes: number; max_slots: number };
  boards: BoardInfo[];
  currencies: CurrencyInfo[];
  analytics: Record<string, Record<string, "int" | "float" | "str" | "bool">>;
}

export interface ServerSave<T = unknown> {
  slot: string;
  version: number;
  schema_version: number;
  size?: number;
  data: T;
  updated_at?: string;
}

export interface SaveList {
  results: Omit<ServerSave, "data">[];
  max_slots: number;
  max_bytes: number;
}

/** A run: what a deterministic game needs to replay a score. */
export interface RunRecord {
  seed: string;
  inputs: [number, string][];
  duration_ms?: number;
  build?: string;
  meta?: Record<string, unknown>;
}

export interface ScoreResponse {
  score: { id: string; value: number; status: "accepted" | "flagged"; created_at: string };
  best: Partial<Record<Period, { value: number; rank: number }>>;
  improved: Period[];
  replayed?: boolean;
}

export interface BoardEntry {
  rank: number;
  handle: string;
  value: number;
  achieved_at?: string;
  me: boolean;
}

export interface BoardResponse {
  board: Pick<BoardInfo, "key" | "title" | "order" | "periods">;
  period: Period;
  period_start: string | null;
  entries: BoardEntry[];
  me: { rank: number; value: number } | null;
  /** True when the board came from this device (offline or no server). */
  local?: boolean;
}

export interface AroundResponse {
  period: Period;
  period_start: string | null;
  rank: number | null;
  value: number | null;
  entries: BoardEntry[];
}

export interface Balance {
  currency: string;
  title?: string;
  balance: number;
  cap?: number;
}

export interface OwnedItem {
  item: string;
  title?: string;
  slot?: string;
  equipped: boolean;
  acquired_at?: string;
}

export interface WalletResponse {
  balances: Balance[];
  items: OwnedItem[];
  /** True when read from this device's cache or local economy. */
  local?: boolean;
}

export interface LedgerEntry {
  id: string;
  currency: string;
  amount: number;
  balance_after: number;
  reason: string;
  reference?: string;
  created_at: string;
}

export interface LedgerPage {
  count: number;
  next: number | null;
  results: LedgerEntry[];
}

export interface ShopItem {
  key: string;
  title: string;
  slot?: string;
  price: { currency: string; amount: number } | null;
  real_money: boolean;
  owned: boolean;
  equipped: boolean;
}

export interface BuyResponse {
  item: { key: string; slot?: string; equipped: boolean };
  balance: { currency: string; balance: number };
  replayed?: boolean;
}

export interface EquipResponse {
  item: string;
  slot?: string;
  equipped: boolean;
}

/**
 * Who vouches for a reward: `callback`, the portal's server with a signed
 * callback (an ad), `client`, any client's claim (an ad, capped low), or
 * `server`, the server's own rule (every other kind).
 */
export type RewardTrust = "callback" | "client" | "server";

export interface RewardInfo {
  key: string;
  title: string;
  kind: "daily" | "ad" | "mission" | "achievement" | "match" | "grant";
  currency: string;
  amount: number;
  /** Absent from a server older than the field: read `callback` then. */
  trust?: RewardTrust;
  callback: boolean;
  per_day?: number | null;
  claimed_today?: number;
  available: boolean;
  next_at: string | null;
}

export interface Granted {
  currency: string;
  amount: number;
  balance: number;
}

export interface ClaimResponse {
  granted: Granted;
  capped: boolean;
  next_at: string | null;
  replayed?: boolean;
}

export interface Streak {
  current: number;
  best: number;
  last_day: string | null;
  checked_in: boolean;
}

export interface DailyResponse {
  date: string;
  seed: number;
  server_time: string;
  resets_at: string;
  board: string | null;
  streak: Streak | null;
  rewards: { key: string; currency: string; amount: number }[];
}

export interface CheckInResponse {
  new_day: boolean;
  streak: Streak;
  granted: ({ reward: string } & Granted)[];
}

export interface ProgressEvent {
  counter: string;
  amount: number;
}

export interface ProgressResponse {
  counters: Record<string, number>;
  unlocked: { key: string; title: string }[];
  completed: { key: string; title: string; granted?: Granted }[];
  replayed?: boolean;
}

export interface Achievement {
  key: string;
  title: string;
  description?: string;
  counter: string;
  goal: number;
  progress: number;
  unlocked_at: string | null;
}

export interface Mission {
  key: string;
  title: string;
  period: "once" | "daily" | "weekly";
  period_start: string | null;
  counter: string;
  goal: number;
  progress: number;
  completed_at: string | null;
  reward: { currency: string; amount: number } | null;
}

export interface AnalyticsEvent {
  name: string;
  props?: Record<string, string | number | boolean>;
}

export interface EventsResponse {
  accepted: number;
  rejected: { index: number; code: string; detail: string }[];
}

export interface MultiplayerToken {
  token: string;
  expires_at: string;
  player: { id: string; handle: string };
}

export interface ListResponse<T> {
  results: T[];
}
