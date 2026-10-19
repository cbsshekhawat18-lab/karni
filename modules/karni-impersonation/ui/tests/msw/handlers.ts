/**
 * Simulated karni_impersonation backend: `current/` answers `currentFixture`
 * (set per test), `stop/` records the call and answers the ended session plus
 * actor tokens. `resetMswData()` runs after every test.
 */
import { HttpResponse, http } from "msw";
import type { ImpersonationSession } from "../../src/types";

export const API_BASE = "http://localhost/api";

export const sessionFixture: ImpersonationSession = {
  id: "imp-1",
  actor: { id: "u-1", email: "support@example.com" },
  target: { id: "u-2", email: "customer@example.com" },
  reason: "ticket #7",
  started_at: "2026-10-20T10:00:00Z",
  expires_at: new Date(Date.now() + 25 * 60_000).toISOString(),
  ended_at: null,
  end_reason: "",
  active: true,
  batch_id: 7,
  created_at: "2026-10-20T10:00:00Z",
};

export const state: { current: ImpersonationSession | null; stops: number; me: string } = {
  current: sessionFixture,
  stops: 0,
  me: "customer@example.com",
};

export function resetMswData(): void {
  state.current = sessionFixture;
  state.stops = 0;
  state.me = "customer@example.com";
}

export const handlers = [
  http.get(`${API_BASE}/impersonation-sessions/current/`, () =>
    HttpResponse.json({ session: state.current }),
  ),
  http.post(`${API_BASE}/impersonation-sessions/stop/`, () => {
    state.stops += 1;
    const ended = { ...sessionFixture, active: false, end_reason: "stopped", ended_at: "now" };
    state.current = null;
    state.me = "support@example.com";
    return HttpResponse.json({ session: ended, access: "actor-access", refresh: "actor-refresh" });
  }),
  http.get(`${API_BASE}/auth/me/`, () =>
    HttpResponse.json({
      id: state.me === "support@example.com" ? "u-1" : "u-2",
      email: state.me,
      roles: [],
    }),
  ),
  http.post(`${API_BASE}/auth/refresh/`, () =>
    HttpResponse.json({ access: "target-access", refresh: "target-refresh" }),
  ),
  http.get(`${API_BASE}/schema/`, () =>
    HttpResponse.json({ "x-karni-auth-mode": "jwt", paths: {} }),
  ),
];
