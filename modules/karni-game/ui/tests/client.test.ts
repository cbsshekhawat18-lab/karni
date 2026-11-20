import { afterEach, describe, expect, it } from "vitest";
import {
  OfflineError,
  createGameClient,
  createStorage,
  dateSeed,
  memoryStorage,
  type GameClient,
  type GameClientOptions,
  type GameStorage,
} from "../src";
import { FakeGameServer } from "./fake-server";

const clients: GameClient[] = [];
afterEach(() => {
  for (const client of clients.splice(0)) client.destroy();
});

let counter = 0;
const make = (
  options: Partial<Omit<GameClientOptions, "server">> & { server?: FakeGameServer | null } = {},
): { client: GameClient; server: FakeGameServer | null; storage: GameStorage } => {
  const storage = options.storage ?? createStorage({ namespace: "bh", backend: memoryStorage() });
  const server = options.server === undefined ? new FakeGameServer() : options.server;
  const client = createGameClient({
    game: "block-hopper",
    storage,
    newIntent: () => `intent-${(counter += 1)}`,
    now: () => new Date("2026-11-19T08:30:00Z"),
    online: () => true,
    ...options,
    server: server ? { transport: server, signedIn: () => server.account !== null } : undefined,
  });
  clients.push(client);
  return { client, server, storage };
};

describe("a game with no server", () => {
  const setup = {
    boards: { high: { title: "High" } },
    currencies: [{ key: "coins", title: "Coins", cap: 500 }],
    shop: [
      { key: "red-cap", title: "Red cap", slot: "hat", price: { currency: "coins", amount: 30 } },
    ],
    rewards: [
      { key: "daily-coins", title: "Daily", kind: "daily" as const, currency: "coins", amount: 10 },
    ],
    achievements: [{ key: "hopper", title: "Hopper", counter: "jumps", goal: 2 }],
  };

  it("plays every call on the device, by the same rules", async () => {
    const seen: string[] = [];
    const { client } = make({
      server: null,
      local: setup,
      defaults: { config: { jump: 7 }, flags: { night: true } },
      analyticsSink: (event) => seen.push(event.name),
    });
    expect(client.hasServer).toBe(false);
    expect(client.online).toBe(false);
    await expect(client.boot()).resolves.toEqual({ source: "defaults", server: null });
    expect(client.config("jump", 1)).toBe(7);
    expect(client.config("missing", 1)).toBe(1);
    expect(client.flag("night")).toBe(true);

    const player = await client.signInGuest("Swift Fox");
    expect(player).toMatchObject({ handle: "Swift Fox", guest: true, local: true });

    expect(await client.submitScore("high", 120)).toEqual({
      improved: ["all", "daily", "weekly"],
      queued: false,
    });
    const board = await client.leaderboard("high");
    expect(board.local).toBe(true);
    expect(board.entries[0]).toMatchObject({ handle: "Swift Fox", value: 120 });

    client.grant("coins", 50);
    await client.buy("red-cap");
    expect((await client.wallet()).balances[0]?.balance).toBe(20);
    expect((await client.shop())[0]).toMatchObject({ owned: true });
    expect((await client.checkIn()).granted[0]?.amount).toBe(10);
    expect(
      (await client.progress([{ counter: "jumps", amount: 2 }])).server?.unlocked,
    ).toHaveLength(1);

    const daily = await client.daily();
    expect(daily).toMatchObject({
      date: "2026-11-19",
      source: "device",
      seed: dateSeed("2026-11-19", "block-hopper"),
    });
    expect(daily.streak?.current).toBe(1);

    const slot = client.saves.write("main", { level: 3 }, 1);
    expect(slot.dirty).toBe(false);
    expect((await client.saves.load<{ level: number }>("main"))?.data.level).toBe(3);

    client.track("jumped", { height: 3 });
    expect(seen).toEqual(["jumped"]);
    expect(client.queue.size).toBe(0);
    await expect(client.rewardIntent("x")).rejects.toBeInstanceOf(OfflineError);
  });
});

