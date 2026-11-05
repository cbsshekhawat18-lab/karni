/**
 * Experimental. OtpLoginForm: sign in with a one-time code sent by email.
 *
 * Two steps on `useOtpLogin`. The email step asks for the address and sends
 * the code. The code step has one input for the whole code (filled by the
 * phone's "from Messages/Mail" suggestion through `autocomplete="one-time-code"`),
 * a button for a new code that waits out a cooldown, and a way back to the
 * email step. On success it calls `onSuccess(user)`. The 2FA step goes to
 * `on2FA`, exactly as LoginForm's does, and a new account that waits for an
 * administrator is shown as its own state.
 */
import * as React from "react";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { Button } from "../components/primitives/button";
import { AlertIcon, OfflineIcon } from "../components/primitives/icons";
import { Input } from "../components/primitives/input";
import { Label } from "../components/primitives/label";
import { KarniApiError } from "../schema/client";
import { describeError, type KarniErrorDescription } from "../states/describe-error";
import type { ErrorSlotProps } from "../states/ErrorState";
import { PendingButton } from "../states/PendingButton";
import type { KarniUser } from "./types";
import { useOtpLogin } from "./useOtpLogin";

registerComponentRole("code-sign-in", "OtpLoginForm");

/** Experimental. What the `Error` slot receives: the failure, already worded for this form. */
export interface OtpLoginFormErrorProps extends ErrorSlotProps {
  /** Put this id on the message's root: the input's `aria-describedby` points at it. */
  id: string;
  described: KarniErrorDescription;
}

/** Experimental. What the `Approval` slot receives when the new account waits for an administrator. */
export interface OtpLoginFormApprovalProps {
  /** Put this id on the message's root. */
  id: string;
  /** The server's explanation. */
  detail: string;
}

/** Experimental. The replaceable parts of OtpLoginForm. `defaultOtpLoginFormSlots` holds Karni's own. */
export interface OtpLoginFormSlots {
  Error: React.ComponentType<OtpLoginFormErrorProps>;
  Approval: React.ComponentType<OtpLoginFormApprovalProps>;
}

export interface OtpLoginFormProps {
  /** Called with the signed-in user. Navigate from here. */
  onSuccess?: (user: KarniUser) => void;
  /** Called when the account needs a second factor (the token completes it), as in LoginForm. */
  on2FA?: (ephemeralToken: string) => void;
  /** Called when a new account was created and waits for an administrator. */
  onAwaitingApproval?: (detail: string) => void;
  /** Seconds before a new code may be asked for. Default 30. */
  resendCooldown?: number;
  /** Heading above the fields. `null` renders none. Default "Sign in with a code". */
  title?: React.ReactNode;
  /** Text under the heading on the email step. */
  description?: React.ReactNode;
  /** The address the email field starts with. */
  defaultEmail?: string;
  /** Disables the form (e.g. while the auth status is still "loading"). */
  disabled?: boolean;
  /** Focus the first field of each step. Default true. */
  autoFocus?: boolean;
  /** Replace parts of the form: Error, Approval. */
  slots?: Partial<OtpLoginFormSlots>;
  className?: string;
}

/** The label-to-control gap LoginForm uses, the same under Tailwind 3 and 4. */
const FIELD_GAP = "[&>:not([hidden])~:not([hidden])]:mt-1";

/** Thrown inside the form when the account needs a code and the app has no `on2FA`. */
class TwoFactorUnavailable extends Error {
  constructor() {
    super("This account needs a two-factor code, but the app has not enabled that step.");
    this.name = "TwoFactorUnavailable";
  }
}

function karniCode(error: KarniApiError): string | undefined {
  const data = error.data;
  if (typeof data !== "object" || data === null) return undefined;
  const code = (data as Record<string, unknown>)["code"];
  return typeof code === "string" ? code : undefined;
}

/** DRF's throttle message: "Request was throttled. Expected available in 42 seconds." */
function throttleSeconds(error: KarniApiError): number | undefined {
  const data = error.data;
  const detail =
    typeof data === "object" && data !== null ? (data as Record<string, unknown>)["detail"] : data;
  const match = typeof detail === "string" ? /available in (\d+) seconds?/i.exec(detail) : null;
  return match?.[1] !== undefined ? Number(match[1]) : undefined;
}

function described(
  kind: KarniErrorDescription["kind"],
  title: string,
  description: string,
  status: number | undefined,
  retryable = false,
): KarniErrorDescription {
  return status === undefined
    ? { kind, title, description, retryable }
    : { kind, title, description, retryable, status };
}

