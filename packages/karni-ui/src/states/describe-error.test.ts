import { afterEach, describe, expect, it, vi } from "vitest";
import { KarniApiError } from "../schema/client";
import { describeError, errorSummary } from "./describe-error";

afterEach(() => vi.unstubAllGlobals());

const api = (status: number, data: unknown = {}): KarniApiError => new KarniApiError(status, data);

describe("describeError", () => {
  it("never shows a status code in what the user reads", () => {
    for (const status of [400, 401, 403, 404, 409, 410, 412, 422, 429, 500, 502, 503, 504]) {
      const { title, description } = describeError(api(status));
      expect(`${title} ${description}`).not.toMatch(/\d{3}/);
    }
  });

  it("names the action and resource a role does not allow", () => {
    const described = describeError(api(403), { action: "delete", resource: "events" });
    expect(described).toMatchObject({ kind: "forbidden", title: "You can't delete events" });
    expect(described.retryable).toBe(false);
  });

  it("keeps the server's own explanation but not DRF's stock sentence", () => {
    expect(
      describeError(api(403, { detail: "You do not have permission to perform this action." }))
        .detail,
    ).toBeUndefined();
    expect(describeError(api(403, { detail: "IMP006: blocked while impersonating" })).detail).toBe(
      "IMP006: blocked while impersonating",
    );
    expect(
      describeError(api(500, { detail: "Traceback (most recent call last)" })).detail,
    ).toBeUndefined();
  });

  it("tells offline from an unreachable server", () => {
    vi.stubGlobal("navigator", { onLine: false });
    expect(describeError(new TypeError("Failed to fetch"))).toMatchObject({
      kind: "offline",
      retryable: true,
    });
    vi.stubGlobal("navigator", { onLine: true });
    expect(describeError(new TypeError("Failed to fetch"))).toMatchObject({
      kind: "network",
      retryable: true,
    });
  });

  it("classifies every status family", () => {
    const kinds = Object.fromEntries(
      [401, 404, 400, 409, 429, 504, 503].map((status) => [
        status,
        describeError(api(status)).kind,
      ]),
    );
    expect(kinds).toEqual({
      401: "unauthenticated",
      404: "not-found",
      400: "validation",
      409: "conflict",
      429: "rate-limited",
      504: "timeout",
      503: "server",
    });
    expect(describeError(new Error("boom"), { action: "save", resource: "the event" }).title).toBe(
      "Couldn't save the event",
    );
    expect(errorSummary(api(404), { resource: "this event" })).toBe("Couldn't find this event");
  });
});