describe("a game with a server", () => {
  it("boots with the server's config, flags and clock, and caches them for offline", async () => {
    const { client, server, storage } = make({ now: () => new Date("2026-11-19T08:00:00Z") });
    const booted = await client.boot();
    expect(booted.source).toBe("server");
    expect(client.config("jump", 1)).toBe(9);
    expect(client.flag("night")).toBe(true);
    expect(client.now().toISOString()).toBe("2026-11-19T08:30:00.000Z");
    if (server) server.down = true;
    const again = make({ storage, server });
    await expect(again.client.boot()).resolves.toMatchObject({ source: "cache" });
    expect(again.client.config("jump", 1)).toBe(9);
  });

  it("sends the guest token in the header the server names", async () => {
    const seen: string[] = [];
    const storage = createStorage({ namespace: "hdr", backend: memoryStorage() });
    storage.set("token", "gt_9");
    const client = createGameClient({
      game: "block-hopper",
      storage,
      online: () => true,
      server: {
        tokenHeader: "X-Game-Token",
        transport: {
          request: async <T>(_path: string, request?: { headers?: Record<string, string> }) => {
            seen.push(Object.keys(request?.headers ?? {}).join(","));
            return { balances: [], items: [] } as T;
          },
        },
      },
    });
    clients.push(client);
    await client.wallet();
    expect(seen).toEqual(["X-Game-Token"]);
  });

  it("signs in a guest with a server token and keeps it", async () => {
    const { client, server, storage } = make();
    const player = await client.signInGuest("Swift Fox");
    expect(player).toMatchObject({ id: "p1", guest: true });
    expect(storage.get("token")).toBe("gt_p1");
    const renamed = await client.setHandle("Calm Owl");
    expect(renamed.handle).toBe("Calm Owl");
    expect(server?.calls).toContain("PATCH me/");
  });

  it("writes a save at once and sends it, with the version it was based on", async () => {
    const { client, server } = make();
    await client.signInGuest();
    client.saves.write("main", { level: 1 }, 1);
    await client.sync();
    expect(server?.saves.get("p1:main")).toMatchObject({ version: 1, data: { level: 1 } });
    client.saves.write("main", { level: 2 }, 1);
    await client.sync();
    expect(server?.saves.get("p1:main")).toMatchObject({ version: 2, data: { level: 2 } });
    const loaded = await client.saves.load<{ level: number }>("main");
    expect(loaded).toMatchObject({
      version: 2,
      dirty: false,
      source: "server",
      data: { level: 2 },
    });
  });

  it("keeps the server's copy on a conflict by default, and this device's copy beside it", async () => {
    const { client, server, storage } = make();
    await client.signInGuest();
    server?.saves.set("p1:main", {
      slot: "main",
      version: 5,
      schema_version: 1,
      data: { level: 9 },
    });
    const conflicts: string[] = [];
    client.on("conflict", ({ kept }) => conflicts.push(kept));
    client.saves.write("main", { level: 2 }, 1);
    await client.sync();
    expect(conflicts).toEqual(["server"]);
    expect(server?.saves.get("p1:main")?.version).toBe(5);
    expect((await client.saves.load<{ level: number }>("main"))?.data.level).toBe(9);
    expect(storage.getJson<{ data: unknown }>("slot.main.conflict")?.data).toEqual({ level: 2 });
  });

  it("lets the game settle a conflict, writing on top of the server's version", async () => {
    const { client, server } = make({
      onConflict: (mine, theirs) => ({
        data: {
          level: Math.max(
            (mine.data as { level: number }).level,
            (theirs.data as { level: number }).level,
          ),
          merged: true,
        },
      }),
    });
    await client.signInGuest();
    server?.saves.set("p1:main", {
      slot: "main",
      version: 5,
      schema_version: 1,
      data: { level: 9 },
    });
    client.saves.write("main", { level: 12 }, 1);
    await client.sync();
    expect(server?.saves.get("p1:main")).toMatchObject({
      version: 6,
      data: { level: 12, merged: true },
    });
    expect(client.queue.size).toBe(0);
  });

  it("sends a score at once when online", async () => {
    const { client, server } = make();
    await client.signInGuest();
    const result = await client.submitScore("high", 300, {
      run: { seed: "1", inputs: [[0, "jump"]] },
    });
    expect(result.queued).toBe(false);
    expect(result.server?.score.status).toBe("accepted");
    expect(server?.scores).toEqual([
      { player: "p1", board: "high", value: 300, playedAt: "2026-11-19T08:30:00.000Z" },
    ]);
    const board = await client.leaderboard("high");
    expect(board.local).toBeUndefined();
    expect(board.entries[0]?.value).toBe(300);
  });

  it("refuses a score the server refuses, without queueing it", async () => {
    const { client } = make();
    await client.signInGuest();
    await expect(client.submitScore("high", 500_000)).rejects.toMatchObject({ code: "GAME013" });
    expect(client.queue.size).toBe(0);
  });

  it("buys and claims on the server, and refuses currency from the client", async () => {
    const { client } = make();
    await client.signInGuest();
    expect((await client.buy("red-cap")).balance.balance).toBe(50);
    await expect(client.buy("blue-cap")).resolves.toBeDefined();
    await expect(client.buy("green-cap")).rejects.toMatchObject({ code: "GAME016" });
    expect((await client.claimReward("ad-coins")).granted.balance).toBe(25);
    expect(() => client.grant("coins", 5)).toThrow(/GAME018/);
  });

  it("uses the server's daily seed and streak, and checks in on the server", async () => {
    const { client } = make();
    await client.signInGuest();
    const daily = await client.daily();
    expect(daily).toMatchObject({ source: "server", seed: 1738294011, board: "daily" });
    expect((await client.checkIn()).streak.current).toBe(1);
  });

  it("batches declared analytics and keeps undeclared ones off the wire", async () => {
    const seen: string[] = [];
    const { client, server } = make({ analyticsSink: (event) => seen.push(event.name) });
    await client.boot();
    await client.signInGuest();
    client.track("jumped", { height: 2 });
    client.track("undeclared");
    client.flushEvents();
    await client.sync();
    expect(seen).toEqual(["jumped", "undeclared"]);
    expect(server?.events).toEqual([{ name: "jumped", props: { height: 2 } }]);
  });
});

