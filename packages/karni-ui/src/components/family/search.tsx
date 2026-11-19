/**
 * Experimental. `/search`: one search over every installed part (`GET
 * /search/`, cross-model search), the results part by part.
 *
 * Keyboard first: the box has focus when the page opens, Enter searches (and
 * keeps the query in the address through `onQueryChange`), Arrow Down moves
 * to the first result, the arrows walk the results, Home and End go to the
 * ends, and Escape goes back to the box. The server searches each model
 * through its own list access, so nobody finds a row they cannot list.
 *
 * `searchHitHref(hit, routes)` is where a hit goes: the record link its part
 * registered (`registerRecordLink`, which gets the hit as the row), else the
 * app's route that ends with `/<resource>/$id` (`/shop/products/$id`), else
 * `/<resource>/<id>`.
 */
import * as React from "react";
import { useGlobalSearch, type GlobalSearchHit } from "../../hooks/useGlobalSearch";
import { usePageMeta } from "../../hooks/usePageMeta";
import { ErrorState } from "../../states/ErrorState";
import { groupByPart } from "../global-search/global-search";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { recordHref } from "../resource/record-links";

/**
 * Experimental. Where a record of `resource` opens: its record link (`registerRecordLink`,
 * which gets `row`), else the app's route that ends with `/<resource>/$id`, else `null`.
 */
export function routeHref(
  resource: string,
  id: string | number,
  routes: readonly string[] = [],
  row: Readonly<Record<string, unknown>> = { id },
): string | null {
  const own = recordHref(resource, row);
  if (own !== null) return own;
  const tail = `/${resource}/$id`;
  const route = routes.find((path) => path === tail || path.endsWith(tail));
  return route !== undefined ? route.replace("$id", encodeURIComponent(String(id))) : null;
}

/** Experimental. Where a search hit opens: its record link, a route of the app, or `/<resource>/<id>`. */
export function searchHitHref(hit: GlobalSearchHit, routes: readonly string[] = []): string {
  return (
    routeHref(hit.resource, hit.id, routes, { ...hit }) ??
    `/${hit.resource}/${encodeURIComponent(String(hit.id))}`
  );
}

export interface SearchPageProps {
  /** The query (from the address). */
  query?: string;
  /** Keeps the query in the address (the router's replace). */
  onQueryChange?: (query: string) => void;
  /** Opens a hit inside the app. Default: a page load. */
  navigate?: (to: string) => void;
  /** Where a hit opens (default `searchHitHref(hit, routes)`). */
  hrefFor?: (hit: GlobalSearchHit) => string;
  /** The app's route paths, for `searchHitHref`. */
  routes?: readonly string[];
  /** Hits per resource. Default 10. */
  limit?: number;
  title?: string;
  siteName?: string;
}

const RESULT =
  "block rounded-md px-3 py-2 text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Experimental. `/search`: every part's results for one query, part by part. */
export function SearchPage({
  query = "",
  onQueryChange,
  navigate,
  hrefFor,
  routes = [],
  limit = 10,
  title = "Search",
  siteName,
}: SearchPageProps): React.ReactElement {
  usePageMeta({ title: query ? `${title}: ${query}` : title, siteName });
  const boxId = React.useId();
  const box = React.useRef<HTMLInputElement>(null);
  const results = React.useRef<HTMLDivElement>(null);
  const [text, setText] = React.useState(query);
  const [asked, setAsked] = React.useState(query.trim());
  React.useEffect(() => {
    setText(query);
    setAsked(query.trim());
  }, [query]);
  const search = useGlobalSearch({ q: asked, limit });
  const parts = groupByPart(search.data?.groups ?? []);
  const total = parts.reduce(
    (sum, part) => sum + part.groups.reduce((count, group) => count + group.hits.length, 0),
    0,
  );
  const href = hrefFor ?? ((hit: GlobalSearchHit) => searchHitHref(hit, routes));
  function submit(): void {
    const next = text.trim();
    setAsked(next);
    onQueryChange?.(next);
  }
  function links(): HTMLAnchorElement[] {
    return Array.from(results.current?.querySelectorAll<HTMLAnchorElement>("a[data-hit]") ?? []);
  }
  function onResultsKey(event: React.KeyboardEvent<HTMLDivElement>): void {
    const all = links();
    const at = all.indexOf(document.activeElement as HTMLAnchorElement);
    if (at < 0) return;
    let next: number | null = null;
    if (event.key === "ArrowDown") next = Math.min(at + 1, all.length - 1);
    else if (event.key === "ArrowUp") next = at === 0 ? -1 : at - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = all.length - 1;
    else if (event.key === "Escape") next = -1;
    if (next === null) return;
    event.preventDefault();
    if (next === -1) box.current?.focus();
    else all[next]?.focus();
  }
  let status: string;
  if (asked.length < 2) status = "Type at least 2 characters, then press Enter.";
  else if (search.isPending) status = "Searching…";
  else if (search.isError) status = "Search failed.";
  else if (total === 0) status = `Nothing found for “${asked}”.`;
  else status = `${total} ${total === 1 ? "result" : "results"} for “${asked}”.`;
  return (
    <div className="min-w-0 space-y-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <form
        role="search"
        className="flex max-w-128 gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor={boxId} className="sr-only">
          Search everything
        </label>
        <Input
          id={boxId}
          ref={box}
          type="search"
          autoFocus
          autoComplete="off"
          placeholder="A name, an email, an order number"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              const first = links()[0];
              if (first !== undefined) {
                event.preventDefault();
                first.focus();
              }
            }
          }}
        />
        <Button type="submit">Search</Button>
      </form>
      <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
        {status}
      </p>
      {search.isError ? (
        <ErrorState
          error={search.error}
          context={{ action: "view", resource: "search" }}
          onRetry={() => void search.refetch()}
        />
      ) : null}
      <div ref={results} className="space-y-8" onKeyDown={onResultsKey}>
        {parts.map((part) => (
          <section
            key={part.part || "results"}
            aria-labelledby={`${boxId}-${part.part}`}
            className="space-y-4"
          >
            {parts.length > 1 || part.label !== "" ? (
              <h2 id={`${boxId}-${part.part}`} className="text-lg font-semibold">
                {part.label || "Results"}
              </h2>
            ) : null}
            {part.groups.map((group) => (
              <div key={group.resource} className="space-y-1">
                <h3 className="px-3 text-sm font-medium text-muted-foreground">{group.label}</h3>
                <ul>
                  {group.hits.map((hit) => {
                    const target = href(hit);
                    return (
                      <li key={`${hit.resource}:${String(hit.id)}`}>
                        <a
                          data-hit=""
                          href={target}
                          className={RESULT}
                          onClick={(event) => {
                            if (navigate === undefined) return;
                            event.preventDefault();
                            navigate(target);
                          }}
                        >
                          <span className="block font-medium">{hit.title}</span>
                          {hit.subtitle ? (
                            <span className="block text-muted-foreground">{hit.subtitle}</span>
                          ) : null}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
