/**
 * Experimental. TermsGate: the app behind it renders only once the signed-in
 * user has accepted the current terms.
 *
 * While the server sets `KARNI_TERMS` and the user has not accepted its
 * version, the API refuses them with a 403 (`E245`). `useAuth()` knows it
 * from `/me/` and from that 403 on any request (`termsRequired`), so terms
 * bumped mid-session are caught as well. TermsGate then renders the terms
 * (a link to their url, or an embedded frame with `embed`) and an accept
 * button in place of its children. Accepting calls `acceptTerms`, and the
 * children render.
 *
 * Wrap the part of the app that calls the API, inside AuthProvider:
 *
 *   <AuthProvider>
 *     <TermsGate>
 *       <RouterProvider router={router} />
 *     </TermsGate>
 *   </AuthProvider>
 */
import * as React from "react";
import { AlertIcon, OfflineIcon } from "../components/primitives/icons";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { KarniApiError } from "../schema/client";
import { describeError, type KarniErrorDescription } from "../states/describe-error";
import { PendingButton } from "../states/PendingButton";
import { useAuth } from "./provider";
import type { AuthTerms, TermsClientInfo } from "./types";

registerComponentRole("terms-gate", "TermsGate");

/** Experimental. What the `Panel` slot receives: the terms, and the way to accept them. */
export interface TermsGatePanelProps {
  /** The terms to accept: `version`, `url`. */
  terms: AuthTerms;
  /** Accept them. The gate opens once the server records it. */
  accept: () => void;
  /** True while the acceptance is being recorded. */
  accepting: boolean;
  /** The last failed attempt in plain words, or null. */
  error: KarniErrorDescription | null;
  /** Show the terms in a frame instead of a link. */
  embed: boolean;
  title: React.ReactNode;
  description: React.ReactNode;
  acceptLabel: React.ReactNode;
  /**
   * True when the gate is the whole screen: the panel is the page's `<main>`
   * and its heading is the `<h1>`. False inside a page that has its own.
   */
  page: boolean;
  className?: string;
}

/** Experimental. The replaceable parts of TermsGate. `defaultTermsGateSlots` holds Karni's own. */
export interface TermsGateSlots {
  /** The terms and the accept button, rendered in place of the children. */
  Panel: React.ComponentType<TermsGatePanelProps>;
}

export interface TermsGateProps {
  /** What renders once the terms are accepted, or when the server asks for none. */
  children?: React.ReactNode;
  /**
   * Show the terms in an embedded frame instead of a link. The page at the
   * terms url must allow being framed (Karni's own pages send
   * `X-Frame-Options: DENY` unless the project changes it). Default false.
   */
  embed?: boolean;
  /**
   * What the app sends about itself with the acceptance (a device, an app
   * version), stored with it. A function is called when the user accepts.
   */
  client?: TermsClientInfo | (() => TermsClientInfo);
  /** Called with the accepted terms, before the children render. */
  onAccepted?: (terms: AuthTerms) => void;
  /** Rendered while the auth status is still "loading". Default: nothing. */
  loading?: React.ReactNode;
  /** The panel's heading. Default "Terms of use". */
  title?: React.ReactNode;
  /** The text under the heading. Default: which version to read and accept. */
  description?: React.ReactNode;
  /** The button's label. Default "Accept and continue". */
  acceptLabel?: React.ReactNode;
  /**
   * The gate replaces the whole app, so by default its panel is the page's
   * `<main>` with an `<h1>` heading. Pass false when the gate sits inside a
   * page that already has both (the heading is then an `<h2>`). Default true.
   */
  page?: boolean;
  /** Replace the panel: `Panel`. */
  slots?: Partial<TermsGateSlots>;
  /** Merged onto the default panel's root. */
  className?: string;
}

function karniCode(error: unknown): string | undefined {
  if (!(error instanceof KarniApiError)) return undefined;
  const data = error.data;
  if (typeof data !== "object" || data === null) return undefined;
  const code = (data as Record<string, unknown>)["code"];
  return typeof code === "string" ? code : undefined;
}

/** A failed acceptance in plain words: the terms changed again (E246), or describeError's. */
function describeTermsError(error: unknown): KarniErrorDescription {
  if (karniCode(error) === "E246") {
    return {
      kind: "conflict",
      title: "The terms have changed",
      description: "Read the new version, then accept it.",
      retryable: true,
      status: 400,
    };
  }
  return describeError(error, { action: "accept", resource: "the terms" });
}