describe("offline first", () => {
  it("plays offline, then joins the server and sends everything in order", async () => {
    const server = new FakeGameServer();
    server.down = true;
    const { client } = make({ server });
    const guest = await client.signInGuest("Swift Fox");
    expect(guest.local).toBe(true);
    const score = await client.submitScore("high", 250);
    expect(score.queued).toBe(true);
    expect((await client.progress([{ counter: "jumps", amount: 3 }])).queued).toBe(true);
    client.saves.write("main", { level: 4 }, 1);
    // The write tried the network at once: let that attempt end while it is down.
    await client.sync();
    expect(client.queue.size).toBe(3);
    expect(client.online).toBe(false);
    expect((await client.leaderboard("high")).local).toBe(true);

    server.down = false;
    const synced: string[] = [];
    client.on("synced", ({ write }) => synced.push(write.kind));
    // The waiting writes back off after the failed attempt: let them be due again.
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(synced).toEqual(["score", "progress", "save"]);
    expect(client.player).toMatchObject({ handle: "Swift Fox", guest: true });
    expect(client.player?.local).toBeUndefined();
    expect(server.scores).toEqual([
      { player: "p1", board: "high", value: 250, playedAt: "2026-11-19T08:30:00.000Z" },
    ]);
    expect(server.saves.get("p1:main")?.data).toEqual({ level: 4 });
    expect(client.online).toBe(true);
  });

  it("never counts a write twice when its answer was lost (the intent is sent again)", async () => {
    const { client, server } = make();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    server.loseNextAnswer = true;
    const result = await client.submitScore("high", 400);
    expect(result.queued).toBe(true);
    expect(server.scores).toHaveLength(1);
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(server.scores).toHaveLength(1);
    expect(client.queue.size).toBe(0);
  });

  it("drops a queued write the server refuses for good, and says so", async () => {
    const server = new FakeGameServer();
    server.down = true;
    const { client } = make({ server });
    await client.signInGuest();
    await client.submitScore("high", 900_000);
    server.down = false;
    const rejected: (string | null)[] = [];
    client.on("rejected", ({ code }) => rejected.push(code));
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(rejected).toEqual(["GAME013"]);
    expect(client.queue.size).toBe(0);
  });

  it("keeps a write while the server waits for a player (guests off until sign-in)", async () => {
    const { client, server } = make();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    server.failNext = { status: 403, data: { code: "GAME005" } };
    const result = await client.progress([{ counter: "jumps", amount: 1 }]);
    expect(result.queued).toBe(true);
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(client.queue.size).toBe(0);
  });

  it("waits as long as a rate limit asks", async () => {
    const { client, server } = make();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    server.down = true;
    await client.progress([{ counter: "jumps", amount: 1 }]);
    server.down = false;
    server.failNext = { status: 429, data: { code: "GAME015", retry_after: 30 } };
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(client.queue.size).toBe(1);
    expect(client.queue.nextAt()).toBeGreaterThan(Date.now() + 25_000);
  });

  it("keeps the server's daily seed of today offline, and uses the device's otherwise", async () => {
    const { client, server, storage } = make();
    await client.signInGuest();
    await client.daily();
    if (!server) throw new Error("no server");
    server.down = true;
    expect(await client.daily()).toMatchObject({ source: "server", seed: 1738294011 });
    const tomorrow = make({ storage, server, now: () => new Date("2026-11-20T09:00:00Z") });
    expect(await tomorrow.client.daily()).toMatchObject({ source: "device", date: "2026-11-20" });
    await expect(client.checkIn()).rejects.toBeInstanceOf(OfflineError);
    await expect(client.buy("red-cap")).rejects.toBeInstanceOf(OfflineError);
  });
});

