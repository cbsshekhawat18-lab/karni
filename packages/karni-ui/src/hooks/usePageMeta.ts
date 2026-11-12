/**
 * Experimental. `usePageMeta({ title, description })`: the page's title and description
 * for search engines and for the browser tab.
 *
 * A public page (a catalogue, a product, a course) is found through a search
 * engine, which reads `<title>` and `<meta name="description">`. The hook
 * sets both while the page is shown, and puts back what was there when it
 * goes. `siteName` is added after the title (`Brass Lamp | Corner Shop`).
 *
 * Override / escape hatch: set `document.title` yourself, or render the tags
 * on the server for crawlers that do not run scripts.
 */
import { useEffect } from "react";

export interface PageMeta {
  title?: string;
  description?: string;
  /** Added after the title, after a bar. */
  siteName?: string;
}

function descriptionTag(): HTMLMetaElement {
  const found = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (found) return found;
  const created = document.createElement("meta");
  created.name = "description";
  document.head.appendChild(created);
  return created;
}

/** Experimental. Sets `document.title` and the description meta tag while the caller is mounted. */
export function usePageMeta({ title, description, siteName }: PageMeta): void {
  useEffect(() => {
    if (title === undefined) return undefined;
    const before = document.title;
    document.title = siteName && siteName !== title ? `${title} | ${siteName}` : title;
    return () => {
      document.title = before;
    };
  }, [title, siteName]);
  useEffect(() => {
    if (description === undefined) return undefined;
    const tag = descriptionTag();
    const before = tag.content;
    tag.content = description;
    return () => {
      tag.content = before;
    };
  }, [description]);
}
