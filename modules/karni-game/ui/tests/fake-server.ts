import {
  GameApiError,
  OfflineError,
  type Transport,
  type TransportRequest,
} from "../src/client/transport";
import type { GameBoot, Player, ServerSave } from "../src/client/types";

/**
 * A small in-memory karni-game server for the client's tests: the parts of
 * docs/game-api.md the client calls, with its codes. `down` makes every call
 * fail as a dropped network would.
 */
export class FakeGameServer implements Transport {
  down = false;
  /** The account the next calls are signed in as (null: none). */
  account: string | null = null;
  calls: string[] = [];
  readonly players = new Map<string, Player>();
  readonly tokens = new Map<string, string>();
  readonly accounts = new Map<string, string>();
  readonly saves = new Map<string, ServerSave>();
  readonly scores: { player: string; board: string; value: number; playedAt?: string }[] = [];
  /** Refuse a score's played_at (GAME036), as a server whose window it is outside. */
  refusePlayedAt = false;
  /** The ad rewards it declares, by key: who vouches for each. */
  adRewards: Record<string, "callback" | "client"> = {
    "ad-coins": "client",
    "ad-gems": "callback",
  };
  readonly intents = new Map<string, string>();
  readonly events: unknown[] = [];
  balance = 100;
  owned = new Set<string>();
  streak = 0;
  checkedIn = false;
  failNext: { status: number; data: unknown } | null = null;
  /** The next call is done on the server but its answer never arrives. */
  loseNextAnswer = false;

  boot: GameBoot = {
    game: { slug: "block-hopper", title: "Block Hopper" },
    server: {
      time: "2026-11-19T08:30:00Z",
      date: "2026-11-19",
      timezone: "UTC",
      resets_at: "2026-11-20T00:00:00Z",
    },
    config: { jump: 9 },
    flags: { night: true },
    save: { schema_version: 1, max_bytes: 65536, max_slots: 5 },
    boards: [{ key: "high", title: "High", order: "desc", periods: ["all", "daily"] }],
    currencies: [{ key: "coins", title: "Coins", cap: 999 }],
    analytics: { jumped: { height: "int" } },
  };

  private error(status: number, code: string, extra: Record<string, unknown> = {}): never {
    throw new GameApiError(status, { detail: `${code}: test`, code, ...extra });
  }

  private who(headers: Record<string, string> | undefined): string | null {
    if (this.account) {
      let id = this.accounts.get(this.account);
      if (!id) {
        id = `acct-${this.account}`;
        this.accounts.set(this.account, id);
        this.players.set(id, { id, handle: this.account, guest: false });
      }
      return id;
    }
    const token = headers?.["X-Player-Token"];
    if (!token) return null;
    const id = this.tokens.get(token);
    if (!id) this.error(401, "GAME003");
    return id;
  }

  private need(headers: Record<string, string> | undefined): string {
    const id = this.who(headers);
    if (!id) this.error(401, "GAME002");
    return id;
  }

  private replay(body: unknown): unknown {
    const intent = (body as { intent?: string } | undefined)?.intent;
    if (!intent) return undefined;
    const seen = this.intents.get(intent);
    if (seen === undefined) {
      this.intents.set(intent, JSON.stringify(body));
      return undefined;
    }
    if (seen !== JSON.stringify(body)) this.error(409, "GAME033");
    return { replayed: true };
  }

