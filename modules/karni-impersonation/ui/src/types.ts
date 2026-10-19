/** Shapes `/api/impersonation-sessions/` serves (karni_impersonation.api.SessionSerializer). */

export interface Person {
  id: string | number;
  email?: string;
}

export type EndReason = "" | "stopped" | "expired" | "logout" | "swept";

export interface ImpersonationSession {
  id: string;
  actor: Person;
  target: Person;
  reason: string;
  started_at: string;
  expires_at: string;
  ended_at: string | null;
  end_reason: EndReason;
  active: boolean;
  batch_id: number | null;
  created_at: string;
}

/** `GET …/current/`. */
export interface CurrentResponse {
  session: ImpersonationSession | null;
}

/** `POST …/start/` and `…/stop/`: the session, plus tokens in JWT mode. */
export interface SessionResponse {
  session: ImpersonationSession;
  access?: string;
  refresh?: string;
}