/**
 * Experimental. A sign-in-by-code failure in plain words, from the Karni code
 * of the refusal (E235, E226, E236), never a status code. Exported for a
 * project's own form.
 */
export function describeOtpError(error: unknown): KarniErrorDescription {
  if (error instanceof TwoFactorUnavailable) {
    return described(
      "unauthenticated",
      "This account needs a two-factor code",
      "The app has not enabled that step. Ask the site's administrator.",
      401,
    );
  }
  if (!(error instanceof KarniApiError)) return describeError(error, { action: "sign in" });
  const status = error.status;
  switch (karniCode(error)) {
    case "E235":
      return described(
        "unauthenticated",
        "That code did not work",
        "Check it and try again, or ask for a new code. Only the newest code works.",
        status,
      );
    case "E226":
      return described(
        "forbidden",
        "This account is not active",
        "Ask the site's administrator to activate it.",
        status,
      );
    case "E236":
      return described(
        "not-found",
        "Sign-in with a code is not available here",
        "Sign in another way.",
        status,
      );
    default:
      break;
  }
  if (status === 429) {
    const seconds = throttleSeconds(error);
    return described(
      "rate-limited",
      "Too many attempts",
      seconds !== undefined
        ? `Wait ${seconds} ${seconds === 1 ? "second" : "seconds"}, then try again.`
        : "Wait a few minutes, then try again.",
      status,
      true,
    );
  }
  if (status === 400) {
    return described(
      "validation",
      "Check the email address",
      "Enter the address you sign in with, then try again.",
      status,
    );
  }
  return describeError(error, { action: "sign in" });
}

function DefaultOtpError({ id, described: message }: OtpLoginFormErrorProps): React.ReactElement {
  const Icon = message.kind === "offline" || message.kind === "network" ? OfflineIcon : AlertIcon;
  return (
    <div
      id={id}
      role="alert"
      data-error-kind={message.kind}
      className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="space-y-1">
        <p className="font-medium text-foreground">{message.title}</p>
        <p className="text-muted-foreground">{message.description}</p>
      </div>
    </div>
  );
}

function DefaultOtpApproval({ id }: OtpLoginFormApprovalProps): React.ReactElement {
  return (
    <div
      id={id}
      role="status"
      data-state="awaiting-approval"
      className="rounded-md border border-border bg-muted p-3 text-sm"
    >
      <p className="font-medium text-foreground">Your account is waiting for approval</p>
      <p className="text-muted-foreground">
        An administrator must approve it before you can sign in. Try again once they have.
      </p>
    </div>
  );
}

/** Experimental. Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultOtpLoginFormSlots: OtpLoginFormSlots = {
  Error: DefaultOtpError,
  Approval: DefaultOtpApproval,
};

function minutes(seconds: number): string {
  const whole = Math.max(1, Math.floor(seconds / 60));
  return `${whole} ${whole === 1 ? "minute" : "minutes"}`;
}

/**
 * Experimental. Passwordless sign-in: an email step, then a code step with one input for the code.
 *
 * Accessible: labelled fields, the code input sized to the server's code
 * length (`inputMode="numeric"`, `autocomplete="one-time-code"`), refusals
 * announced as alerts and pointed at by `aria-describedby`, approval pending
 * as a status. A wrong code clears the input and focuses it. Escape hatch:
 * `slots`, or `useOtpLogin` for a form of your own.
 */
