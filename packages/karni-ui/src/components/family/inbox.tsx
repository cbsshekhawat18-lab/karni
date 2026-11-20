/**
 * Experimental. The signed-in person's inbox (karni.notify, `/inbox/`):
 *
 * - `<InboxBell>`: a button with the unread count (`GET /inbox/unread/`,
 *   read again every minute and when the window gets focus), for the layout.
 * - `<InboxPage>`: `/inbox`, the notifications newest first, a page at a
 *   time, with an "Unread only" filter, mark one read (opening it does too),
 *   mark it unread again, and mark all read.
 * - `<EmailChoices>`: the person's own switches, per kind and channel
 *   (`GET/PATCH /inbox/choices/`), for the account page.
 *
 * Every request answers the signed-in person about their own notifications
 * only. A project without `karni.notify` answers 404: the bell then hides
 * itself and the page says the inbox is off.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useAuth } from "../../auth/provider";
import { usePageMeta } from "../../hooks/usePageMeta";
import { cn } from "../../lib/cn";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { ErrorState } from "../../states/ErrorState";
import { PendingButton } from "../../states/PendingButton";
import { EmptyState } from "../empty-state/empty-state";
import { Button } from "../primitives/button";
import { Skeleton } from "../primitives/skeleton";
import { Switch } from "../primitives/switch";
import { useToast } from "../toast/use-toast";

/** Experimental. One notification. */
export interface InboxNotification {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
}

/** Experimental. One page of `GET /inbox/`. */
export interface InboxPageBody {
  count: number;
  unread: number;
  next: number | null;
  results: InboxNotification[];
}

/** Experimental. A kind the person may switch, as `GET /inbox/choices/` answers it. */
export interface InboxChoice {
  kind: string;
  title: string;
  describe: string;
  audience: string;
  marketing: boolean;
  channels: string[];
  email: boolean;
  inbox: boolean;
}

const ROOT = ["karni", "$inbox"] as const;

function useUser(): string | null {
  const { status, user } = useAuth();
  return status === "authenticated" && user ? String(user.id) : null;
}

/** Experimental. How many notifications the signed-in person has not read (null: unknown or off). */
export function useInboxUnread(pollMs = 60_000): number | null {
  const client = useKarniClient();
  const user = useUser();
  const query = useQuery({
    queryKey: [...ROOT, user, "unread"],
    enabled: user !== null,
    retry: false,
    refetchInterval: pollMs > 0 ? pollMs : false,
    refetchOnWindowFocus: true,
    queryFn: ({ signal }) => client.request<{ count: number }>("/inbox/unread/", { signal }),
  });
  return query.data?.count ?? null;
}

function BellIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

export interface InboxBellProps {
  /** Opens the inbox (default: a page load of `href`). */
  navigate?: (to: string) => void;
  /** The inbox page (default "/inbox"). */
  href?: string;
  /** How often the count is read again, in milliseconds (0: never). Default a minute. */
  pollMs?: number;
  className?: string;
}

