/**
 * <MarkdownView>: markdown text shown as formatted, sanitized HTML.
 *
 * Experimental. The parser (marked) and the sanitizer (DOMPurify) load on the
 * first MarkdownView a page renders, so a page without one never downloads
 * them. Raw HTML in the source shows as text unless `allowHtml`, and even
 * then it is sanitized: no script, no event handler, no `javascript:` link,
 * no form, frame or inline style. A link to another site gets
 * `rel="noopener noreferrer nofollow"` and opens in a new tab.
 *
 * Headings move down one level by default (`#` renders an h2), because the
 * page title is the h1. `headingOffset={0}` keeps them as written.
 *
 * Escape hatches: `isLinkAllowed` drops links a project does not want,
 * `sanitize.addTags` and `sanitize.addAttributes` allow more than the safe
 * set, `slots.Loading` replaces the placeholder shown while the renderer
 * loads, and `className` merges on the root.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { Skeleton } from "../primitives/skeleton";
import type { MarkdownRenderOptions } from "./render";

registerComponentRole("markdown", "MarkdownView");

type Renderer = typeof import("./render");

let loaded: Renderer | null = null;
let loading: Promise<Renderer> | null = null;

/** The renderer module, loaded once for the whole page. */
function loadRenderer(): Promise<Renderer> {
  loading ??= import("./render").then((module) => {
    loaded = module;
    return module;
  });
  return loading;
}

/** What the `Loading` slot receives. */
export interface MarkdownViewLoadingProps {
  /** The markdown source, for a placeholder of its size. */
  source: string;
}

export interface MarkdownViewSlots {
  /** Shown until the renderer has loaded (once per page). */
  Loading: React.ComponentType<MarkdownViewLoadingProps>;
}

export interface MarkdownViewProps extends Omit<
  React.HTMLAttributes<HTMLDivElement>,
  "children" | "dangerouslySetInnerHTML"
> {
  /** The markdown source. `null` or `undefined` renders nothing. */
  source: string | null | undefined;
  /** Keep the source's own HTML (sanitized) instead of showing it as text. Default false. */
  allowHtml?: boolean;
  /** Added to every heading level (default 1: `#` renders an h2). */
  headingOffset?: number;
  /** How a link to another site opens (default "new-tab"). */
  externalLinks?: "new-tab" | "same-tab";
  /** Return false to drop a link (its text stays). Unsafe URLs are dropped before this runs. */
  isLinkAllowed?: (href: string) => boolean;
  /** Elements and attributes to allow on top of the safe set. */
  sanitize?: { addTags?: readonly string[]; addAttributes?: readonly string[] };
  slots?: Partial<MarkdownViewSlots>;
}

function DefaultLoading({ source }: MarkdownViewLoadingProps): React.ReactElement {
  const lines = Math.min(6, Math.max(1, source.split("\n").filter(Boolean).length));
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cn("h-4", index === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** MarkdownView's default slots, exported so a project can wrap one. */
export const defaultMarkdownViewSlots: MarkdownViewSlots = { Loading: DefaultLoading };

/** The typography of rendered markdown: every value is a theme token. */
const PROSE = cn(
  "min-w-0 break-words text-sm text-foreground",
  "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
  "[&_p]:my-3 [&_ul]:my-3 [&_ol]:my-3 [&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-6 [&_ol]:pl-6 [&_li]:my-1",
  "[&_h1]:mb-3 [&_h1]:mt-6 [&_h1]:text-2xl [&_h1]:font-semibold [&_h1]:tracking-tight",
  "[&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:tracking-tight",
  "[&_h3]:mb-2 [&_h3]:mt-5 [&_h3]:text-lg [&_h3]:font-semibold",
  "[&_h4]:mb-2 [&_h4]:mt-4 [&_h4]:text-base [&_h4]:font-semibold",
  "[&_h5]:mb-2 [&_h5]:mt-4 [&_h5]:text-sm [&_h5]:font-semibold",
  "[&_h6]:mb-2 [&_h6]:mt-4 [&_h6]:text-sm [&_h6]:font-medium [&_h6]:text-muted-foreground",
  "[&_a]:font-medium [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4",
  "[&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground",
  "[&_code]:rounded-sm [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs",
  "[&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3",
  "[&_pre_code]:bg-muted [&_pre_code]:p-0",
  "[&_hr]:my-6 [&_hr]:border-border",
  "[&_img]:max-w-full [&_img]:rounded-md",
  "[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm",
  "[&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-medium",
  "[&_td]:border [&_td]:border-border [&_td]:px-3 [&_td]:py-2",
);

/** Experimental. Markdown shown as formatted, sanitized HTML (the parser loads on first use). */
export const MarkdownView = React.forwardRef<HTMLDivElement, MarkdownViewProps>(
  (
    {
      source,
      allowHtml = false,
      headingOffset = 1,
      externalLinks = "new-tab",
      isLinkAllowed,
      sanitize,
      slots,
      className,
      ...props
    },
    ref,
  ) => {
    const Slots: MarkdownViewSlots = { ...defaultMarkdownViewSlots, ...slots };
    const [renderer, setRenderer] = React.useState<Renderer | null>(loaded);
    const [failed, setFailed] = React.useState(false);
    React.useEffect(() => {
      if (renderer !== null) return undefined;
      let alive = true;
      loadRenderer().then(
        (module) => {
          if (alive) setRenderer(module);
        },
        () => {
          if (alive) setFailed(true);
        },
      );
      return () => {
        alive = false;
      };
    }, [renderer]);

    const addTags = sanitize?.addTags;
    const addAttributes = sanitize?.addAttributes;
    const html = React.useMemo(() => {
      if (renderer === null || source == null) return null;
      const options: MarkdownRenderOptions = {
        allowHtml,
        headingOffset,
        externalLinks,
        isLinkAllowed,
        addTags: addTags ?? [],
        addAttributes: addAttributes ?? [],
        origin: typeof window === "undefined" ? "" : window.location.origin,
      };
      return renderer.renderMarkdown(source, options);
    }, [
      renderer,
      source,
      allowHtml,
      headingOffset,
      externalLinks,
      isLinkAllowed,
      addTags,
      addAttributes,
    ]);

    if (source == null) return null;
    if (failed) {
      // The renderer could not load (offline): the text itself, never as HTML.
      return (
        <div ref={ref} className={cn(PROSE, "whitespace-pre-wrap", className)} {...props}>
          {source}
        </div>
      );
    }
    if (html === null) {
      return (
        <div ref={ref} aria-busy="true" className={cn(PROSE, className)} {...props}>
          <Slots.Loading source={source} />
          <span className="sr-only">Loading</span>
        </div>
      );
    }
    return (
      <div
        ref={ref}
        className={cn(PROSE, className)}
        {...props}
        // The HTML comes from renderMarkdown, which sanitizes it with DOMPurify.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  },
);
MarkdownView.displayName = "MarkdownView";

/** Experimental. Loads MarkdownView's renderer ahead of time (on hover of a link to a page that shows markdown, say). */
export function preloadMarkdown(): Promise<void> {
  return loadRenderer().then(() => undefined);
}