  async request<T>(path: string, options: TransportRequest = {}): Promise<T> {
    if (this.down) throw new OfflineError("network down");
    const method = options.method ?? "GET";
    const route = path.replace(/^\/api\/game\//, "");
    this.calls.push(`${method} ${route}`);
    if (this.failNext) {
      const { status, data } = this.failNext;
      this.failNext = null;
      throw new GameApiError(status, data);
    }
    const answer = this.route(method, route, options) as T;
    if (this.loseNextAnswer) {
      this.loseNextAnswer = false;
      throw new OfflineError("the answer was lost");
    }
    return answer;
  }

  private route(method: string, route: string, options: TransportRequest): unknown {
    const body = options.body as Record<string, unknown> | undefined;
    const headers = options.headers;
    if (method === "POST" && route === "guest/") {
      const intent = body?.intent as string | undefined;
      const seen = intent ? this.intents.get(`guest:${intent}`) : undefined;
      if (intent && seen !== undefined) {
        const [handle, earlier] = JSON.parse(seen) as [string | null, string];
        if (handle !== ((body?.handle as string | undefined) ?? null)) this.error(409, "GAME033");
        const token = `gt_${earlier}_again`;
        this.tokens.set(token, earlier);
        return { token, player: this.players.get(earlier), replayed: true };
      }
      const id = `p${this.players.size + 1}`;
      if (intent) {
        this.intents.set(
          `guest:${intent}`,
          JSON.stringify([(body?.handle as string | undefined) ?? null, id]),
        );
      }
      const player: Player = {
        id,
        handle: (body?.handle as string) ?? `Player ${id}`,
        guest: true,
      };
      this.players.set(id, player);
      const token = `gt_${id}`;
      this.tokens.set(token, id);
      return { token, player };
    }
    if (route === "me/" && method === "GET") {
      return this.players.get(this.need(headers));
    }
    if (route === "me/" && method === "PATCH") {
      const id = this.need(headers);
      const player = { ...(this.players.get(id) as Player), handle: body?.handle as string };
      this.players.set(id, player);
      return player;
    }
    if (method === "POST" && route === "upgrade/") {
      if (!this.account) this.error(401, "GAME002");
      const token = (body?.guest_token as string) ?? headers?.["X-Player-Token"];
      const guest = token ? this.tokens.get(token) : undefined;
      if (!guest || !token) this.error(409, "GAME028");
      this.tokens.delete(token);
      this.accounts.set(this.account, guest);
      const player = { ...(this.players.get(guest) as Player), guest: false };
      this.players.set(guest, player);
      return {
        player,
        merged: {
          adopted: true,
          saves: { moved: 0, kept_both: [] },
          scores: 0,
          currencies: {},
          items: 0,
          unlocks: 0,
        },
      };
    }
    const [game, ...rest] = route.split("/");
    if (game !== "block-hopper") this.error(404, "GAME006");
    const tail = rest.join("/");
    if (tail === "" && method === "GET") return this.boot;
    if (tail === "saves/" && method === "GET") {
      const id = this.need(headers);
      const results = [...this.saves.entries()]
        .filter(([key]) => key.startsWith(`${id}:`))
        .map(([, save]) => ({ slot: save.slot, version: save.version, schema_version: 1 }));
      return { results, max_slots: 5, max_bytes: 65536 };
    }
    if (tail.startsWith("saves/")) {
      const id = this.need(headers);
      const slot = tail.split("/")[1] ?? "";
      const key = `${id}:${slot}`;
      const current = this.saves.get(key);
      if (method === "GET") {
        if (!current) this.error(404, "GAME037");
        return current;
      }
      if (method === "PUT") {
        const base = body?.base_version as number;
        if ((current?.version ?? 0) !== base) this.error(409, "GAME008", { save: current });
        const saved: ServerSave = {
          slot,
          version: base + 1,
          schema_version: body?.schema_version as number,
          data: body?.data,
        };
        this.saves.set(key, saved);
        return saved;
      }
      if (method === "DELETE") {
        if (!current) this.error(404, "GAME037");
        this.saves.delete(key);
        return null;
      }
    }
    const board = tail.match(/^boards\/([^/]+)\/(scores\/|me\/)?$/);
    if (board) {
      const key = board[1] ?? "";
      if (board[2] === "scores/") {
        const id = this.need(headers);
        const playedAt = body?.played_at as string | undefined;
        if (playedAt && this.refusePlayedAt) this.error(400, "GAME036", { window: 86400 });
        const replayed = this.replay(body);
        const value = body?.value as number;
        if (value > 100_000) this.error(400, "GAME013");
        if (!replayed) this.scores.push({ player: id, board: key, value, playedAt });
        return {
          score: { id: `s${this.scores.length}`, value, status: "accepted", created_at: "" },
          best: {},
          improved: ["all"],
          ...(replayed as object),
        };
      }
      const entries = this.scores
        .filter((s) => s.board === key)
        .sort((a, b) => b.value - a.value)
        .map((s, index) => ({
          rank: index + 1,
          handle: this.players.get(s.player)?.handle ?? "",
          value: s.value,
          me: false,
        }));
      return {
        board: { key, title: key, order: "desc", periods: ["all"] },
        period: "all",
        period_start: null,
        entries,
        me: null,
      };
    }
    if (tail === "wallet/") {
      this.need(headers);
      return {
        balances: [{ currency: "coins", balance: this.balance, cap: 999 }],
        items: [...this.owned].map((item) => ({ item, equipped: false })),
      };
    }
    const buy = tail.match(/^shop\/([^/]+)\/buy\/$/);
    if (buy) {
      this.need(headers);
      if (this.balance < 50) this.error(409, "GAME016", { balance: this.balance, needed: 50 });
      this.balance -= 50;
      this.owned.add(buy[1] ?? "");
      return {
        item: { key: buy[1], equipped: false },
        balance: { currency: "coins", balance: this.balance },
      };
    }
    if (tail === "daily/") {
      return {
        date: "2026-11-19",
        seed: 1738294011,
        server_time: "2026-11-19T08:30:00Z",
        resets_at: "2026-11-20T00:00:00Z",
        board: "daily",
        streak: this.who(headers)
          ? { current: this.streak, best: this.streak, last_day: null, checked_in: this.checkedIn }
          : null,
        rewards: [],
      };
    }
    if (tail === "daily/check-in/") {
      this.need(headers);
      const newDay = !this.checkedIn;
      if (newDay) this.streak += 1;
      this.checkedIn = true;
      return {
        new_day: newDay,
        streak: {
          current: this.streak,
          best: this.streak,
          last_day: "2026-11-19",
          checked_in: true,
        },
        granted: [],
      };
    }
    if (tail === "progress/") {
      this.need(headers);
      const replayed = this.replay(body);
      return { counters: {}, unlocked: [], completed: [], ...(replayed as object) };
    }
    if (tail === "events/") {
      this.need(headers);
      const replayed = this.replay(body);
      if (!replayed) this.events.push(...((body?.events as unknown[]) ?? []));
      return {
        accepted: (body?.events as unknown[]).length,
        rejected: [],
        ...(replayed as object),
      };
    }
    if (tail === "rewards/") {
      this.need(headers);
      return {
        results: Object.entries(this.adRewards).map(([key, trust]) => ({
          key,
          title: key,
          kind: "ad",
          currency: "coins",
          amount: 25,
          trust,
          callback: trust === "callback",
          per_day: 3,
          claimed_today: 0,
          available: true,
          next_at: null,
        })),
      };
    }
    const intentFor = tail.match(/^rewards\/([^/]+)\/intent\/$/);
    if (intentFor) {
      this.need(headers);
      return { intent: `signed:${intentFor[1]}`, expires_at: "2026-11-19T09:30:00Z" };
    }
    const claim = tail.match(/^rewards\/([^/]+)\/claim\/$/);
    if (claim) {
      this.need(headers);
      if (this.adRewards[claim[1] ?? ""] === "callback") this.error(403, "GAME018");
      this.balance += 25;
      return {
        granted: { currency: "coins", amount: 25, balance: this.balance },
        capped: false,
        next_at: null,
      };
    }
    throw new GameApiError(404, { detail: "Not found." });
  }
}