/** Experimental. The bell in the layout: the unread count, a link to the inbox. Hidden when off. */
export function InboxBell({
  navigate,
  href = "/inbox",
  pollMs = 60_000,
  className,
}: InboxBellProps): React.ReactElement | null {
  const count = useInboxUnread(pollMs);
  if (count === null) return null;
  const label = count === 0 ? "Inbox, nothing unread" : `Inbox, ${count} unread`;
  return (
    <a
      href={href}
      aria-label={label}
      title={label}
      className={cn(
        "relative inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      onClick={(event) => {
        if (navigate === undefined) return;
        event.preventDefault();
        navigate(href);
      }}
    >
      <BellIcon className="h-5 w-5" />
      {count > 0 ? (
        <span
          aria-hidden="true"
          className="absolute -right-0.5 -top-0.5 min-w-5 rounded-full bg-primary px-1 py-0.5 text-center text-xs font-semibold text-primary-foreground"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </a>
  );
}

function shownAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export interface InboxPageProps {
  title?: string;
  siteName?: string;
  /** Opens a notification's link inside the app. Default: a page load. */
  navigate?: (to: string) => void;
  /** Notifications per page. Default 25. */
  pageSize?: number;
}

/** Experimental. `/inbox`: the person's notifications, with the unread filter and the read marks. */
export function InboxPage({
  title = "Inbox",
  siteName,
  navigate,
  pageSize = 25,
}: InboxPageProps): React.ReactElement {
  usePageMeta({ title, siteName });
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const user = useUser();
  const { error: toastError } = useToast();
  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const unreadId = React.useId();
  const list = useQuery({
    queryKey: [...ROOT, user, "list", unreadOnly, page, pageSize],
    enabled: user !== null,
    retry: false,
    queryFn: ({ signal }) =>
      client.request<InboxPageBody>("/inbox/", {
        signal,
        query: {
          page: String(page),
          limit: String(pageSize),
          ...(unreadOnly ? { unread: "true" } : {}),
        },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...ROOT, user] });
  const mark = useMutation({
    mutationFn: ({ id, read }: { id: number; read: boolean }) =>
      client.request<InboxNotification>(`/inbox/${id}/${read ? "read" : "unread"}/`, {
        method: "POST",
      }),
    onSuccess: () => void refresh(),
    onError: () => toastError("That did not change", { description: "Try again." }),
  });
  const all = useMutation({
    mutationFn: () => client.request<{ updated: number }>("/inbox/read-all/", { method: "POST" }),
    onSuccess: () => void refresh(),
    onError: () => toastError("That did not change", { description: "Try again." }),
  });
  function open(item: InboxNotification): void {
    if (!item.read) mark.mutate({ id: item.id, read: true });
    if (item.link === "") return;
    if (navigate !== undefined && item.link.startsWith("/")) navigate(item.link);
    else window.location.assign(item.link);
  }
  let body: React.ReactNode;
  if (list.isPending) {
    body = (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  } else if (list.error instanceof KarniApiError && list.error.status === 404) {
    body = <EmptyState title="The inbox is off in this project" />;
  } else if (list.isError) {
    body = (
      <ErrorState
        error={list.error}
        context={{ action: "view", resource: "inbox" }}
        onRetry={() => void list.refetch()}
      />
    );
  } else if (list.data.results.length === 0) {
    body = (
      <EmptyState
        title={unreadOnly ? "Nothing unread" : "Nothing in your inbox yet"}
        description={
          unreadOnly
            ? "Everything here is read."
            : "Orders, bookings and messages for you land here as they happen."
        }
      />
    );
  } else {
    const data = list.data;
    body = (
      <div className="space-y-4">
        <ul className="rounded-lg border border-border [&>*+*]:border-t [&>*+*]:border-border">
          {data.results.map((item) => (
            <li
              key={item.id}
              className={cn("flex flex-wrap items-start gap-3 p-4", !item.read && "bg-muted")}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "mt-2 h-2 w-2 shrink-0 rounded-full",
                  item.read ? "bg-transparent" : "bg-primary",
                )}
              />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-medium">
                  {item.link !== "" ? (
                    <a
                      href={item.link}
                      className="underline-offset-4 hover:underline"
                      onClick={(event) => {
                        event.preventDefault();
                        open(item);
                      }}
                    >
                      {item.title}
                    </a>
                  ) : (
                    item.title
                  )}
                  {item.read ? null : <span className="sr-only"> (unread)</span>}
                </p>
                {item.body !== "" ? (
                  <p className="line-clamp-3 whitespace-pre-line text-sm text-muted-foreground">
                    {item.body}
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  <time dateTime={item.created_at}>{shownAt(item.created_at)}</time>
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`${item.read ? "Mark unread" : "Mark read"}: ${item.title}`}
                disabled={mark.isPending}
                onClick={() => mark.mutate({ id: item.id, read: !item.read })}
              >
                {item.read ? "Mark unread" : "Mark read"}
              </Button>
            </li>
          ))}
        </ul>
        <nav aria-label="Inbox pages" className="flex items-center gap-3">
          <Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Newer
          </Button>
          <span className="text-sm text-muted-foreground">Page {page}</span>
          <Button variant="outline" disabled={data.next === null} onClick={() => setPage(page + 1)}>
            Older
          </Button>
        </nav>
      </div>
    );
  }
  const unread = list.data?.unread ?? 0;
  return (
    <div className="min-w-0 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">{title}</h1>
          {list.data !== undefined ? (
            <p className="text-sm text-muted-foreground" role="status">
              {unread === 0 ? "Nothing unread" : `${unread} unread`}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label htmlFor={unreadId} className="flex items-center gap-2 text-sm">
            <Switch
              id={unreadId}
              checked={unreadOnly}
              onCheckedChange={(checked) => {
                setUnreadOnly(checked);
                setPage(1);
              }}
            />
            Unread only
          </label>
          <PendingButton
            variant="outline"
            pending={all.isPending}
            disabled={unread === 0}
            onClick={() => all.mutate()}
          >
            Mark all read
          </PendingButton>
        </div>
      </header>
      {body}
    </div>
  );
}

function ChoiceRow({ choice }: { choice: InboxChoice }): React.ReactElement {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const user = useUser();
  const { error } = useToast();
  const id = React.useId();
  const change = useMutation({
    mutationFn: (body: { email?: boolean; inbox?: boolean }) =>
      client.request<InboxChoice>(`/inbox/choices/${encodeURIComponent(choice.kind)}/`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...ROOT, user, "choices"] }),
    onError: () => error("Your choice was not saved", { description: "Try again." }),
  });
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 space-y-1">
        <p id={`${id}-title`} className="font-medium">
          {choice.title}
        </p>
        {choice.describe !== "" ? (
          <p className="text-sm text-muted-foreground">{choice.describe}</p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        {(["email", "inbox"] as const)
          .filter((channel) => choice.channels.includes(channel))
          .map((channel) => (
            <label key={channel} className="flex items-center gap-2 text-sm">
              <Switch
                aria-label={`${channel === "email" ? "Email" : "Inbox"}: ${choice.title}`}
                checked={choice[channel]}
                disabled={change.isPending}
                onCheckedChange={(checked) => change.mutate({ [channel]: checked })}
              />
              <span aria-hidden="true">{channel === "email" ? "Email" : "Inbox"}</span>
            </label>
          ))}
      </div>
    </li>
  );
}

/** Experimental. The person's own switches: which messages reach them by email and in the inbox. */
export function EmailChoices(): React.ReactElement {
  const client = useKarniClient();
  const user = useUser();
  const choices = useQuery({
    queryKey: [...ROOT, user, "choices"],
    enabled: user !== null,
    retry: false,
    queryFn: ({ signal }) => client.request<InboxChoice[]>("/inbox/choices/", { signal }),
  });
  if (choices.isPending) return <Skeleton className="h-16 w-full" />;
  if (choices.isError) {
    return (
      <ErrorState
        variant="inline"
        error={choices.error}
        context={{ action: "view", resource: "choices" }}
        onRetry={() => void choices.refetch()}
      />
    );
  }
  if (choices.data.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to choose here yet.</p>;
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        Choose how each message reaches you. A message nobody may switch off, such as a sign-in
        code, is not listed.
      </p>
      <ul className="[&>*+*]:border-t [&>*+*]:border-border">
        {choices.data.map((choice) => (
          <ChoiceRow key={choice.kind} choice={choice} />
        ))}
      </ul>
    </div>
  );
}
