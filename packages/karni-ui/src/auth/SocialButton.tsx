/**
 * Experimental. SocialButton: "Continue with Google" (or Microsoft, Apple, ...) for Karni.
 *
 * `getIdToken` is the app's own call into the provider's SDK (Google Identity
 * Services, MSAL, Sign in with Apple JS) and resolves with the ID token, and
 * the nonce when the app made one. Karni bundles no provider SDK. The button
 * posts the token through `useSocialLogin`, shows progress, says in plain
 * words why a sign-in was refused, and says so when the new account waits
 * for an administrator. On success it calls `onSuccess(user)`. The 2FA step
 * goes to `on2FA`, exactly as LoginForm's does.
 */
import * as React from "react";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import type { ButtonVariantProps } from "../components/primitives/button";
import { AlertIcon, OfflineIcon } from "../components/primitives/icons";
import { KarniApiError } from "../schema/client";
import { describeError, type KarniErrorDescription } from "../states/describe-error";
import type { ErrorSlotProps } from "../states/ErrorState";
import { PendingButton } from "../states/PendingButton";
import type { KarniUser, SocialSignInOptions } from "./types";
import { useSocialLogin } from "./useSocialLogin";

registerComponentRole("social-sign-in", "SocialButton");

/** Experimental. What `getIdToken` resolves with: the token, or the token with its nonce and name. */
export interface SocialIdToken extends SocialSignInOptions {
  idToken: string;
}

/** Experimental. What the `Error` slot receives: the failure, already worded for this provider. */
export interface SocialButtonErrorProps extends ErrorSlotProps {
  /** Put this id on the message's root: the button's `aria-describedby` points at it. */
  id: string;
  described: KarniErrorDescription;
}

/** Experimental. What the `Approval` slot receives when the new account waits for an administrator. */
export interface SocialButtonApprovalProps {
  /** Put this id on the message's root: the button's `aria-describedby` points at it. */
  id: string;
  /** The provider's display name ("Google"). */
  providerName: string;
  /** The server's explanation. */
  detail: string;
}

/** Experimental. The replaceable parts of SocialButton. `defaultSocialButtonSlots` holds Karni's own. */
export interface SocialButtonSlots {
  Error: React.ComponentType<SocialButtonErrorProps>;
  Approval: React.ComponentType<SocialButtonApprovalProps>;
}

export interface SocialButtonProps {
  /** The provider's name in the backend's `KARNI_SOCIAL_TOKEN_PROVIDERS`: "google", "microsoft", "apple", ... */
  provider: string;
  /**
   * The app's call into the provider's SDK. Resolve with the ID token (a
   * string, or `{ idToken, nonce?, name? }`), or with `null` when the user
   * closed the provider's window (nothing is shown).
   */
  getIdToken: () => Promise<SocialIdToken | string | null>;
  /** The button's text. Default "Continue with <Provider>". */
  label?: React.ReactNode;
  /** The provider's mark, drawn before the label. Karni ships none (brand rules vary). */
  icon?: React.ReactNode;
  /** The provider's name in messages. Default: Google, Microsoft or Apple, else the name capitalised. */
  providerName?: string;
  /** Called with the signed-in user. Navigate from here. */
  onSuccess?: (user: KarniUser) => void;
  /** Called when the account needs a second factor (the token completes it), as in LoginForm. */
  on2FA?: (ephemeralToken: string) => void;
  /** Called when a new account was created and waits for an administrator. */
  onAwaitingApproval?: (detail: string) => void;
  /** Button style. Default "outline". */
  variant?: ButtonVariantProps["variant"];
  disabled?: boolean;
  /** Replace parts of the button: Error, Approval. */
  slots?: Partial<SocialButtonSlots>;
  className?: string;
}

const PROVIDER_NAMES: Record<string, string> = {
  google: "Google",
  microsoft: "Microsoft",
  apple: "Apple",
};

function displayName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** Thrown inside the button when the account needs a code and the app has no `on2FA`. */
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

function refused(
  title: string,
  description: string,
  status: number,
  kind: KarniErrorDescription["kind"] = "unauthenticated",
  retryable = false,
): KarniErrorDescription {
  return { kind, title, description, retryable, status };
}

/**
 * Experimental. A SocialButton failure in plain words, from the Karni code of the refusal
 * (E215 to E227), never a status code. Exported for a project's own button.
 */