describe("guest to account", () => {
  it("upgrades through Karni's sign-in: the token is dropped and unchanged slots are read again", async () => {
    const { client, server, storage } = make();
    await client.signInGuest("Swift Fox");
    client.saves.write("main", { level: 6 }, 1);
    await client.sync();
    if (!server) throw new Error("no server");
    server.account = "fox@example.test";
    const answer = await client.upgrade();
    expect(answer.player).toMatchObject({ id: "p1", guest: false });
    expect(storage.get("token")).toBeNull();
    expect(storage.get("slot.main")).toBeNull();
    expect((await client.saves.load<{ level: number }>("main"))?.data.level).toBe(6);
    expect(server.calls).toContain("POST upgrade/");
  });

  it("plays a signed-in account as its own player, and makes no guest", async () => {
    const server = new FakeGameServer();
    server.account = "owl@example.test";
    const { client, storage } = make({ server });
    const player = await client.signInGuest();
    expect(player).toMatchObject({ id: "acct-owl@example.test", guest: false });
    expect(server.calls).not.toContain("POST guest/");
    expect(storage.get("token")).toBeNull();
  });

  it("keeps a guest on the device as the player after sign-in, until the upgrade", async () => {
    const { client, server } = make();
    await client.signInGuest("Swift Fox");
    if (!server) throw new Error("no server");
    server.account = "fox@example.test";
    expect(await client.signInGuest()).toMatchObject({ id: "p1", guest: true });
    expect((await client.upgrade()).player).toMatchObject({ guest: false });
  });

  it("forgets a guest the server no longer knows, and makes a new one on the next call", async () => {
    const { client, server, storage } = make();
    await client.signInGuest();
    server?.tokens.clear();
    await expect(client.wallet()).rejects.toMatchObject({ code: "GAME003" });
    expect(storage.get("token")).toBeNull();
    expect(client.player).toBeNull();
    await client.wallet();
    expect(storage.get("token")).toBe("gt_p2");
  });

  it("signs out: player, token and waiting writes are forgotten", async () => {
    const server = new FakeGameServer();
    server.down = true;
    const { client, storage } = make({ server });
    await client.signInGuest();
    await client.submitScore("high", 1);
    client.signOut();
    expect(client.player).toBeNull();
    expect(storage.get("token")).toBeNull();
    expect(client.queue.size).toBe(0);
  });
});

