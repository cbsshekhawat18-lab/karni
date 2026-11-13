/**
 * Experimental. DemoNotice: the demo accounts above a sign-in form, with what
 * each one can do. It reads `GET /demo/` (`useDemo`) and renders nothing when
 * the server is not a demo, while it loads, or when the request fails, so the
 * same app runs as a demo and as the real thing without a flag.
 *
 * `DemoSignInPrompt` is the `AuthGuard` `Anonymous` slot with the notice above
 * Karni's own sign-in prompt:
 *
 *   <AuthGuard explain slots={{ Anonymous: DemoSignInPrompt }}>...</AuthGuard>
 *
 * Replace the body with the `Notice` prop (`createDemoSignInPrompt({ Notice })`
 * for the sign-in slot), or render `useDemo()`'s data yourself. `onPick` is
 * called with the account a visitor chooses, so an app can fill its own form.
 */
import * as React from "react";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { defaultAuthGuardSlots, type AuthGuardAnonymousProps } from "../auth/AuthGuard";
import { useDemo, type DemoAccount, type DemoInfo } from "./useDemo";

registerComponentRole("demo-notice", "DemoNotice");

/** Experimental. What the `Notice` slot receives: the server's description of the demo. */
export interface DemoNoticeBodyProps {
  demo: DemoInfo;
  /** Called with the account a visitor picks; the "Use" buttons show only when it is set. */
  onPick?: (account: DemoAccount) => void;
  className?: string;
}

/** Experimental. The default body: a sentence, then one row per account. */
export function DemoNoticeBody({
  demo,
  onPick,
  className,
}: DemoNoticeBodyProps): React.ReactElement {
  const headingId = React.useId();
  return (
    <section
      data-demo-notice=""
      aria-labelledby={headingId}
      className={cn(
        "w-full space-y-3 rounded-lg border border-border bg-card p-4 text-sm text-card-foreground",
        className,
      )}
    >
      <h2 id={headingId} className="font-semibold">
        This is a demo
      </h2>
      <p className="text-muted-foreground">
        Sign in with one of these accounts. Only they can change data, and the data goes back to the
        start every {demo.reset_hours} hours.
        {demo.admin_url !== null ? (
          <>
            {" "}
            The{" "}
            <a className="underline" href={demo.admin_url}>
              admin
            </a>{" "}
            takes the same logins.
          </>
        ) : null}
      </p>
      <ul className="space-y-2">
        {demo.accounts.map((account) => (
          <li key={account.login} data-demo-account={account.login} className="space-y-0.5">
            <div className="font-medium">{account.label}</div>
            <div>
              <code>{account.login}</code>, password <code>{account.password}</code>
              {onPick !== undefined ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => onPick(account)}
                    aria-label={`Use the ${account.label} account`}
                  >
                    Use
                  </button>
                </>
              ) : null}
            </div>
            {account.can !== "" ? <div className="text-muted-foreground">{account.can}</div> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Experimental. DemoNotice's props. */
export interface DemoNoticeProps {
  /** Called with the account a visitor picks (shows a "Use" button on each). */
  onPick?: (account: DemoAccount) => void;
  /** Replace the body. It gets the server's description of the demo. */
  Notice?: React.ComponentType<DemoNoticeBodyProps>;
  className?: string;
}

/** Experimental. The demo accounts, or nothing when the server is not a demo. */
export function DemoNotice({
  onPick,
  Notice = DemoNoticeBody,
  className,
}: DemoNoticeProps): React.ReactElement | null {
  const { data } = useDemo();
  if (data === undefined || data.accounts.length === 0) return null;
  return <Notice demo={data} onPick={onPick} className={className} />;
}

/** Experimental. An `Anonymous` slot for AuthGuard: DemoNotice above Karni's sign-in prompt. */
export function createDemoSignInPrompt(
  props: DemoNoticeProps = {},
): React.ComponentType<AuthGuardAnonymousProps> {
  const KarniSignInPrompt = defaultAuthGuardSlots.Anonymous;
  return function DemoSignInPrompt(slot: AuthGuardAnonymousProps): React.ReactElement {
    return (
      <div className="mx-auto w-full max-w-96 space-y-4">
        <DemoNotice {...props} />
        <KarniSignInPrompt {...slot} />
      </div>
    );
  };
}

/** Experimental. DemoNotice above Karni's sign-in prompt, as AuthGuard's `Anonymous` slot. */
export const DemoSignInPrompt: React.ComponentType<AuthGuardAnonymousProps> =
  createDemoSignInPrompt();
