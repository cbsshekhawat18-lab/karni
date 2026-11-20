import { createEmitter } from "../internal/emitter";
import { dayKey, deviceDailySeed, type DailySeed } from "../rng/date";
import type { GameStorage } from "../save/storage";
import { createLocalGame, LocalRuleError, type LocalGame, type LocalGameSetup } from "./local";
import {
  createQueue,
  type FlushResult,
  type QueuedWrite,
  type SendOutcome,
  type WriteQueue,
} from "./queue";
import {
  OfflineError,
  fetchTransport,
  httpError,
  type Method,
  type Transport,
  type TransportRequest,
} from "./transport";
import type {
  Achievement,
  AnalyticsEvent,
  AroundResponse,
  Balance,
  BoardResponse,
  BuyResponse,
  CheckInResponse,
  ClaimResponse,
  Granted,
  EquipResponse,
  GameBoot,
  GuestResponse,
  LedgerPage,
  ListResponse,
  Mission,
  MultiplayerToken,
  Period,
  Player,
  ProgressEvent,
  ProgressResponse,
  RewardInfo,
  RewardTrust,
  RunRecord,
  SaveList,
  ScoreResponse,
  ServerSave,
  ShopItem,
  Streak,
  UpgradeResponse,
  WalletResponse,
} from "./types";

export interface ServerOptions {
  /** A transport of the project's own, such as `@karni/ui`'s `createKarniClient(...)`. */
  transport?: Transport;
  /** For the built-in transport: the API's origin. Default the page's own. */
  baseUrl?: string;
  /** Where karni-game is mounted. Default "/api/game/". */
  path?: string;
  /** For the built-in transport: the account's JWT. */
  getAccessToken?: () => string | null;
  /** For the built-in transport: extra headers (`csrfHeader()` for a session). */
  getHeaders?: () => Record<string, string>;
  credentials?: RequestCredentials;
  /** The header the guest token travels in, as the server's `KARNI_GAME_TOKEN_HEADER`. Default "X-Player-Token". */
  tokenHeader?: string;
  /**
   * Whether an account is signed in. Default: `getAccessToken` returns a
   * token. With an account the server finds the player from it, and a guest
   * token is needed only to upgrade.
   */
  signedIn?: () => boolean;
}

/** A save in a slot, as this device knows it. */
export interface SlotState<T = unknown> {
  slot: string;
  data: T;
  schemaVersion: number;
  /** The server's version this data is based on (0 before the first write reached it). */
  version: number;
  /** Changed here and not on the server yet. */
  dirty: boolean;
  source: "server" | "device";
}

/** How a game settles a save changed both here and on the server (`409 GAME008`). */
export type SaveConflictResolver = (
  local: SlotState,
  server: ServerSave,
) => "local" | "server" | { data: unknown; schemaVersion?: number };

export interface GameClientOptions {
  /** The game's slug on the server, and the salt of the device's daily seed. */
  game: string;
  /** Where the client keeps the player, its token, the queue and cached answers. */
  storage: GameStorage;
  /** The game server. Omit it and the game runs on this device only. */
  server?: ServerOptions;
  /** Boards, currencies, shop, rewards and achievements for play without a server. */
  local?: LocalGameSetup;
  /** Bundled config and flags, used until (and unless) the server's arrive. */
  defaults?: { config?: Record<string, unknown>; flags?: Record<string, boolean> };
  /**
   * Settle a save conflict. Default "server": the server's copy is used and
   * this device's is kept under `slot.<name>.conflict`, so nothing is lost.
   */
  onConflict?: SaveConflictResolver;
  /** Every tracked event also goes here (the project's own analytics). */
  analyticsSink?: (event: AnalyticsEvent) => void;
  /** Gather analytics this long before sending them as one request. Default 5000 ms. */
  analyticsBatchMs?: number;
  /** Retry waiting writes this often while there are some. Default 30000 ms. */
  syncEveryMs?: number;
  /** Whether the device is online. Default `navigator.onLine`. */
  online?: () => boolean;
  /** The time zone of the device's day before the server says its own. Default UTC. */
  timeZone?: string;
  now?: () => Date;
  /** Make an intent: a unique id per action. Default a random UUID. */
  newIntent?: () => string;
}

export interface BootResult {
  source: "server" | "cache" | "defaults";
  server: GameBoot | null;
}

export interface ScoreResult {
  /** The periods this device's own board improved in. */
  improved: Period[];
  /** Waiting in the queue: the server answer comes on the "synced" event. */
  queued: boolean;
  /** The server's answer, when it was reached now. */
  server?: ScoreResponse;
}

