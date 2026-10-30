/**
 * MarkdownView's renderer, loaded on first use (`import("./render")`), so a
 * page without markdown never downloads the parser or the sanitizer.
 *
 * The pipeline: marked turns the markdown into HTML (GitHub-flavoured: tables,
 * strikethrough, autolinks). Raw HTML in the source is escaped, so it shows as
 * text, unless `allowHtml`. Then DOMPurify removes everything that could run
 * script or reach outside the page: script and style elements, event-handler
 * attributes, `javascript:` and other unsafe URLs, forms, frames and inline
 * styles. Links that leave the site get `rel="noopener noreferrer nofollow"`
 * (and open in a new tab unless told otherwise). Internal to @karni/ui.
 */
import DOMPurify, { type Config } from "dompurify";
import { Marked, type Tokens } from "marked";

export interface MarkdownRenderOptions {
  /** Keep the source's own HTML (after sanitizing) instead of escaping it. */
  allowHtml: boolean;
  /** Added to every heading level (`#` with 1 becomes an h2), capped at h6. */
  headingOffset: number;
  /** How a link to another site opens. */
  externalLinks: "new-tab" | "same-tab";
  /** Return false to drop a link (its text stays). Runs after the URL check. */
  isLinkAllowed: ((href: string) => boolean) | undefined;
  /** Elements and attributes allowed on top of the safe set (an escape hatch). */
  addTags: readonly string[];
  addAttributes: readonly string[];
  /** The page's origin, to tell an external link from an internal one. */
  origin: string;
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ESCAPES[ch] ?? ch);
}

/** Never allowed, whatever the options: they run script, submit data or restyle the page. */
const FORBID_TAGS = [
  "script",
  "style",
  "link",
  "meta",
  "base",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "option",
  "iframe",
  "frame",
  "frameset",
  "object",
  "embed",
  "svg",
  "math",
  "template",
];
const FORBID_ATTR = ["style", "srcset", "formaction", "action", "xlink:href"];

const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const SAFE_SCHEME = /^(?:https?|mailto|tel):/i;

/** http(s), mailto and tel links, and links within the site (relative, or #anchor). */
function isSafeUrl(href: string): boolean {
  // Browsers ignore tabs, newlines and spaces inside a scheme ("java\tscript:"), so the check does too.
  const compact = Array.from(href)
    .filter((ch) => ch.charCodeAt(0) > 32)
    .join("");
  return !SCHEME.test(compact) || SAFE_SCHEME.test(compact);
}

function isExternal(href: string, origin: string): boolean {
  if (!/^https?:/i.test(href)) return false;
  try {
    return new URL(href).origin !== origin;
  } catch {
    return true;
  }
}

function parser(options: MarkdownRenderOptions): Marked {
  const marked = new Marked({ gfm: true, async: false });
  marked.use({
    renderer: {
      heading(this: { parser: { parseInline: (tokens: Tokens.Generic[]) => string } }, token) {
        const level = Math.min(6, Math.max(1, token.depth + options.headingOffset));
        return `<h${level}>${this.parser.parseInline(token.tokens)}</h${level}>\n`;
      },
      ...(options.allowHtml ? {} : { html: ({ text }: { text: string }) => escapeHtml(text) }),
    },
  });
  return marked;
}

/** The markdown as sanitized HTML, ready for `dangerouslySetInnerHTML`. */
export function renderMarkdown(source: string, options: MarkdownRenderOptions): string {
  const html = parser(options).parse(source, { async: false });
  // A private instance: the hook below never touches a DOMPurify the app uses itself.
  const purify = DOMPurify(window);
  purify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName !== "A") return;
    const href = node.getAttribute("href");
    if (href === null) return;
    const trimmed = href.trim();
    if (
      !isSafeUrl(trimmed) ||
      (options.isLinkAllowed !== undefined && !options.isLinkAllowed(trimmed))
    ) {
      node.removeAttribute("href");
      node.removeAttribute("target");
      return;
    }
    if (isExternal(trimmed, options.origin)) {
      node.setAttribute("rel", "noopener noreferrer nofollow");
      if (options.externalLinks === "new-tab") node.setAttribute("target", "_blank");
      else node.removeAttribute("target");
    } else {
      node.removeAttribute("target");
    }
  });
  const config: Config = {
    USE_PROFILES: { html: true },
    FORBID_TAGS,
    FORBID_ATTR,
    ADD_TAGS: [...options.addTags],
    ADD_ATTR: [...options.addAttributes, "target"],
    ALLOW_DATA_ATTR: false,
  };
  return purify.sanitize(html, config);
}