/** Thrown inside the gate when the context cannot accept terms (a hand-built context value). */
class AcceptUnavailable extends Error {
  constructor() {
    super("This app cannot accept terms: AuthProvider is missing acceptTerms.");
    this.name = "AcceptUnavailable";
  }
}

function DefaultTermsPanel({
  terms,
  accept,
  accepting,
  error,
  embed,
  title,
  description,
  acceptLabel,
  page,
  className,
}: TermsGatePanelProps): React.ReactElement {
  const id = React.useId();
  const headingId = `${id}-heading`;
  const errorId = `${id}-error`;
  const Icon = error?.kind === "offline" || error?.kind === "network" ? OfflineIcon : AlertIcon;
  const link = (
    <a
      href={terms.url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-sm font-medium text-foreground underline underline-offset-4 hover:text-muted-foreground"
    >
      {embed ? "Open the terms in a new tab" : "Read the terms"}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
  const Heading = page ? "h1" : "h2";
  const panel = (
    <section
      aria-labelledby={headingId}
      data-terms-version={terms.version}
      className={cn(
        "mx-auto w-full max-w-128 space-y-4 rounded-lg border border-border bg-card p-6 text-card-foreground",
        className,
      )}
    >
      <div className="space-y-1">
        <Heading id={headingId} className="text-lg font-semibold">
          {title}
        </Heading>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {embed ? (
        <iframe
          src={terms.url}
          title={`Terms, version ${terms.version}`}
          className="h-96 w-full rounded-md border border-border bg-background"
        />
      ) : null}
      <p>{link}</p>
      {error !== null ? (
        <div
          id={errorId}
          role="alert"
          data-error-kind={error.kind}
          className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
        >
          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div className="space-y-1">
            <p className="font-medium text-foreground">{error.title}</p>
            <p className="text-muted-foreground">{error.description}</p>
          </div>
        </div>
      ) : null}
      <PendingButton
        className="w-full sm:w-auto"
        pending={accepting}
        pendingLabel="Accepting the terms…"
        aria-describedby={error !== null ? errorId : undefined}
        onClick={accept}
      >
        {acceptLabel}
      </PendingButton>
    </section>
  );
  return page ? <main className="px-4 py-10">{panel}</main> : panel;
}

/** Experimental. Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultTermsGateSlots: TermsGateSlots = {
  Panel: DefaultTermsPanel,
};

/**
 * Experimental. Renders its children once the signed-in user has accepted the
 * current terms, and the terms with an accept button until then.
 *
 * Accessible: the panel is a labelled region, the terms link says it opens a
 * new tab, the frame has a title, a failed acceptance is an alert the button
 * points at, and the button is busy while it works. Escape hatch: `slots`, or
 * `useAuth()`'s `termsRequired`, `terms` and `acceptTerms` for a gate of your own.
 */
export function TermsGate({
  children,
  embed = false,
  client,
  onAccepted,
  loading = null,
  title = "Terms of use",
  description,
  acceptLabel = "Accept and continue",
  page = true,
  slots,
  className,
}: TermsGateProps): React.ReactElement {
  const Slots: TermsGateSlots = { ...defaultTermsGateSlots, ...slots };
  const { status, terms, termsRequired, acceptTerms } = useAuth();
  const [accepting, setAccepting] = React.useState(false);
  const [failure, setFailure] = React.useState<{ error: unknown } | null>(null);

  if (status === "loading") return <>{loading}</>;
  // Only a signed-in user is gated: a visitor sees the app, whose own AuthGuard asks them to sign in.
  if (
    status !== "authenticated" ||
    termsRequired !== true ||
    terms === null ||
    terms === undefined
  ) {
    return <>{children}</>;
  }

  async function accept(): Promise<void> {
    setAccepting(true);
    // Cleared first, so a failure after a retry is a new alert and is announced again.
    setFailure(null);
    try {
      if (acceptTerms === undefined) throw new AcceptUnavailable();
      const info = typeof client === "function" ? client() : client;
      const accepted = await acceptTerms(info);
      onAccepted?.(accepted);
    } catch (error) {
      setFailure({ error });
    } finally {
      setAccepting(false);
    }
  }

  return (
    <Slots.Panel
      terms={terms}
      accept={() => void accept()}
      accepting={accepting}
      error={failure !== null ? describeTermsError(failure.error) : null}
      embed={embed}
      title={title}
      description={
        description ?? (
          <>
            Read the terms (version{" "}
            <span className="font-medium text-foreground">{terms.version}</span>) and accept them to
            continue.
          </>
        )
      }
      acceptLabel={acceptLabel}
      page={page}
      {...(className !== undefined ? { className } : {})}
    />
  );
}
