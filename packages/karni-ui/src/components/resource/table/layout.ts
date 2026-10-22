/**
 * The class lists ResourceTable's table and its loading skeleton share, so
 * the skeleton occupies exactly the box the data will: same container, same
 * header height, same row height per density. Internal to @karni/ui.
 */
import type { ResourceTableDensity } from "./preferences";

/** Row and header geometry per density. Every value is a spacing token. */
export const DENSITY_CLASSES: Record<
  ResourceTableDensity,
  { head: string; cell: string; action: string; card: string }
> = {
  comfortable: {
    head: "h-10 px-3",
    cell: "h-12 px-3 py-2",
    action: "h-8 px-3",
    card: "gap-3 p-4",
  },
  compact: {
    head: "h-9 px-2",
    cell: "h-9 px-2 py-1",
    action: "h-7 px-2",
    card: "gap-2 p-3",
  },
};

/**
 * The scrolling box: both directions scroll inside it, so 50 columns never
 * push the page sideways and the header can stick. Its height is capped by
 * the `--karni-table-max-height` token (70vh). Set it to `none` to let the
 * page scroll instead.
 */
export const SCROLL_BOX =
  "group/scroll relative w-full max-h-[var(--karni-table-max-height)] overflow-auto rounded-md border border-border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export const TABLE = "w-full border-separate border-spacing-0 text-sm";

/** Sticky on vertical scroll, above the frozen body cells. */
export const THEAD = "sticky top-0 z-raised";

export const HEAD_CELL =
  "whitespace-nowrap border-b border-border bg-muted text-left align-middle text-xs font-medium text-muted-foreground";

/** Opaque backgrounds on every cell, so frozen cells hide what scrolls beneath them. */
export const BODY_CELL =
  "whitespace-nowrap border-b border-border bg-background align-middle group-hover/row:bg-muted group-data-[state=selected]/row:bg-muted";

export const LAST_ROW = "[&>tr:last-child>td]:border-b-0";

/** The checkbox column: a fixed width, so the frozen first column can sit after it. */
export const SELECT_CELL = "sticky left-0 w-10 min-w-10 px-3";

/** The frozen first data column, with an edge once the table scrolls sideways. */
export const FROZEN_CELL =
  "sticky border-r border-r-transparent group-data-[scrolled=true]/scroll:border-r-border";

export const FROZEN_AT_START = "left-0";
export const FROZEN_AFTER_SELECT = "left-10";

/** The frozen column's content is capped, so it never takes the whole width. */
export const FROZEN_CONTENT = "max-w-72 truncate";