export interface DailyState extends DailySeed {
  streak: Streak | null;
  /** The game's daily board, or null. */
  board: string | null;
  resetsAt: string | null;
}

export interface WriteResult<T> {
  queued: boolean;
  server?: T;
}

/** What `adReward()` came to. */
export type AdRewardResult =
  /** Granted now: a reward the client claims (`trust` `client`), or the device's own. */
  | { status: "granted"; granted: Granted; capped: boolean; nextAt: string | null }
  /**
   * Watched, and the portal's server grants it with its signed callback
   * (`trust` `callback`): read the wallet again in a moment.
   */
  | { status: "pending"; intent: string }
  /** The ad was not watched to the end: nothing is granted. */
  | { status: "not-watched" }
  /** Not an ad reward, or not available now (`nextAt`: when it is again, or null). */
  | { status: "unavailable"; nextAt: string | null };

export interface GameClientEvents {
  /** The player changed (signed in, upgraded, forgotten). */
  player: Player | null;
  /** The server's config arrived. */
  config: GameBoot;
  /** A queued write reached the server. */
  synced: { write: QueuedWrite; response: unknown };
  /** The server refused a queued write for good. */
  rejected: { write: QueuedWrite; status: number; code: string | null; data: unknown };
  /** A save changed here and on the server; `kept` says whose copy the slot now holds. */
  conflict: {
    slot: string;
    local: SlotState;
    server: ServerSave;
    kept: "local" | "server" | "merged";
  };
  /** The server became reachable or unreachable. */
  online: boolean;
}

export interface GameClient {
  readonly game: string;
  /** A server is configured. */
  readonly hasServer: boolean;
  /** The server answered the last request (false with no server). */
  readonly online: boolean;
  readonly player: Player | null;
  readonly queue: WriteQueue;
  on<K extends keyof GameClientEvents>(
    event: K,
    listener: (value: GameClientEvents[K]) => void,
  ): () => void;

  /** Load the game's config, flags and server clock. Falls back to the cached copy, then the defaults. */
  boot(): Promise<BootResult>;
  config<T>(key: string, fallback: T): T;
  flag(key: string, fallback?: boolean): boolean;
  /** The time on the server's clock (the device's, corrected by the last server answer). */
  now(): Date;
  /** Today on the game's clock, `YYYY-MM-DD`. */
  today(): string;

  /**
   * The player, made a guest when there is none. Works offline: a device guest
   * joins the server later. Signed in with no guest on the device, it is the
   * account's own player, and no guest is made.
   */
  signInGuest(handle?: string): Promise<Player>;
  /** Keep the guest's progress on the account the player just signed in to (Karni's sign-in). */
  upgrade(): Promise<UpgradeResponse>;
  setHandle(handle: string): Promise<Player>;
  /** Forget this device's player, token and waiting writes. */
  signOut(): void;

  saves: {
    list(): Promise<SaveList>;
    load<T>(slot?: string): Promise<SlotState<T> | null>;
    /** Keep the save here at once and send it when the server can be reached. */
    write<T>(slot: string, data: T, schemaVersion: number): SlotState<T>;
    remove(slot: string): Promise<void>;
  };

  /**
   * Send a score. It carries when it was played (`playedAt`, default now on
   * the server's clock), so a score sent later from the queue is on the
   * boards of the day it was played.
   */
  submitScore(
    board: string,
    value: number,
    options?: { run?: RunRecord; intent?: string; playedAt?: Date },
  ): Promise<ScoreResult>;
  leaderboard(board: string, options?: { period?: Period; limit?: number }): Promise<BoardResponse>;
  around(
    board: string,
    options?: { period?: Period; around?: number },
  ): Promise<AroundResponse | null>;

  wallet(): Promise<WalletResponse>;
  ledger(options?: { currency?: string; page?: number }): Promise<LedgerPage>;
  shop(): Promise<ShopItem[]>;
  buy(item: string, options?: { intent?: string }): Promise<BuyResponse>;
  equip(item: string): Promise<EquipResponse>;
  unequip(item: string): Promise<EquipResponse>;
  rewards(): Promise<RewardInfo[]>;
  claimReward(key: string, options?: { intent?: string }): Promise<ClaimResponse>;
  /** For a reward the portal's server grants: the intent to hand to the portal's ad call. */
  rewardIntent(key: string): Promise<{ intent: string; expires_at: string }>;
  /**
   * An ad reward, by its `trust`. `show` plays the ad (`() => portal.rewarded()`)
   * and resolves true when it was watched to the end. With `trust` `callback`
   * it gets the intent to hand to the portal's ad call first, and the portal's
   * server grants the reward. With `client` the reward is claimed once the ad
   * was watched. The client never names an amount.
   */
  adReward(key: string, show: (intent: string | null) => Promise<boolean>): Promise<AdRewardResult>;
  /** Add currency earned in play, on a game with no server only (the server grants its own). */
  grant(currency: string, amount: number, reference?: string): Balance;

