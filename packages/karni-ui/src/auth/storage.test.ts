/**
 * TokenStorage adapter tests.
 */
import { describe, expect, it, vi } from "vitest";
import { createLocalStorageTokenStorage, createMemoryTokenStorage } from "./storage";

describe("createLocalStorageTokenStorage", () => {
  it("round-trips through localStorage under the default key", () => {
    const storage = createLocalStorageTokenStorage();
    try {
      expect(storage.get()).toBeNull();
      storage.set("refresh-1");
      expect(storage.get()).toBe("refresh-1");
      expect(globalThis.localStorage.getItem("karni.refreshToken")).toBe("refresh-1");
      // A second adapter over the same key sees the same token (reload survival).
      expect(createLocalStorageTokenStorage().get()).toBe("refresh-1");
      storage.clear();
      expect(storage.get()).toBeNull();
    } finally {
      storage.clear();
    }
  });

  it("isolates custom keys", () => {
    const a = createLocalStorageTokenStorage("app-a");
    const b = createLocalStorageTokenStorage("app-b");
    try {
      a.set("token-a");
      expect(b.get()).toBeNull();
      expect(a.get()).toBe("token-a");
    } finally {
      a.clear();
      b.clear();
    }
  });

  it("degrades to a no-op instead of throwing when localStorage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const storage = createLocalStorageTokenStorage();
    expect(() => storage.set("x")).not.toThrow();
    expect(storage.get()).toBeNull();
    expect(() => storage.clear()).not.toThrow();
  });
});

describe("createMemoryTokenStorage", () => {
  it("round-trips in memory and isolates instances", () => {
    const a = createMemoryTokenStorage();
    const b = createMemoryTokenStorage();
    expect(a.get()).toBeNull();
    a.set("secret");
    expect(a.get()).toBe("secret");
    expect(b.get()).toBeNull();
    a.clear();
    expect(a.get()).toBeNull();
  });
});
