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
import { AlertIcon, OfflineIcon } from "../components/primitives/icons";
import { Input } from "../components/primitives/input";
import { Label } from "../components/primitives/label";
import { KarniApiError } from "../schema/client";
import { describeError, type KarniErrorDescription } from "../states/describe-error";
import type { ErrorSlotProps } from "../states/ErrorState";
import { PendingButton } from "../states/PendingButton";
import { useAuth } from "./provider";
import type { KarniUser } from "./types";

registerComponentRole("login-form", "LoginForm");

/** What the `Error` slot receives: ErrorSlotProps plus the message, already worded for sign-in. */
export interface LoginFormErrorProps extends ErrorSlotProps {
  /** Put this id on the message's root: the inputs' `aria-describedby` points at it. */
  id: string;
  /**
   * The failure in plain words: wrong credentials ("That email and password
   * do not match"), throttling ("Wait 42 seconds"), offline, a server error.
   */
  described: KarniErrorDescription;
}

/**
 * The replaceable parts of LoginForm. Pass any subset as `slots`;
 * `defaultLoginFormSlots` holds Karni's own, to wrap them.
 */
export interface LoginFormSlots {
  /** The message under the fields when signing in fails (announced as an alert). */
  Error: React.ComponentType<LoginFormErrorProps>;
}

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
  /** Disables the form (e.g. while the auth status is still "loading"). */
  disabled?: boolean;
  /** Focus the email field when the form appears. Default true: signing in is the page's purpose. */
  autoFocus?: boolean;
  /** Replace parts of the form: Error. */
  slots?: Partial<LoginFormSlots>;
  className?: string;
}

/**
 * A field's label-to-control gap as Tailwind 3's `space-y` draws it: a top
 * margin on every child after the first. Tailwind 4's `space-y` puts a bottom
 * margin on the inline <label> instead, which an inline element ignores, so
 * the gap is spelled out to render the same under both.
 */
const FIELD_GAP = "[&>:not([hidden])~:not([hidden])]:mt-1";

/** Thrown inside the form when the account needs a code and the app has no `on2FA`. */
class TwoFactorUnavailable extends Error {
  constructor() {
    super("This account needs a two-factor code; the app has not enabled that step.");
    this.name = "TwoFactorUnavailable";
  }
}

/** DRF's throttle message: "Request was throttled. Expected available in 42 seconds." */
function throttleSeconds(error: KarniApiError): number | undefined {
  const data = error.data;
  const detail =
    typeof data === "object" && data !== null ? (data as Record<string, unknown>)["detail"] : data;
  const match = typeof detail === "string" ? /available in (\d+) seconds?/i.exec(detail) : null;
  return match?.[1] !== undefined ? Number(match[1]) : undefined;
}