  daily(): Promise<DailyState>;
  checkIn(): Promise<CheckInResponse>;

  progress(
    events: ProgressEvent[],
    options?: { intent?: string },
  ): Promise<WriteResult<ProgressResponse>>;
  achievements(): Promise<Achievement[]>;
  missions(): Promise<Mission[]>;

  /** Record an analytics event. Sent in batches, queued when offline. */
  track(name: string, props?: AnalyticsEvent["props"]): void;
  flushEvents(): void;

  multiplayerToken(): Promise<MultiplayerToken>;

  /** Send what waits in the queue now. */
  sync(): Promise<FlushResult>;
  /** Stop the timers and listeners. */
  destroy(): void;
}

/** Where a guest's issue waits for its answer: its intent and body. */
const GUEST_PENDING = "guest.pending";
interface GuestPending {
  intent: string;
  body: { handle?: string };
}

function randomIntent(): string {
  const scope = globalThis as unknown as { crypto?: Crypto };
  if (scope.crypto && typeof scope.crypto.randomUUID === "function")
    return scope.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (scope.crypto) scope.crypto.getRandomValues(bytes);
  else
    for (let index = 0; index < bytes.length; index += 1)
      bytes[index] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Codes that say who is calling is not settled yet (no player, a forgotten
 * guest, an unverified email, guests off until the player signs in): the
 * write waits for a player instead of being dropped.
 */
const waitsForPlayer = (code: string | null): boolean =>
  code === "GAME002" || code === "GAME003" || code === "GAME004" || code === "GAME005";

const retryAfterMs = (data: unknown): number | undefined => {
  const seconds =
    typeof data === "object" && data !== null
      ? (data as { retry_after?: unknown }).retry_after
      : undefined;
  return typeof seconds === "number" && seconds >= 0 ? seconds * 1000 : undefined;
};

/**
 * The game's data client: guest sign-in and the upgrade to an account, save
 * slots with conflict handling, scores and boards, wallet and shop, daily
 * content, achievements, remote config and analytics, against the karni-game
 * contract. Writes go to the device first and through a queue with intents,
 * so the game plays offline. Without a server it runs on the device alone,
 * by the same rules, and a server is an upgrade.
 */
export function createGameClient(options: GameClientOptions): GameClient {
  const { storage, game } = options;
  const server = options.server;
  const prefix = `${(server?.path ?? "/api/game/").replace(/\/?$/, "/")}`;
  const transport: Transport | null = server
    ? (server.transport ??
      fetchTransport({
        baseUrl: server.baseUrl,
        getAccessToken: server.getAccessToken,
        getHeaders: server.getHeaders,
        credentials: server.credentials,
      }))
    : null;
  const signedIn = server?.signedIn ?? (() => Boolean(server?.getAccessToken?.()));
  const tokenHeader = server?.tokenHeader ?? "X-Player-Token";
  const deviceOnline =
    options.online ??
    (() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  const deviceNow = options.now ?? (() => new Date());
  const newIntent = options.newIntent ?? randomIntent;
  const events = createEmitter<GameClientEvents>();
  const queue = createQueue({ storage });

  let player: Player | null = storage.getJson<Player>("player") ?? null;
  let token: string | null = storage.get("token");
  let boot: GameBoot | null = storage.getJson<GameBoot>("boot") ?? null;
  let clockOffset = 0;
  let reachable = Boolean(server);
  let pendingEvents: AnalyticsEvent[] = [];
  let eventTimer: ReturnType<typeof setTimeout> | null = null;

  const now = (): Date => new Date(deviceNow().getTime() + clockOffset);
  const timeZone = (): string => boot?.server.timezone ?? options.timeZone ?? "UTC";
  const today = (): string => dayKey(now(), timeZone());
  const local: LocalGame = createLocalGame(storage, options.local ?? {}, () => ({
    day: today(),
    now: now(),
  }));

  const setReachable = (value: boolean): void => {
    if (value === reachable) return;
    reachable = value;
    events.emit("online", value);
  };
  const setPlayer = (next: Player | null): void => {
    player = next;
    if (next) storage.setJson("player", next);
    else storage.remove("player");
    events.emit("player", next);
  };
  const setToken = (next: string | null): void => {
    token = next;
    if (next) storage.set("token", next);
    else storage.remove("token");
  };
  const learnClock = (iso: string | undefined): void => {
    const at = iso ? Date.parse(iso) : Number.NaN;
    if (Number.isFinite(at)) clockOffset = at - deviceNow().getTime();
  };

  const offline = (): OfflineError =>
    new OfflineError(server ? "The game server cannot be reached" : "This game has no server");

  /** One request to the server, with the guest token. Marks the server reachable or not. */
  const request = async <T>(
    method: Method,
    path: string,
    init: Omit<TransportRequest, "method"> = {},
  ): Promise<T> => {
    if (!transport) throw offline();
    if (!deviceOnline()) {
      setReachable(false);
      throw offline();
    }
    const headers = { ...init.headers };
    if (token) headers[tokenHeader] = token;
    try {
      const answer = await transport.request<T>(`${prefix}${path}`, { ...init, method, headers });
      setReachable(true);
      return answer;
    } catch (error) {
      const http = httpError(error);
      if (!http) {
        setReachable(false);
        throw error instanceof OfflineError ? error : offline();
      }
      setReachable(true);
      if (http.code === "GAME003") {
        // The server no longer knows this guest: forget it, a new one is made on the next call.
        setToken(null);
        if (player?.guest) setPlayer(null);
      }
      throw error;
    }
  };
  const gamePath = (rest = ""): string => `${game}/${rest}`;

  /**
   * Issue a guest on the server. The request's intent and body are kept until
   * an answer arrives, and a retry sends them again: a lost answer gives the
   * same guest (with a new token), never a second one.
   */
  const issueGuest = async (body: { handle?: string }, fresh = false): Promise<GuestResponse> => {
    const kept = fresh ? null : storage.getJson<GuestPending>(GUEST_PENDING);
    const pending: GuestPending =
      kept && typeof kept.intent === "string" ? kept : { intent: newIntent(), body };
    storage.setJson(GUEST_PENDING, pending);
    let answer: GuestResponse;
    try {
      answer = await request<GuestResponse>("POST", "guest/", {
        body: { ...pending.body, intent: pending.intent },
      });
    } catch (error) {
      // Kept past the server's hour, or its guest is gone: a new intent makes a new guest.
      if (fresh || httpError(error)?.code !== "GAME033") throw error;
      return issueGuest(body, true);
    }
    storage.remove(GUEST_PENDING);
    setToken(answer.token);
    setPlayer(answer.player);
    return answer;
  };

  /** Make sure the server knows who is calling: an account, or a guest token. */
  const ensureServerPlayer = async (): Promise<void> => {
    if (!transport || signedIn() || token) return;
    await issueGuest(player?.handle && player.local ? { handle: player.handle } : {});
  };

  /**
   * POST a write. A score whose `played_at` the server does not trust
   * (`GAME036`: older than its window, or a device clock ahead of it) is sent
   * again without it, and counts as played now.
   */
  const post = async <T>(path: string, body: unknown): Promise<T> => {
    try {
      return await request<T>("POST", path, { body });
    } catch (error) {
      const fields = body as Record<string, unknown> | undefined;
      if (httpError(error)?.code !== "GAME036" || !fields || !("played_at" in fields)) throw error;
      const now: Record<string, unknown> = { ...fields };
      delete now.played_at;
      return request<T>("POST", path, { body: now });
    }
  };

  // --- saves -------------------------------------------------------------------

  const slotKey = (slot: string): string => `slot.${slot}`;
  const readSlot = <T>(slot: string): (SlotState<T> & { rev: number }) | null =>
    storage.getJson<SlotState<T> & { rev: number }>(slotKey(slot)) ?? null;
  const keepSlot = (state: SlotState & { rev: number }): void => {
    storage.setJson(slotKey(state.slot), state);
  };
  const fromServer = <T>(save: ServerSave<T>, rev = 0): SlotState<T> & { rev: number } => ({
    slot: save.slot,
    data: save.data,
    schemaVersion: save.schema_version,
    version: save.version,
    dirty: false,
    source: "server",
    rev,
  });

  const settleConflict = (
    slot: string,
    mine: SlotState & { rev: number },
    theirs: ServerSave,
  ): boolean => {
    const choice = options.onConflict ? options.onConflict(mine, theirs) : "server";
    if (choice === "server") {
      storage.setJson(`${slotKey(slot)}.conflict`, mine);
      keepSlot(fromServer(theirs, mine.rev));
      events.emit("conflict", { slot, local: mine, server: theirs, kept: "server" });
      return false;
    }
    const data = choice === "local" ? mine.data : choice.data;
    const schemaVersion =
      choice === "local" ? mine.schemaVersion : (choice.schemaVersion ?? mine.schemaVersion);
    keepSlot({
      ...mine,
      data,
      schemaVersion,
      version: theirs.version,
      dirty: true,
      rev: mine.rev + 1,
    });
    events.emit("conflict", {
      slot,
      local: mine,
      server: theirs,
      kept: choice === "local" ? "local" : "merged",
    });
    return true;
  };

  const sendSave = async (
    slot: string,
    attempt = 0,
  ): Promise<{ outcome: SendOutcome; response?: ServerSave }> => {
    const mine = readSlot(slot);
    if (!mine || !mine.dirty) return { outcome: "done" };
    try {
      const saved = await request<ServerSave>("PUT", gamePath(`saves/${slot}/`), {
        body: { data: mine.data, schema_version: mine.schemaVersion, base_version: mine.version },
      });
      const latest = readSlot(slot);
      // A write made while this one travelled stays dirty, on top of the new version.
      if (latest && latest.rev !== mine.rev) keepSlot({ ...latest, version: saved.version });
      else keepSlot(fromServer(saved, mine.rev));
      return { outcome: "done", response: saved };
    } catch (error) {
      const http = httpError(error);
      if (http?.code === "GAME008") {
        const theirs = (http.data as { save?: ServerSave }).save;
        if (!theirs) return { outcome: "drop" };
        const again = settleConflict(slot, mine, theirs);
        if (!again) return { outcome: "done", response: theirs };
        // Written again on top of the server's version, at once (and only a few times in a row).
        return attempt < 3 ? sendSave(slot, attempt + 1) : { outcome: {} };
      }
      throw error;
    }
  };

  // --- the queue ---------------------------------------------------------------

  const send = async (write: QueuedWrite): Promise<SendOutcome> => {
    try {
      await ensureServerPlayer();
      let response: unknown;
      if (write.kind === "save") {
        const result = await sendSave((write.body as { slot: string }).slot);
        if (result.outcome !== "done") return result.outcome;
        response = result.response;
      } else if (write.method === "POST") {
        response = await post(write.path, write.body);
      } else {
        response = await request(write.method, write.path, { body: write.body });
      }
      events.emit("synced", { write, response });
      return "done";
    } catch (error) {
      const http = httpError(error);
      if (!http) return {};
      if (http.status === 429) return { retryInMs: retryAfterMs(http.data) };
      if (http.status >= 500 || waitsForPlayer(http.code)) return {};
      events.emit("rejected", { write, status: http.status, code: http.code, data: http.data });
      return "drop";
    }
  };

  const sync = async (): Promise<FlushResult> => {
    if (!transport || !deviceOnline()) return { sent: 0, dropped: 0, left: queue.size };
    return queue.flush(send);
  };

  /** Send a write now when nothing waits before it, or queue it. */
  const write = async <T>(
    kind: string,
    path: string,
    body: Record<string, unknown>,
  ): Promise<WriteResult<T>> => {
    const intent = typeof body.intent === "string" ? body.intent : newIntent();
    const queued: Omit<QueuedWrite, "attempts" | "createdAt" | "notBefore"> = {
      id: intent,
      kind,
      method: "POST",
      path: gamePath(path),
      body: { ...body, intent },
    };
    if (queue.size === 0 && deviceOnline()) {
      try {
        await ensureServerPlayer();
        const answer = await post<T>(queued.path, queued.body);
        return { queued: false, server: answer };
      } catch (error) {
        const http = httpError(error);
        if (http && http.status < 500 && http.status !== 429 && !waitsForPlayer(http.code)) {
          throw error;
        }
      }
    }
    queue.add(queued);
    return { queued: true };
  };

  const timer = setInterval(() => {
    if (queue.size > 0) void sync();
  }, options.syncEveryMs ?? 30_000);
  const onOnline = (): void => void sync();
  if (typeof window !== "undefined") window.addEventListener("online", onOnline);

  // --- analytics ---------------------------------------------------------------

  const flushEvents = (): void => {
    if (eventTimer) clearTimeout(eventTimer);
    eventTimer = null;
    if (!transport) {
      pendingEvents = [];
      return;
    }
    while (pendingEvents.length > 0) {
      const batch = pendingEvents.slice(0, 20);
      pendingEvents = pendingEvents.slice(20);
      // The batch's intent: a retry after a lost answer publishes nothing twice.
      const intent = newIntent();
      queue.add({
        id: intent,
        kind: "events",
        method: "POST",
        path: gamePath("events/"),
        body: { events: batch, intent },
      });
    }
    void sync();
  };

  // --- the client --------------------------------------------------------------

  const client: GameClient = {
    game,
    hasServer: Boolean(transport),
    get online() {
      return Boolean(transport) && reachable && deviceOnline();
    },
    get player() {
      return player;
    },
    queue,
    on: events.on,

    async boot() {
      if (transport) {
        try {
          const answer = await request<GameBoot>("GET", gamePath());
          boot = answer;
          storage.setJson("boot", answer);
          learnClock(answer.server.time);
          events.emit("config", answer);
          void sync();
          return { source: "server", server: answer };
        } catch {
          // The cached copy, then the defaults.
        }
      }
      return { source: boot ? "cache" : "defaults", server: boot };
    },
    config<T>(key: string, fallback: T): T {
      const fromServer = boot?.config[key];
      if (fromServer !== undefined) return fromServer as T;
      const bundled = options.defaults?.config?.[key];
      return bundled !== undefined ? (bundled as T) : fallback;
    },
    flag(key, fallback = false) {
      return boot?.flags[key] ?? options.defaults?.flags?.[key] ?? fallback;
    },
    now,
    today,

    async signInGuest(handle) {
      // An account plays as its own player. A guest kept on the device stays the
      // player until upgrade() moves its progress to the account.
      if (transport && signedIn() && !token && deviceOnline()) {
        try {
          const mine = await request<Player>("GET", "me/");
          setPlayer(mine);
          return mine;
        } catch (error) {
          if (httpError(error)) throw error;
        }
      }
      if (player) return player;
      if (transport && deviceOnline()) {
        try {
          return (await issueGuest(handle ? { handle } : {})).player;
        } catch (error) {
          if (httpError(error)) throw error;
        }
      }
      const guest: Player = {
        id: `local-${newIntent()}`,
        handle: handle ?? "Player",
        guest: true,
        local: true,
      };
      setPlayer(guest);
      return guest;
    },
    async upgrade() {
      if (!transport) throw offline();
      const answer = await request<UpgradeResponse>("POST", "upgrade/", {
        body: token ? { guest_token: token } : {},
      });
      setToken(null);
      setPlayer(answer.player);
      // The server merged the saves: slots not changed here are read again from it.
      for (const name of storage.keys()) {
        if (!name.startsWith("slot.") || name.endsWith(".conflict")) continue;
        const state = storage.getJson<SlotState>(name);
        if (state && !state.dirty) storage.remove(name);
      }
      return answer;
    },
    async setHandle(handle) {
      if (!transport || player?.local) {
        const renamed: Player = {
          ...(player ?? { id: `local-${newIntent()}`, guest: true, local: true }),
          handle,
        };
        setPlayer(renamed);
        return renamed;
      }
      await ensureServerPlayer();
      const answer = await request<Player>("PATCH", "me/", { body: { handle } });
      setPlayer(answer);
      return answer;
    },
    signOut() {
      setToken(null);
      setPlayer(null);
      storage.remove(GUEST_PENDING);
      queue.clear();
    },

    saves: {
      async list() {
        await ensureServerPlayer();
        return request<SaveList>("GET", gamePath("saves/"));
      },
      async load<T>(slot = "main") {
        const mine = readSlot<T>(slot);
        if (!transport || mine?.dirty) return mine ? { ...mine, source: "device" } : null;
        try {
          await ensureServerPlayer();
          // A device with no copy asks the list first: a new player's empty slot is
          // never a 404 in the browser's console.
          if (!mine) {
            const listed = await request<SaveList>("GET", gamePath("saves/"));
            if (!listed.results.some((save) => save.slot === slot)) return null;
          }
          const save = await request<ServerSave<T>>("GET", gamePath(`saves/${slot}/`));
          const state = fromServer(save, mine?.rev ?? 0);
          keepSlot(state);
          return state;
        } catch (error) {
          // GAME037: the server has no save in the slot (deleted on another device,
          // or never written). A 404 without a code is a path that does not exist.
          if (httpError(error)?.code === "GAME037") {
            if (mine && mine.version > 0) storage.remove(slotKey(slot));
            return mine && mine.version === 0 ? { ...mine, source: "device" } : null;
          }
          return mine ? { ...mine, source: "device" } : null;
        }
      },
      write<T>(slot: string, data: T, schemaVersion: number) {
        const mine = readSlot<T>(slot);
        const state = {
          slot,
          data,
          schemaVersion,
          version: mine?.version ?? 0,
          dirty: Boolean(transport),
          source: "device" as const,
          rev: (mine?.rev ?? 0) + 1,
        };
        keepSlot(state);
        if (transport) {
          queue.add({
            id: newIntent(),
            kind: "save",
            method: "PUT",
            path: gamePath(`saves/${slot}/`),
            body: { slot },
            key: `save:${slot}`,
          });
          void sync();
        }
        return state;
      },
      async remove(slot) {
        const mine = readSlot(slot);
        storage.remove(slotKey(slot));
        if (!transport || !mine || mine.version === 0) return;
        await ensureServerPlayer();
        try {
          await request("DELETE", gamePath(`saves/${slot}/`), {
            query: { base_version: mine.version },
          });
        } catch (error) {
          // GAME037: the slot is empty on the server already.
          if (httpError(error)?.code !== "GAME037") throw error;
        }
      },
    },

    async submitScore(board, value, scoreOptions = {}) {
      const { improved } = local.addScore(board, value);
      if (!transport) return { improved, queued: false };
      const body: Record<string, unknown> = {
        value,
        intent: scoreOptions.intent ?? newIntent(),
        played_at: (scoreOptions.playedAt ?? now()).toISOString(),
      };
      if (scoreOptions.run) body.run = scoreOptions.run;
      const result = await write<ScoreResponse>("score", `boards/${board}/scores/`, body);
      return { improved, ...result };
    },
    async leaderboard(board, boardOptions = {}) {
      const period = boardOptions.period ?? "all";
      if (transport) {
        try {
          return await request<BoardResponse>("GET", gamePath(`boards/${board}/`), {
            query: { period, limit: boardOptions.limit },
          });
        } catch (error) {
          if (httpError(error)) throw error;
        }
      }
      return local.board(board, period, player?.handle ?? "You", boardOptions.limit);
    },
    async around(board, aroundOptions = {}) {
      if (!transport) return null;
      try {
        await ensureServerPlayer();
        return await request<AroundResponse>("GET", gamePath(`boards/${board}/me/`), {
          query: { period: aroundOptions.period ?? "all", around: aroundOptions.around },
        });
      } catch (error) {
        if (httpError(error)) throw error;
        return null;
      }
    },

    async wallet() {
      if (!transport) return local.wallet();
      try {
        await ensureServerPlayer();
        const answer = await request<WalletResponse>("GET", gamePath("wallet/"));
        storage.setJson("cache.wallet", answer);
        return answer;
      } catch (error) {
        const cached = storage.getJson<WalletResponse>("cache.wallet");
        if (!httpError(error) && cached) return { ...cached, local: true };
        throw error;
      }
    },
    async ledger(ledgerOptions = {}) {
      if (!transport) {
        const results = local
          .ledger()
          .filter((e) => !ledgerOptions.currency || e.currency === ledgerOptions.currency);
        return { count: results.length, next: null, results };
      }
      await ensureServerPlayer();
      return request<LedgerPage>("GET", gamePath("wallet/ledger/"), {
        query: { currency: ledgerOptions.currency, page: ledgerOptions.page },
      });
    },
    async shop() {
      if (!transport) {
        const owned = local.wallet().items;
        return (options.local?.shop ?? []).map((item) => {
          const mine = owned.find((o) => o.item === item.key);
          return {
            ...item,
            real_money: false,
            owned: Boolean(mine),
            equipped: mine?.equipped ?? false,
          };
        });
      }
      return (await request<ListResponse<ShopItem>>("GET", gamePath("shop/"))).results;
    },
    async buy(item, buyOptions = {}) {
      if (!transport) return local.buy(item);
      await ensureServerPlayer();
      return request<BuyResponse>("POST", gamePath(`shop/${item}/buy/`), {
        body: { intent: buyOptions.intent ?? newIntent() },
      });
    },
    async equip(item) {
      if (!transport) return local.equip(item, true);
      await ensureServerPlayer();
      return request<EquipResponse>("POST", gamePath(`items/${item}/equip/`));
    },
    async unequip(item) {
      if (!transport) return local.equip(item, false);
      await ensureServerPlayer();
      return request<EquipResponse>("POST", gamePath(`items/${item}/unequip/`));
    },
    async rewards() {
      if (!transport) {
        return (options.local?.rewards ?? []).map((r) => ({
          key: r.key,
          title: r.title,
          kind: r.kind,
          currency: r.currency,
          amount: r.amount,
          trust: (r.kind === "ad" ? "client" : "server") as RewardTrust,
          callback: false,
          per_day: r.perDay ?? null,
          available: true,
          next_at: null,
        }));
      }
      await ensureServerPlayer();
      return (await request<ListResponse<RewardInfo>>("GET", gamePath("rewards/"))).results;
    },
    async claimReward(key, claimOptions = {}) {
      if (!transport) return local.claim(key);
      await ensureServerPlayer();
      return request<ClaimResponse>("POST", gamePath(`rewards/${key}/claim/`), {
        body: { intent: claimOptions.intent ?? newIntent() },
      });
    },
    async rewardIntent(key) {
      if (!transport) throw offline();
      await ensureServerPlayer();
      return request<{ intent: string; expires_at: string }>(
        "POST",
        gamePath(`rewards/${key}/intent/`),
      );
    },
    async adReward(key, show) {
      const info = (await client.rewards()).find((reward) => reward.key === key);
      if (!info || info.kind !== "ad") return { status: "unavailable", nextAt: null };
      if (!info.available) return { status: "unavailable", nextAt: info.next_at };
      const trust: RewardTrust = info.trust ?? (info.callback ? "callback" : "client");
      if (trust === "callback") {
        const { intent } = await client.rewardIntent(key);
        return (await show(intent)) ? { status: "pending", intent } : { status: "not-watched" };
      }
      if (!(await show(null))) return { status: "not-watched" };
      try {
        const answer = await client.claimReward(key);
        return {
          status: "granted",
          granted: answer.granted,
          capped: answer.capped,
          nextAt: answer.next_at,
        };
      } catch (error) {
        const refused = httpError(error) ?? (error instanceof LocalRuleError ? error : null);
        if (refused?.code !== "GAME017") throw error;
        const nextAt = (refused.data as { next_at?: string | null } | undefined)?.next_at;
        return { status: "unavailable", nextAt: nextAt ?? null };
      }
    },
    grant(currency, amount, reference) {
      if (transport) {
        throw new LocalRuleError(
          "GAME018",
          "the server grants currency: declare a reward on it instead",
        );
      }
      return local.grant(currency, amount, reference);
    },

    async daily() {
      if (transport) {
        try {
          if (player || token) await ensureServerPlayer();
          const answer = await request<{
            date: string;
            seed: number;
            server_time: string;
            resets_at: string;
            board: string | null;
            streak: Streak | null;
          }>("GET", gamePath("daily/"));
          learnClock(answer.server_time);
          storage.setJson("cache.daily", answer);
          return {
            date: answer.date,
            seed: answer.seed,
            source: "server",
            streak: answer.streak,
            board: answer.board,
            resetsAt: answer.resets_at,
          };
        } catch (error) {
          if (httpError(error)) throw error;
          const cached = storage.getJson<{
            date: string;
            seed: number;
            board: string | null;
            streak: Streak | null;
            resets_at: string;
          }>("cache.daily");
          if (cached && cached.date === today()) {
            return {
              date: cached.date,
              seed: cached.seed,
              source: "server",
              streak: cached.streak,
              board: cached.board,
              resetsAt: cached.resets_at,
            };
          }
        }
      }
      const seed = deviceDailySeed({ salt: game, timeZone: timeZone(), now });
      return { ...seed, streak: transport ? null : local.streak(), board: null, resetsAt: null };
    },
    async checkIn() {
      if (!transport) return local.checkIn();
      await ensureServerPlayer();
      return request<CheckInResponse>("POST", gamePath("daily/check-in/"));
    },

    async progress(progressEvents, progressOptions = {}) {
      if (!transport) return { queued: false, server: local.progress(progressEvents) };
      return write<ProgressResponse>("progress", "progress/", {
        events: progressEvents,
        intent: progressOptions.intent ?? newIntent(),
      });
    },
    async achievements() {
      if (!transport) return local.achievements();
      await ensureServerPlayer();
      return (await request<ListResponse<Achievement>>("GET", gamePath("achievements/"))).results;
    },
    async missions() {
      if (!transport) return [];
      await ensureServerPlayer();
      return (await request<ListResponse<Mission>>("GET", gamePath("missions/"))).results;
    },

    track(name, props) {
      const event: AnalyticsEvent = props ? { name, props } : { name };
      try {
        options.analyticsSink?.(event);
      } catch {
        // The project's sink never stops the game.
      }
      if (!transport) return;
      // An event the server does not declare would be refused: keep it off the wire.
      if (boot && !(name in boot.analytics)) return;
      pendingEvents.push(event);
      if (pendingEvents.length >= 20) flushEvents();
      else if (!eventTimer) eventTimer = setTimeout(flushEvents, options.analyticsBatchMs ?? 5000);
    },
    flushEvents,

    async multiplayerToken() {
      await ensureServerPlayer();
      return request<MultiplayerToken>("POST", gamePath("multiplayer/token/"));
    },

    sync,
    destroy() {
      clearInterval(timer);
      if (eventTimer) clearTimeout(eventTimer);
      if (typeof window !== "undefined") window.removeEventListener("online", onOnline);
      events.clear();
    },
  };
  return client;
}
