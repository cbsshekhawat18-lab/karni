/**
 * The width of an element, kept current with a ResizeObserver. ResourceTable
 * switches to cards from its own container's width, not the viewport's, so a
 * table in a narrow sidebar or a split view lays out for the room it has.
 * `undefined` until measured (and where there is no layout, as in jsdom), so
 * the table keeps its default layout rather than guessing.
 * Internal to @karni/ui.
 */
import * as React from "react";

const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

export function useContainerWidth(ref: React.RefObject<HTMLElement | null>): number | undefined {
  const [width, setWidth] = React.useState<number | undefined>(undefined);
  useIsomorphicLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return undefined;
    const measure = (next: number): void => setWidth(next > 0 ? next : undefined);
    measure(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) measure(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