describe("the server's contract, as it closed the client's gaps", () => {
  it("sends a score with when it was played, so one sent after midnight is on the day it was played", async () => {
    const server = new FakeGameServer();
    let clock = new Date("2026-11-18T23:58:10Z");
    const { client } = make({ server, now: () => clock });
    await client.signInGuest();
    server.down = true;
    expect((await client.submitScore("high", 640)).queued).toBe(true);
    clock = new Date("2026-11-19T00:05:00Z");
    server.down = false;
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(server.scores).toEqual([
      { player: "p1", board: "high", value: 640, playedAt: "2026-11-18T23:58:10.000Z" },
    ]);
  });

  it("sends a score again without played_at when the server does not trust it (GAME036), never dropping it", async () => {
    const { client, server } = make();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    server.refusePlayedAt = true;
    const result = await client.submitScore("high", 300);
    expect(result.server?.score.status).toBe("accepted");
    expect(server.scores).toEqual([{ player: "p1", board: "high", value: 300 }]);
    server.down = true;
    await client.submitScore("high", 310);
    server.down = false;
    const rejected: unknown[] = [];
    client.on("rejected", (event) => rejected.push(event));
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(rejected).toEqual([]);
    expect(server.scores.map((score) => score.value)).toEqual([300, 310]);
  });

  it("asks for a guest with an intent, so a lost answer never makes a second guest", async () => {
    const server = new FakeGameServer();
    const { client, storage } = make({ server });
    server.loseNextAnswer = true;
    const guest = await client.signInGuest("Swift Fox");
    // The server made the guest, the answer was lost: the game plays as a device guest.
    expect(guest.local).toBe(true);
    expect(storage.getJson<{ intent: string }>("guest.pending")?.intent).toMatch(/^intent-/);
    await client.wallet();
    expect(server.players.size).toBe(1);
    expect(client.player).toMatchObject({ id: "p1", handle: "Swift Fox" });
    expect(client.player?.local).toBeUndefined();
    expect(storage.get("token")).toBe("gt_p1_again");
    expect(storage.get("guest.pending")).toBeNull();
  });

  it("starts a guest's issue again with a new intent when the server says it was used (GAME033)", async () => {
    const server = new FakeGameServer();
    const { client, storage } = make({ server });
    server.intents.set("guest:intent-old-1", JSON.stringify(["Calm Owl", "p0"]));
    storage.setJson("guest.pending", { intent: "intent-old-1", body: { handle: "Swift Fox" } });
    const player = await client.signInGuest("Swift Fox");
    expect(player).toMatchObject({ id: "p1", handle: "Swift Fox", guest: true });
    expect(storage.get("guest.pending")).toBeNull();
  });

  it("sends an analytics batch with its intent, so a retried batch is published once", async () => {
    const { client, server } = make();
    await client.boot();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    client.track("jumped", { height: 2 });
    server.loseNextAnswer = true;
    client.flushEvents();
    await client.sync();
    expect(server.events).toHaveLength(1);
    const [waiting] = client.queue.list();
    expect(waiting?.body).toMatchObject({ intent: waiting?.id });
    for (const write of client.queue.list()) write.notBefore = 0;
    await client.sync();
    expect(server.events).toHaveLength(1);
    expect(client.queue.size).toBe(0);
  });

  it("asks a new device's list first, so an empty slot is never fetched", async () => {
    const { client, server } = make();
    await client.signInGuest();
    expect(await client.saves.load("main")).toBeNull();
    expect(server?.calls.filter((call) => call.includes("saves/"))).toEqual([
      "GET block-hopper/saves/",
    ]);
    server?.saves.set("p1:main", {
      slot: "main",
      version: 2,
      schema_version: 1,
      data: { level: 4 },
    });
    expect(await client.saves.load<{ level: number }>("main")).toMatchObject({
      version: 2,
      data: { level: 4 },
    });
  });

  it("forgets a slot the server says is empty (GAME037), and keeps it on a 404 without a code", async () => {
    const { client, server, storage } = make();
    await client.signInGuest();
    if (!server) throw new Error("no server");
    client.saves.write("main", { level: 3 }, 1);
    await client.sync();
    // Deleted on another device.
    server.saves.delete("p1:main");
    expect(await client.saves.load("main")).toBeNull();
    expect(storage.get("slot.main")).toBeNull();

    client.saves.write("alt", { level: 5 }, 1);
    await client.sync();
    server.failNext = { status: 404, data: { detail: "Not found." } };
    expect(await client.saves.load<{ level: number }>("alt")).toMatchObject({
      source: "device",
      data: { level: 5 },
    });
    server.saves.delete("p1:alt");
    await expect(client.saves.remove("alt")).resolves.toBeUndefined();
  });

  it("plays an ad reward by its trust: claimed after the ad, or left to the portal's callback", async () => {
    const { client, server } = make();
    await client.signInGuest();
    const shown: (string | null)[] = [];
    const watch = async (intent: string | null): Promise<boolean> => {
      shown.push(intent);
      return true;
    };
    const claimed = await client.adReward("ad-coins", watch);
    expect(claimed).toMatchObject({ status: "granted", granted: { amount: 25, balance: 125 } });
    const pending = await client.adReward("ad-gems", watch);
    expect(pending).toEqual({ status: "pending", intent: "signed:ad-gems" });
    // The callback reward's intent went to the ad call, and the client claimed nothing for it.
    expect(shown).toEqual([null, "signed:ad-gems"]);
    expect(server?.calls.filter((call) => call.endsWith("/claim/"))).toEqual([
      "POST block-hopper/rewards/ad-coins/claim/",
    ]);
    expect(await client.adReward("ad-coins", async () => false)).toEqual({
      status: "not-watched",
    });
    expect(await client.adReward("missing", watch)).toEqual({
      status: "unavailable",
      nextAt: null,
    });
  });

  it("plays an ad reward on the device with no server, and says when the day's claims are used", async () => {
    const { client } = make({
      server: null,
      local: {
        currencies: [{ key: "coins", title: "Coins", cap: 500 }],
        rewards: [
          { key: "ad-coins", title: "Ad", kind: "ad", currency: "coins", amount: 5, perDay: 1 },
        ],
      },
    });
    expect((await client.rewards())[0]?.trust).toBe("client");
    expect(await client.adReward("ad-coins", async () => true)).toMatchObject({
      status: "granted",
      granted: { balance: 5 },
    });
    expect(await client.adReward("ad-coins", async () => true)).toEqual({
      status: "unavailable",
      nextAt: null,
    });
  });
});
