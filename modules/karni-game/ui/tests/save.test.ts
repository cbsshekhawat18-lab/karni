import { describe, expect, it } from "vitest";
import { createSave, createStorage, memoryStorage, probeStorage, type StorageLike } from "../src";

const blocked: StorageLike = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("SecurityError");
  },
  removeItem: () => {
    throw new Error("SecurityError");
  },
};

describe("createStorage", () => {
  it("namespaces keys and lists only its own", () => {
    const backend = memoryStorage();
    backend.setItem("other.save", "x");
    const storage = createStorage({ namespace: "block-hopper", backend });
    expect(storage.kind).toBe("local");
    storage.set("save", "1");
    storage.setJson("settings", { volume: 0.5 });
    expect(backend.getItem("block-hopper.save")).toBe("1");
    expect(storage.keys().sort()).toEqual(["save", "settings"]);
    expect(storage.getJson("settings")).toEqual({ volume: 0.5 });
    storage.set("broken", "{");
    expect(storage.getJson("broken")).toBeUndefined();
    storage.remove("save");
    expect(storage.get("save")).toBeNull();
  });

  it("falls back to memory when storage is blocked, and never throws", () => {
    expect(probeStorage(blocked)).toBe(false);
    const storage = createStorage({ namespace: "g", backend: blocked });
    expect(storage.kind).toBe("memory");
    expect(storage.persistent).toBe(false);
    expect(storage.set("a", "1")).toBe(true);
    expect(storage.get("a")).toBe("1");
  });

  it("uses localStorage by default", () => {
    window.localStorage.clear();
    const storage = createStorage({ namespace: "default-test" });
    expect(storage.kind).toBe("local");
    storage.set("k", "v");
    expect(window.localStorage.getItem("default-test.k")).toBe("v");
  });

  it("reports a full storage as not kept", () => {
    const full = memoryStorage();
    const storage = createStorage({ namespace: "g", backend: full });
    full.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    expect(storage.set("big", "x")).toBe(false);
  });

  it("reads a portal's data module first and writes both", () => {
    const local = memoryStorage();
    const portal = memoryStorage();
    portal.setItem("g.save", "from-portal");
    local.setItem("g.save", "from-local");
    const storage = createStorage({ namespace: "g", backend: local, portal });
    expect(storage.get("save")).toBe("from-portal");
    storage.set("save", "new");
    expect(local.getItem("g.save")).toBe("new");
    expect(portal.getItem("g.save")).toBe("new");
  });
});

interface V2 {
  best: number;
  coins: number;
  skins: string[];
}

const setup = (backend = memoryStorage()) => {
  const storage = createStorage({ namespace: "g", backend });
  let tick = 0;
  const save = createSave<V2>({
    storage,
    version: 2,
    defaults: () => ({ best: 0, coins: 0, skins: ["plain"] }),
    migrations: {
      0: (legacy) => ({ best: (legacy as { high?: number }).high ?? 0 }),
      1: (data) => ({ ...(data as object), skins: ["plain"] }),
    },
    now: () => new Date(Date.UTC(2026, 0, 1, 0, 0, tick++)),
  });
  return { backend, storage, save };
};

