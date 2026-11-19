/**
 * Experimental. `<Timeline>`: one stream of what happened to a person or a
 * record, in every installed part (karni.timeline, `GET /timeline/`).
 *
 *   <Timeline person={personId} history={{ resource: "people", id: personId }} />
 *   <Timeline subject="karni_commerce.order:6c1d..." />
 *
 * Newest first, a page at a time ("Show more" asks the next cursor). The
 * filter narrows it to one kind (`?kind=`): the kinds seen so far and the
 * ones a part registered (`registerTimelineKind`). Each entry links to the
 * records it is about through `hrefFor` (default: the record link a part
 * registered, `registerRecordLink`). The server shows an entry only to who
 * may read every record it is linked to, so the component filters nothing.
 *
 * With `history`, a "Changes" tab shows the record's field-level change
 * history next to it (the timeline never copies it), when the viewer may
 * read it: a 403 or 404 on the history hides the tab.
 *
 * Escape hatch: `registerTimelineKind(kind, { render })` draws one kind's
 * body, `useTimeline(params)` is the data alone.
 */
import { useInfiniteQuery, type UseInfiniteQueryResult } from "@tanstack/react-query";
import * as React from "react";
import { useChangeHistory } from "../../hooks/useChangeHistory";
import { cn } from "../../lib/cn";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { ErrorState } from "../../states/ErrorState";
import { PendingButton } from "../../states/PendingButton";
import { EmptyState } from "../empty-state/empty-state";
import { Label } from "../primitives/label";
import { Skeleton } from "../primitives/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";
import { ChangeHistory } from "../resource/history/ChangeHistory";
import { recordHref } from "../resource/record-links";
import { timelineKind, timelineKindLabel, type TimelineEntry } from "./registry";

export type { TimelineEntry } from "./registry";

/** Experimental. Whose timeline: exactly one of them. */
export interface TimelineParams {
  /** A person's id. */
  person?: string;
  /** An organisation's id. */
  organisation?: string;
  /** A record: `app_label.model:id` (`karni_commerce.order:6c1d...`). */
  subject?: string;
  /** Keep these kinds only. */
  kinds?: readonly string[];
  /** Entries per page (the server caps it at KARNI_TIMELINE_MAX_PAGE_SIZE). */
  limit?: number;
}

interface TimelinePage {
  results: TimelineEntry[];
  next: string | null;
}

/** Experimental. The cache key of one timeline. */
export function timelineKey(params: TimelineParams): readonly unknown[] {
  return [
    "karni",
    "$timeline",
    params.person ?? null,
    params.organisation ?? null,
    params.subject ?? null,
    [...(params.kinds ?? [])].sort().join(","),
    params.limit ?? null,
  ];
}

/** Experimental. One timeline, a page at a time (`GET /timeline/`, cursor paging). */
export function useTimeline(params: TimelineParams): UseInfiniteQueryResult<{
  pages: TimelinePage[];
  pageParams: Array<string | null>;
}> {
  const client = useKarniClient();
  return useInfiniteQuery({
    queryKey: timelineKey(params),
    initialPageParam: null as string | null,
    getNextPageParam: (last: TimelinePage) => last.next,
    queryFn: ({ pageParam, signal }) => {
      const query: Record<string, string> = {};
      if (params.person !== undefined) query["person"] = params.person;
      if (params.organisation !== undefined) query["organisation"] = params.organisation;
      if (params.subject !== undefined) query["subject"] = params.subject;
      if (params.kinds !== undefined && params.kinds.length > 0) {
        query["kind"] = params.kinds.join(",");
      }
      if (params.limit !== undefined) query["limit"] = String(params.limit);
      if (pageParam !== null) query["cursor"] = pageParam;
      return client.request<TimelinePage>("/timeline/", { query, signal });
    },
  });
}

export interface TimelineProps {
  person?: string;
  organisation?: string;
  subject?: string;
  /** The record's change history, shown in a tab next to the timeline when the viewer may read it. */
  history?: { resource: string; id: string | number };
  /** Kinds the filter offers before any entry of them loaded. */
  kinds?: readonly string[];
  /** Entries per page. Default 25. */
  pageSize?: number;
  /** Where a linked record opens (default: its registered record link, else nothing). */
  hrefFor?: (resource: string, id: string) => string | null;
  /** Opens an app path (a link's click). Default: the browser follows the link. */
  navigate?: (to: string) => void;
  /** The heading (default "Timeline"). `null` shows none. */
  title?: React.ReactNode;
  className?: string;
}

const CONTROL =
  "h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function when(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function EntryLinks({
  entry,
  hrefFor,
  navigate,
}: {
  entry: TimelineEntry;
  hrefFor: (resource: string, id: string) => string | null;
  navigate: ((to: string) => void) | undefined;
}): React.ReactElement | null {
  const links = entry.links
    .map((link) => ({ link, href: link.resource ? hrefFor(link.resource, link.id) : null }))
    .filter((found): found is { link: TimelineEntry["links"][number]; href: string } =>
      Boolean(found.href),
    );
  if (links.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-x-3 text-sm">
      {links.map(({ link, href }) => (
        <a
          key={`${link.model}:${link.id}`}
          href={href}
          className="text-primary underline-offset-4 hover:underline"
          onClick={(event) => {
            if (navigate === undefined) return;
            event.preventDefault();
            navigate(href);
          }}
        >
          Open {link.model.split(".").pop() ?? "record"}
        </a>
      ))}
    </span>
  );
}