/** The first message of a DRF 400 body (`{"email": ["Enter a valid email address."]}`). */
function firstMessage(data: unknown): string | undefined {
  if (typeof data !== "object" || data === null) return undefined;
  for (const value of Object.values(data as Record<string, unknown>)) {
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return undefined;
}

/**
 * A sign-in failure in plain words. A 401 is the credentials (the backend
 * does not say which one is wrong, so neither does this); a 429 says how long
 * to wait; everything else is describeError's ("You're offline", "Something
 * went wrong on our side"), never a status code.
 */
function describeLoginError(error: unknown): KarniErrorDescription {
  if (error instanceof TwoFactorUnavailable) {
    return {
      kind: "unauthenticated",
      title: "This account needs a two-factor code",
      description: "The app has not enabled that step. Ask the site's administrator.",
      retryable: false,
    };
  }
  if (error instanceof KarniApiError) {
    if (error.status === 401) {
      return {
        kind: "unauthenticated",
        title: "That email and password do not match",
        description: "Check both and try again.",
        retryable: false,
        status: 401,
      };
    }
    if (error.status === 400) {
      return {
        kind: "validation",
        title: "Check your email and password",
        description: firstMessage(error.data) ?? "Fill in both fields, then try again.",
        retryable: false,
        status: 400,
      };
    }
    if (error.status === 429) {
      const seconds = throttleSeconds(error);
      return {
        kind: "rate-limited",
        title: "Too many sign-in attempts",
        description:
          seconds !== undefined
            ? `Wait ${seconds} ${seconds === 1 ? "second" : "seconds"}, then try again.`
            : "Wait a few minutes, then try again.",
        retryable: true,
        status: 429,
      };
    }
  }
  return describeError(error, { action: "sign in" });
}

function DefaultLoginError({ id, described }: LoginFormErrorProps): React.ReactElement {
  const Icon =
    described.kind === "offline" || described.kind === "network" ? OfflineIcon : AlertIcon;
  return (
    <div
      id={id}
      role="alert"
      data-error-kind={described.kind}
      className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="space-y-1">
        <p className="font-medium text-foreground">{described.title}</p>
        <p className="text-muted-foreground">{described.description}</p>
        {described.detail !== undefined && described.kind !== "rate-limited" ? (
          <p className="text-xs text-muted-foreground">{described.detail}</p>
        ) : null}
      </div>
    </div>
  );
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultLoginFormSlots: LoginFormSlots = { Error: DefaultLoginError };

/**
 * Email and password sign-in form with inline errors and a callback for the two-factor step.
 *
 * Wrong credentials, throttling, a dropped connection and a server error each
 * read differently; the message is announced, both fields point at it
 * (`aria-describedby`) and are marked invalid when they are the problem.
 * After a failure the email stays; wrong credentials clear the password and
 * focus it. Escape hatch: `slots.Error`.
 */
export function LoginForm({
  onSuccess,
  on2FA,
  title = "Sign in",
  description,
  submitLabel = "Sign in",
  disabled = false,
  autoFocus = true,
  slots,
  className,
}: LoginFormProps) {
  const Slots: LoginFormSlots = { ...defaultLoginFormSlots, ...slots };
  const { login } = useAuth();
  const id = React.useId();
  const errorId = `${id}-error`;
  const [busy, setBusy] = React.useState(false);
  const [failure, setFailure] = React.useState<{ error: unknown; attempt: number } | null>(null);
  const emailRef = React.useRef<HTMLInputElement>(null);
  const passwordRef = React.useRef<HTMLInputElement>(null);
  const submitRef = React.useRef<HTMLButtonElement>(null);
  const attempts = React.useRef(0);

  const described = failure !== null ? describeLoginError(failure.error) : null;
  // The fields are the problem only when the backend refused them (401, 400) —
  // not when it throttled, failed or asked for a second factor.
  const invalid =
    failure !== null &&
    failure.error instanceof KarniApiError &&
    (failure.error.status === 401 || failure.error.status === 400);

  // Focus follows the failure once the fields are enabled again: wrong
  // credentials → the (cleared) password, a refused field → the email, the
  // rest (offline, throttled, server) → the button that tries again.
  React.useEffect(() => {
    if (failure === null || busy) return;
    const kind = describeLoginError(failure.error);
    if (failure.error instanceof KarniApiError && failure.error.status === 401) {
      passwordRef.current?.focus();
    } else if (kind.kind === "validation") {
      emailRef.current?.focus();
    } else {
      submitRef.current?.focus();
    }
  }, [failure, busy]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    attempts.current += 1;
    const attempt = attempts.current;
    setBusy(true);
    setFailure(null);
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
        setFailure({ error: new TwoFactorUnavailable(), attempt });
      }
    } catch (error) {
      if (error instanceof KarniApiError && error.status === 401 && passwordRef.current !== null) {
        passwordRef.current.value = "";
      }
      setFailure({ error, attempt });
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
      <div className={FIELD_GAP}>
        <Label htmlFor={`${id}-email`}>Email</Label>
        <Input
          ref={emailRef}
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="email"
          // Signing in is what the page is for; a form placed elsewhere passes autoFocus={false}.
          autoFocus={autoFocus}
          required
          disabled={disabled || busy}
          className={cn(invalid && "border-destructive")}
          aria-invalid={invalid || undefined}
          aria-describedby={failure !== null ? errorId : undefined}
        />
      </div>
      <div className={FIELD_GAP}>
        <Label htmlFor={`${id}-password`}>Password</Label>
        <Input
          ref={passwordRef}
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={disabled || busy}
          className={cn(invalid && "border-destructive")}
          aria-invalid={invalid || undefined}
          aria-describedby={failure !== null ? errorId : undefined}
        />
      </div>
      {failure !== null && described !== null ? (
        // Keyed by attempt: the same message after a second failed attempt is announced again.
        <React.Fragment key={failure.attempt}>
          <Slots.Error
            id={errorId}
            error={failure.error}
            context={{ action: "sign in" }}
            described={described}
          />
        </React.Fragment>
      ) : null}
      <PendingButton
        ref={submitRef}
        type="submit"
        disabled={disabled}
        pending={busy}
        pendingLabel="Signing in…"
      >
        {submitLabel}
      </PendingButton>
    </form>
  );
}