export function describeSocialError(error: unknown, providerName: string): KarniErrorDescription {
  if (error instanceof TwoFactorUnavailable) {
    return refused(
      "This account needs a two-factor code",
      "The app has not enabled that step. Ask the site's administrator.",
      401,
    );
  }
  if (!(error instanceof KarniApiError)) return describeError(error, { action: "sign in" });
  const status = error.status;
  switch (karniCode(error)) {
    case "E218":
      return refused("The sign-in took too long", "Try again.", status, "unauthenticated", true);
    case "E215":
    case "E216":
    case "E217":
    case "E220":
      return refused(
        `Sign-in with ${providerName} did not work`,
        "Try again. If it keeps failing, the app is not set up for this account.",
        status,
        "unauthenticated",
        true,
      );
    case "E219":
      return status === 503
        ? refused(
            `${providerName} cannot be reached right now`,
            "Wait a minute, then try again.",
            status,
            "server",
            true,
          )
        : refused(
            `Sign-in with ${providerName} did not work`,
            "Try again in a minute.",
            status,
            "unauthenticated",
            true,
          );
    case "E221":
      return refused(
        `${providerName} did not share your email address`,
        "Allow access to your email address, then try again.",
        status,
        "validation",
      );
    case "E222":
      return refused(
        `${providerName} has not verified your email address`,
        "Sign in another way, or verify the address with the provider first.",
        status,
        "validation",
      );
    case "E223":
      return refused(
        "No account is set up for you here",
        "Ask the site's administrator for an account, then sign in again.",
        status,
        "forbidden",
      );
    case "E225":
      return refused(
        `Sign-in with ${providerName} is not available here`,
        "Sign in another way.",
        status,
        "not-found",
      );
    case "E226":
      return refused(
        "This account is not active",
        "Ask the site's administrator to activate it.",
        status,
        "forbidden",
      );
    case "E227":
      return refused(
        "An account with this email address already exists",
        "Sign in with your password.",
        status,
        "conflict",
      );
    default:
      break;
  }
  if (status === 429) {
    return refused(
      "Too many sign-in attempts",
      "Wait a few minutes, then try again.",
      status,
      "rate-limited",
      true,
    );
  }
  return describeError(error, { action: "sign in" });
}

function DefaultSocialError({ id, described }: SocialButtonErrorProps): React.ReactElement {
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
      </div>
    </div>
  );
}

function DefaultSocialApproval({ id }: SocialButtonApprovalProps): React.ReactElement {
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
export const defaultSocialButtonSlots: SocialButtonSlots = {
  Error: DefaultSocialError,
  Approval: DefaultSocialApproval,
};

/**
 * Experimental. A "Continue with <provider>" button that signs in with the provider's ID token.
 *
 * Accessible: a real button whose name is the label, `aria-busy` and a
 * spoken "Signing in with Google…" while pending, and the outcome (a refusal
 * as an alert, approval pending as a status) linked by `aria-describedby`.
 * Escape hatch: `slots`, or `useSocialLogin` for a button of your own.
 */
export function SocialButton({
  provider,
  getIdToken,
  label,
  icon,
  providerName,
  onSuccess,
  on2FA,
  onAwaitingApproval,
  variant = "outline",
  disabled = false,
  slots,
  className,
}: SocialButtonProps): React.ReactElement {
  const Slots: SocialButtonSlots = { ...defaultSocialButtonSlots, ...slots };
  const name = providerName ?? displayName(provider);
  const { signIn } = useSocialLogin(provider);
  const id = React.useId();
  const messageId = `${id}-message`;
  const [busy, setBusy] = React.useState(false);
  const [outcome, setOutcome] = React.useState<
    { kind: "error"; error: unknown; attempt: number } | { kind: "approval"; detail: string } | null
  >(null);
  const attempts = React.useRef(0);

  async function start(): Promise<void> {
    attempts.current += 1;
    const attempt = attempts.current;
    setBusy(true);
    setOutcome(null);
    try {
      const token = await getIdToken();
      if (token === null) return;
      const { idToken, ...options } = typeof token === "string" ? { idToken: token } : token;
      const result = await signIn(idToken, options);
      if ("ok" in result) {
        onSuccess?.(result.user);
      } else if ("requires2fa" in result) {
        if (on2FA !== undefined) on2FA(result.ephemeralToken);
        else setOutcome({ kind: "error", error: new TwoFactorUnavailable(), attempt });
      } else {
        setOutcome({ kind: "approval", detail: result.detail });
        onAwaitingApproval?.(result.detail);
      }
    } catch (error) {
      setOutcome({ kind: "error", error, attempt });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("space-y-2", className)} data-provider={provider}>
      <PendingButton
        variant={variant}
        className="w-full"
        disabled={disabled}
        pending={busy}
        pendingLabel={`Signing in with ${name}…`}
        aria-describedby={outcome !== null ? messageId : undefined}
        onClick={() => void start()}
      >
        {icon !== undefined ? (
          <span aria-hidden="true" className="inline-flex h-4 w-4 items-center justify-center">
            {icon}
          </span>
        ) : null}
        {label ?? `Continue with ${name}`}
      </PendingButton>
      {outcome?.kind === "error" ? (
        // Keyed by attempt: the same message after another failed attempt is announced again.
        <React.Fragment key={outcome.attempt}>
          <Slots.Error
            id={messageId}
            error={outcome.error}
            context={{ action: "sign in" }}
            described={describeSocialError(outcome.error, name)}
          />
        </React.Fragment>
      ) : null}
      {outcome?.kind === "approval" ? (
        <Slots.Approval id={messageId} providerName={name} detail={outcome.detail} />
      ) : null}
    </div>
  );
}
