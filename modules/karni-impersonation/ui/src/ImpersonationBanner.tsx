/**
 * <ImpersonationBanner> — the persistent bar naming both identities, with
 * a one-click exit, for a SPA. Renders nothing outside an impersonated
 * session. Mount it once near the root (inside <AuthProvider>).
 *
 * Reads `GET /impersonation-sessions/current/`; Stop posts `…/stop/` and
 * adopts the impersonator's tokens (JWT) or re-syncs `/me/` (session mode).
 */
import { Button, cn } from "@karni/ui";
import { useEffect, useState, type ReactElement } from "react";
import { useImpersonation, useStopImpersonation } from "./hooks";

export interface ImpersonationBannerProps {
  /** Refetch interval in ms so the minutes left stay honest; default 60 000. */
  poll?: false | number;
  /** Called after a successful stop (e.g. navigate home). */
  onStopped?: () => void;
  className?: string;
}

function minutesLeft(expiresAt: string, now: number): number {
  const end = new Date(expiresAt).getTime();
  if (Number.isNaN(end)) return 0;
  return Math.max(Math.floor((end - now) / 60_000), 0);
}

function errorText(error: unknown): string {
  if (error instanceof Error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === "object" && data !== null && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return error.message;
  }
  return "Could not stop impersonating.";
}

export function ImpersonationBanner({
  poll = 60_000,
  onStopped,
  className,
}: ImpersonationBannerProps): ReactElement | null {
  const query = useImpersonation({ poll });
  const stop = useStopImpersonation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const session = query.data?.session ?? null;
  if (session === null || !session.active) return null;
  const left = minutesLeft(session.expires_at, now);
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="impersonation-banner"
      className={cn(
        "fixed inset-x-0 bottom-0 z-50 flex flex-wrap items-center justify-center gap-3 bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground shadow-lg",
        className,
      )}
    >
      <span>
        You are acting as <strong>{session.target.email ?? session.target.id}</strong> — signed in
        as {session.actor.email ?? session.actor.id}.{" "}
        <span className="opacity-80">
          {left} {left === 1 ? "minute" : "minutes"} left
        </span>
      </span>
      <Button
        size="sm"
        variant="secondary"
        disabled={stop.isPending}
        onClick={() => stop.mutate(undefined, { onSuccess: () => onStopped?.() })}
      >
        {stop.isPending ? "Stopping…" : "Stop impersonating"}
      </Button>
      {stop.error !== null && stop.error !== undefined ? (
        <span role="alert">{errorText(stop.error)}</span>
      ) : null}
    </div>
  );
}