export function OtpLoginForm({
  onSuccess,
  on2FA,
  onAwaitingApproval,
  resendCooldown = 30,
  title = "Sign in with a code",
  description,
  defaultEmail,
  disabled = false,
  autoFocus = true,
  slots,
  className,
}: OtpLoginFormProps): React.ReactElement {
  const Slots: OtpLoginFormSlots = { ...defaultOtpLoginFormSlots, ...slots };
  const login = useOtpLogin({ resendCooldown });
  const id = React.useId();
  const messageId = `${id}-message`;
  const codeRef = React.useRef<HTMLInputElement>(null);
  const emailRef = React.useRef<HTMLInputElement>(null);
  const [outcome, setOutcome] = React.useState<
    { kind: "error"; error: unknown; attempt: number } | { kind: "approval"; detail: string } | null
  >(null);
  const attempts = React.useRef(0);
  const busy = login.status === "sending" || login.status === "verifying";
  const onCodeStep = login.step === "code";

  // The code step starts on the code. After a failure the field is focused again
  // (a refused code is cleared first), once the fields are enabled again.
  React.useEffect(() => {
    if (busy) return;
    if (onCodeStep) {
      if (autoFocus || outcome !== null) codeRef.current?.focus();
    } else if (outcome?.kind === "error") {
      emailRef.current?.focus();
    }
  }, [autoFocus, busy, onCodeStep, outcome]);

  function fail(error: unknown): void {
    attempts.current += 1;
    setOutcome({ kind: "error", error, attempt: attempts.current });
  }

  async function sendCode(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "");
    setOutcome(null);
    try {
      await login.send(email);
    } catch (error) {
      fail(error);
    }
  }

  async function resend(): Promise<void> {
    setOutcome(null);
    try {
      await login.resend();
      if (codeRef.current !== null) codeRef.current.value = "";
    } catch (error) {
      fail(error);
    }
  }

  async function verifyCode(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    setOutcome(null);
    try {
      const result = await login.verify(code);
      if ("ok" in result) {
        onSuccess?.(result.user);
      } else if ("requires2fa" in result) {
        if (on2FA !== undefined) on2FA(result.ephemeralToken);
        else fail(new TwoFactorUnavailable());
      } else {
        setOutcome({ kind: "approval", detail: result.detail });
        onAwaitingApproval?.(result.detail);
      }
    } catch (error) {
      if (codeRef.current !== null) codeRef.current.value = "";
      fail(error);
    }
  }

  function back(): void {
    setOutcome(null);
    login.back();
  }

  const message =
    outcome?.kind === "error" ? (
      // Keyed by attempt: the same message after another failed attempt is announced again.
      <React.Fragment key={outcome.attempt}>
        <Slots.Error
          id={messageId}
          error={outcome.error}
          context={{ action: "sign in" }}
          described={describeOtpError(outcome.error)}
        />
      </React.Fragment>
    ) : outcome?.kind === "approval" ? (
      <Slots.Approval id={messageId} detail={outcome.detail} />
    ) : null;
  const refused = outcome?.kind === "error";

  if (!onCodeStep) {
    return (
      <form
        className={cn("space-y-4", className)}
        onSubmit={(event) => void sendCode(event)}
        aria-busy={busy}
        data-step="email"
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
            // Signing in is what the page is for. A form placed elsewhere passes autoFocus={false}.
            autoFocus={autoFocus}
            required
            defaultValue={login.email !== "" ? login.email : defaultEmail}
            disabled={disabled || busy}
            aria-invalid={refused || undefined}
            aria-describedby={outcome !== null ? messageId : undefined}
          />
        </div>
        {message}
        <PendingButton
          type="submit"
          className="w-full"
          disabled={disabled}
          pending={login.status === "sending"}
          pendingLabel="Sending the code…"
        >
          Send the code
        </PendingButton>
      </form>
    );
  }

  const expires = login.expiresIn !== null ? ` It expires in ${minutes(login.expiresIn)}.` : "";
  return (
    <form
      className={cn("space-y-4", className)}
      onSubmit={(event) => void verifyCode(event)}
      aria-busy={busy}
      data-step="code"
    >
      {title !== null ? <h2 className="text-lg font-semibold">{title}</h2> : null}
      <p className="text-sm text-muted-foreground">
        Check <span className="font-medium text-foreground">{login.email}</span> for a{" "}
        {login.length}-digit code.{expires}
      </p>
      <div className={FIELD_GAP}>
        <Label htmlFor={`${id}-code`}>Code</Label>
        <Input
          ref={codeRef}
          id={`${id}-code`}
          name="code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern={`[0-9]{${login.length}}`}
          maxLength={login.length}
          minLength={login.length}
          required
          spellCheck={false}
          className="font-mono tracking-wide"
          disabled={disabled || busy}
          aria-invalid={refused || undefined}
          aria-describedby={outcome !== null ? messageId : undefined}
        />
      </div>
      {message}
      <PendingButton
        type="submit"
        className="w-full"
        disabled={disabled || outcome?.kind === "approval"}
        pending={login.status === "verifying"}
        pendingLabel="Signing in…"
      >
        Sign in
      </PendingButton>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Button
          variant="link"
          size="sm"
          className="px-0"
          disabled={disabled || busy || login.cooldown > 0}
          onClick={() => void resend()}
        >
          Send a new code
        </Button>
        <Button variant="link" size="sm" className="px-0" disabled={busy} onClick={back}>
          Use another email
        </Button>
      </div>
      {login.cooldown > 0 ? (
        <p className="text-xs text-muted-foreground" data-cooldown={login.cooldown}>
          You can ask for a new code in {login.cooldown}{" "}
          {login.cooldown === 1 ? "second" : "seconds"}.
        </p>
      ) : null}
    </form>
  );
}