describe("createSave", () => {
  it("starts new, writes a versioned envelope and loads it back", () => {
    const { backend, save } = setup();
    expect(save.load()).toEqual({ data: { best: 0, coins: 0, skins: ["plain"] }, status: "new" });
    expect(save.write({ best: 10, coins: 3, skins: ["plain"] })).toBe(true);
    const stored = JSON.parse(backend.getItem("g.save") ?? "{}") as { v: number; savedAt: string };
    expect(stored.v).toBe(2);
    expect(stored.savedAt).toMatch(/^2026-01-01T/);
    expect(save.load()).toMatchObject({ status: "loaded", data: { best: 10, coins: 3 } });
  });

  it("runs the migrations in order, from an unversioned save too", () => {
    const { backend, save } = setup();
    backend.setItem("g.save", JSON.stringify({ high: 42 }));
    expect(save.load()).toEqual({
      data: { best: 42, coins: 0, skins: ["plain"] },
      status: "migrated",
      fromVersion: 0,
    });
    backend.setItem("g.save", JSON.stringify({ v: 1, savedAt: "x", data: { best: 5, coins: 9 } }));
    expect(save.load()).toMatchObject({
      status: "migrated",
      fromVersion: 1,
      data: { coins: 9, skins: ["plain"] },
    });
  });

  it("boots with the defaults on corrupt data and keeps the bad copy", () => {
    const { backend, storage, save } = setup();
    backend.setItem("g.save", "{not json");
    const result = save.load();
    expect(result.status).toBe("corrupt");
    expect(result.data).toEqual({ best: 0, coins: 0, skins: ["plain"] });
    expect(result.backupKey).toBeDefined();
    expect(storage.get(result.backupKey ?? "")).toBe("{not json");
    // The same bad copy is not kept twice.
    expect(save.load().backupKey).toBe(result.backupKey);
    expect(save.backups()).toHaveLength(1);
  });

  it("treats a failing migration or validation as corrupt", () => {
    const { backend, save } = setup();
    backend.setItem("g.save", JSON.stringify({ v: 2, savedAt: "x", data: "a string" }));
    expect(save.load().status).toBe("corrupt");
    const storage = createStorage({ namespace: "h", backend });
    const strict = createSave({
      storage,
      version: 3,
      defaults: () => ({ n: 0 }),
      migrations: {},
      validate: (data) => {
        if (typeof (data as { n?: unknown }).n !== "number") throw new Error("bad n");
        return data as { n: number };
      },
    });
    backend.setItem("h.save", JSON.stringify({ v: 2, savedAt: "x", data: { n: 1 } }));
    expect(strict.load()).toMatchObject({ status: "corrupt", fromVersion: 2 });
    backend.setItem("h.save", JSON.stringify({ v: 3, savedAt: "x", data: { n: "1" } }));
    expect(strict.load().status).toBe("corrupt");
  });

  it("keeps a save from a newer build instead of overwriting it", () => {
    const { backend, storage, save } = setup();
    backend.setItem("g.save", JSON.stringify({ v: 9, savedAt: "x", data: {} }));
    const result = save.load();
    expect(result.status).toBe("newer");
    expect(result.fromVersion).toBe(9);
    expect(storage.get(result.backupKey ?? "")).toContain('"v":9');
  });

  it("keeps only the last few corrupt copies", () => {
    const { backend, save } = setup();
    for (let n = 0; n < 5; n += 1) {
      backend.setItem("g.save", `{bad ${n}`);
      save.load();
    }
    expect(save.backups()).toHaveLength(3);
  });

  it("merges new fields over old saves by default", () => {
    const { backend, save } = setup();
    backend.setItem("g.save", JSON.stringify({ v: 2, savedAt: "x", data: { best: 7 } }));
    expect(save.load().data).toEqual({ best: 7, coins: 0, skins: ["plain"] });
  });

  it("upgrades data from elsewhere the same way", () => {
    const { save } = setup();
    expect(save.upgrade({ high: 3 }, 0)).toEqual({ best: 3, coins: 0, skins: ["plain"] });
    expect(() => createSave({ storage: setup().storage, version: 0, defaults: () => 0 })).toThrow();
  });

  it("works on blocked storage (memory) without throwing", () => {
    const storage = createStorage({ namespace: "g", backend: blocked });
    const save = createSave({ storage, version: 1, defaults: () => ({ n: 0 }) });
    expect(save.write({ n: 1 })).toBe(true);
    expect(save.load()).toMatchObject({ status: "loaded", data: { n: 1 } });
    save.clear();
    expect(save.load().status).toBe("new");
  });
});
