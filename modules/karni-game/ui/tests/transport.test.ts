import { describe, expect, it } from "vitest";
import {
  GameApiError,
  OfflineError,
  csrfHeader,
  fetchTransport,
  httpError,
} from "../src/client/transport";

describe("fetchTransport", () => {
  it("joins the path and query, sends JSON with the account's token, parses the answer", async () => {
    const seen: { url: string; init: RequestInit }[] = [];
    const transport = fetchTransport({
      baseUrl: "https://example.test/",
      getAccessToken: () => "jwt-1",
      getHeaders: () => ({ "X-Extra": "1" }),
      fetch: async (url, init) => {
        seen.push({ url: String(url), init: init ?? {} });
        return new Response(JSON.stringify({ ok: true }), { status: 201 });
      },
    });
    const answer = await transport.request<{ ok: boolean }>("/api/game/g/", {
      method: "POST",
      query: { period: "daily", skip: undefined },
      body: { value: 1 },
      headers: { "X-Player-Token": "gt_1" },
    });
    expect(answer).toEqual({ ok: true });
    expect(seen[0]?.url).toBe("https://example.test/api/game/g/?period=daily");
    const headers = seen[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-1");
    expect(headers["X-Player-Token"]).toBe("gt_1");
    expect(headers["X-Extra"]).toBe("1");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(seen[0]?.init.body).toBe('{"value":1}');
  });

  it("throws GameApiError with the contract's code, and handles an empty body", async () => {
    const transport = fetchTransport({
      fetch: async (url) =>
        String(url).endsWith("/gone/")
          ? new Response(null, { status: 204 })
          : new Response(
              JSON.stringify({ detail: "GAME008: stale", code: "GAME008", save: { version: 4 } }),
              {
                status: 409,
              },
            ),
    });
    await expect(transport.request("/gone/", { method: "DELETE" })).resolves.toBeNull();
    const error = await transport.request("/x/").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(GameApiError);
    expect(httpError(error)).toMatchObject({ status: 409, code: "GAME008" });
    expect((error as GameApiError).message).toBe("GAME008: stale");
  });

  it("turns a failed fetch into OfflineError", async () => {
    const transport = fetchTransport({
      fetch: async () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await expect(transport.request("/x/")).rejects.toBeInstanceOf(OfflineError);
    expect(httpError(new OfflineError())).toBeNull();
  });

  it("reads Django's CSRF cookie for session sign-in", () => {
    document.cookie = "csrftoken=abc%3D1";
    expect(csrfHeader()).toEqual({ "X-CSRFToken": "abc=1" });
    expect(csrfHeader("missing")).toEqual({});
  });
});
