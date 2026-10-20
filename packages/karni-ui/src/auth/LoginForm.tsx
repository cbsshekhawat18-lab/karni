/**
 * LoginForm — the sign-in form every app needs (contract: auth).
 *
 * Email + password against `useAuth().login`, with the error inline. On
 * success it calls `onSuccess(user)` (navigate there). When the backend's
 * 2FA gate fires, `on2FA` receives the ephemeral token so the app can render
 * its code step (`POST <authBasePath>/2fa/login/`); without a handler the
 * form explains that a code is required. Render it inside `AuthProvider`,
 * e.g. as `AuthGuard`'s `fallback`.
 */
import * as React from "react";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { Button } from "../components/primitives/button";
import { Input } from "../components/primitives/input";
import { Label } from "../components/primitives/label";
import { useAuth } from "./provider";
import type { KarniUser } from "./types";

registerComponentRole("login-form", "LoginForm");

export interface LoginFormProps {
  /** Called with the signed-in user; navigate from here. */
  onSuccess?: (user: KarniUser) => void;
  /** Called when the account needs a second factor (the token completes it). */
  on2FA?: (ephemeralToken: string) => void;
  /** Heading above the fields; `null` renders none. Default "Sign in". */
  title?: React.ReactNode;
  /** Text under the heading (demo logins, a signup link, ...). */
  description?: React.ReactNode;
  /** The submit button's label. Default "Sign in". */
  submitLabel?: React.ReactNode;
  /** Shown while the auth status is "loading" is irrelevant here; this disables the form. */
  disabled?: boolean;
  className?: string;
}

/** Email and password sign-in form with inline errors and a callback for the two-factor step. */
export function LoginForm({
  onSuccess,
  on2FA,
  title = "Sign in",
  description,
  submitLabel = "Sign in",
  disabled = false,
  className,
}: LoginFormProps) {
  const { login } = useAuth();
  const id = React.useId();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const result = await login(
        String(data.get("email") ?? ""),
        String(data.get("password") ?? ""),
      );
      if ("ok" in result) {
        onSuccess?.(result.user);
      } else if (on2FA !== undefined) {
        on2FA(result.ephemeralToken);
      } else {
        setError("This account needs a two-factor code; the app has not enabled that step.");
      }
    } catch {
      setError("That email and password do not match.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className={cn("space-y-4", className)}
      onSubmit={(event) => void submit(event)}
      aria-busy={busy}
      noValidate={false}
    >
      {title !== null ? <h2 className="text-lg font-semibold">{title}</h2> : null}
      {description !== undefined ? (
        <p className="text-sm text-muted-foreground">{description}</p>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor={`${id}-email`}>Email</Label>
        <Input
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="email"
          required
          disabled={disabled || busy}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-password`}>Password</Label>
        <Input
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={disabled || busy}
        />
      </div>
      {error !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button type="submit" disabled={disabled || busy}>
        {submitLabel}
      </Button>
    </form>
  );
}