function Entries({
  params,
  hrefFor,
  navigate,
  onKinds,
}: {
  params: TimelineParams;
  hrefFor: (resource: string, id: string) => string | null;
  navigate: ((to: string) => void) | undefined;
  onKinds: (kinds: string[]) => void;
}): React.ReactElement {
  const query = useTimeline(params);
  const entries = React.useMemo(
    () => query.data?.pages.flatMap((page) => page.results) ?? [],
    [query.data],
  );
  React.useEffect(() => {
    if (entries.length > 0) onKinds(entries.map((entry) => entry.kind));
  }, [entries, onKinds]);
  if (query.isPending) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-5 w-3/4" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        context={{ action: "view", resource: "timeline" }}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (entries.length === 0) {
    return (
      <EmptyState
        headingLevel={3}
        title="Nothing on the timeline yet"
        description="What happens in each part (an order, a booking, a note) shows here."
      />
    );
  }
  return (
    <div className="space-y-3">
      <ol className="space-y-4">
        {entries.map((entry) => {
          const own = timelineKind(entry.kind)?.render;
          return (
            <li key={entry.id} className="flex gap-3">
              <span
                aria-hidden="true"
                className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-primary"
              />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-medium">{entry.title}</p>
                <p className="text-sm text-muted-foreground">
                  <time dateTime={entry.occurred_at}>{when(entry.occurred_at)}</time>
                  {" · "}
                  {timelineKindLabel(entry.kind)}
                  {entry.actor_name !== "" ? ` · ${entry.actor_name}` : ""}
                </p>
                {own !== undefined ? (
                  own(entry)
                ) : entry.body !== "" ? (
                  <p className="whitespace-pre-line text-sm">{entry.body}</p>
                ) : null}
                <EntryLinks entry={entry} hrefFor={hrefFor} navigate={navigate} />
              </div>
            </li>
          );
        })}
      </ol>
      {query.hasNextPage ? (
        <PendingButton
          variant="outline"
          pending={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          Show more
        </PendingButton>
      ) : null}
    </div>
  );
}

function defaultHref(resource: string, id: string): string | null {
  return recordHref(resource, { id });
}

/** Experimental. The timeline of a person or a record, with a kind filter and paging. */
export function Timeline({
  person,
  organisation,
  subject,
  history,
  kinds = [],
  pageSize = 25,
  hrefFor = defaultHref,
  navigate,
  title = "Timeline",
  className,
}: TimelineProps): React.ReactElement {
  const filterId = React.useId();
  const [kind, setKind] = React.useState("");
  const [seen, setSeen] = React.useState<string[]>([...kinds]);
  const remember = React.useCallback((found: string[]) => {
    setSeen((now) => {
      const next = [...now];
      for (const name of found) if (!next.includes(name)) next.push(name);
      return next.length === now.length ? now : next;
    });
  }, []);
  const params: TimelineParams = {
    ...(person !== undefined ? { person } : {}),
    ...(organisation !== undefined ? { organisation } : {}),
    ...(subject !== undefined ? { subject } : {}),
    ...(kind !== "" ? { kinds: [kind] } : {}),
    limit: pageSize,
  };
  const changes = useChangeHistory(history?.resource ?? "", history?.id ?? "", undefined, {
    enabled: history !== undefined,
    retry: false,
  });
  const historyRefused =
    changes.error instanceof KarniApiError && [403, 404].includes(changes.error.status);
  const showChanges = history !== undefined && !historyRefused;
  const stream = (
    <div className="space-y-4">
      {seen.length > 1 || kind !== "" ? (
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor={filterId}>Show</Label>
          <select
            id={filterId}
            className={CONTROL}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">Everything</option>
            {[...seen]
              .sort((a, b) => timelineKindLabel(a).localeCompare(timelineKindLabel(b)))
              .map((name) => (
                <option key={name} value={name}>
                  {timelineKindLabel(name)}
                </option>
              ))}
          </select>
        </div>
      ) : null}
      <Entries params={params} hrefFor={hrefFor} navigate={navigate} onKinds={remember} />
    </div>
  );
  return (
    <section className={cn("space-y-4", className)} aria-label="Timeline">
      {title !== null ? <h2 className="text-lg font-semibold">{title}</h2> : null}
      {/* One tree whether or not the changes show, so the stream never remounts. */}
      <Tabs defaultValue="timeline">
        {showChanges ? (
          <TabsList aria-label="Timeline or changes">
            <TabsTrigger value="timeline">What happened</TabsTrigger>
            <TabsTrigger value="changes">Changes</TabsTrigger>
          </TabsList>
        ) : null}
        <TabsContent value="timeline" className={showChanges ? "pt-4" : "mt-0"}>
          {stream}
        </TabsContent>
        {showChanges && history !== undefined ? (
          <TabsContent value="changes" className="pt-4">
            <ChangeHistory resource={history.resource} id={history.id} title={null} />
          </TabsContent>
        ) : null}
      </Tabs>
    </section>
  );
}
