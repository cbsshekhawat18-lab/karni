/**
 * ResourceTable's server-mode pagination row (DRF PageNumberPagination:
 * `{count, next, previous, results}` with `page` / `page_size` params):
 * "Page X of Y · N items", a page size choice, first / previous / next /
 * last, and a page number to jump to. Only one page is ever fetched.
 *
 * While a page is on its way (`busy`) the buttons stay focusable but ignore
 * clicks (`aria-disabled`), so a double click never skips a page and a
 * keyboard user's focus stays put; after 500ms the clicked button shows
 * progress. The default of ResourceTable's `Pagination` slot.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { useDelayedFlag } from "../../../states/hooks";
import { Button } from "../../primitives/button";
import { SpinnerIcon } from "../../primitives/icons";
import { Input } from "../../primitives/input";
import { Select } from "../../primitives/select";
import { ChevronLeftIcon, ChevronRightIcon, FirstPageIcon, LastPageIcon } from "./table-icons";

export interface PaginationControlsProps {
  /** 1-based current page. */
  page: number;
  pageCount: number;
  /** Total item count across all pages (DRF `count`). */
  totalCount: number;
  /** From DRF `previous` / `next` — the server is the authority. */
  hasPrevious: boolean;
  hasNext: boolean;
  onPageChange: (page: number) => void;
  /** Rows per page; with `onPageSizeChange` and `pageSizeOptions` it renders the size choice. */
  pageSize?: number;
  pageSizeOptions?: readonly number[];
  onPageSizeChange?: (pageSize: number) => void;
  /** A page is loading: controls announce busy and ignore clicks. */
  busy?: boolean;
  className?: string;
}

type Target = "first" | "previous" | "next" | "last" | "jump";

interface NavButtonProps {
  label: string;
  /** Shown as text; icon-only buttons pass `null` and keep `label` as their name. */
  text: React.ReactNode;
  icon?: React.ReactNode;
  iconAfter?: boolean;
  unavailable: boolean;
  busy: boolean;
  spinning: boolean;
  onActivate: () => void;
  buttonRef?: React.Ref<HTMLButtonElement>;
}

function NavButton(props: NavButtonProps): React.ReactElement {
  const { label, text, icon, iconAfter, unavailable, busy, spinning, onActivate, buttonRef } =
    props;
  return (
    <Button
      ref={buttonRef}
      variant="outline"
      size="sm"
      disabled={unavailable}
      aria-label={text === null ? label : undefined}
      title={text === null ? label : undefined}
      aria-disabled={busy || undefined}
      aria-busy={spinning || undefined}
      className={cn(
        "relative aria-disabled:cursor-wait [&[aria-disabled]:not([aria-busy])]:opacity-50",
        text === null && "w-9 px-0",
      )}
      onClick={() => {
        if (!busy) onActivate();
      }}
    >
      <span className={cn("inline-flex items-center gap-1", spinning && "invisible")}>
        {!iconAfter && icon}
        {text}
        {iconAfter === true && icon}
      </span>
      {spinning && (
        <span className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
          <SpinnerIcon className="h-4 w-4 animate-spin" />
        </span>
      )}
    </Button>
  );
}

export function PaginationControls(props: PaginationControlsProps): React.ReactElement {
  const {
    page,
    pageCount,
    totalCount,
    hasPrevious,
    hasNext,
    onPageChange,
    pageSize,
    pageSizeOptions,
    onPageSizeChange,
    busy = false,
    className,
  } = props;
  const [target, setTarget] = React.useState<Target | null>(null);
  const slow = useDelayedFlag(busy);
  const [jump, setJump] = React.useState("");
  const jumpId = React.useId();
  const previousRef = React.useRef<HTMLButtonElement>(null);
  const nextRef = React.useRef<HTMLButtonElement>(null);
  const [refocus, setRefocus] = React.useState<"previous" | "next" | null>(null);

  // A button that just went unavailable would drop keyboard focus to <body>:
  // hand it to the button pointing the other way.
  React.useEffect(() => {
    if (refocus === "next" && !hasPrevious) nextRef.current?.focus();
    if (refocus === "previous" && !hasNext) previousRef.current?.focus();
    if (refocus !== null) setRefocus(null);
  }, [refocus, hasPrevious, hasNext]);

  const go = (next: number, from: Target): void => {
    const clamped = Math.min(Math.max(1, next), Math.max(1, pageCount));
    if (clamped === page) return;
    setTarget(from);
    if (clamped === 1 && (from === "first" || from === "previous")) setRefocus("next");
    if (clamped === pageCount && (from === "last" || from === "next")) setRefocus("previous");
    onPageChange(clamped);
  };

  const spinning = (which: Target): boolean => slow && target === which;
  const sizes =
    pageSize !== undefined && pageSizeOptions !== undefined
      ? [...new Set([...pageSizeOptions, pageSize])].sort((a, b) => a - b)
      : [];

  return (
    <nav
      aria-label="Pagination"
      aria-busy={busy || undefined}
      className={cn("flex flex-wrap items-center justify-between gap-x-3 gap-y-2", className)}
    >
      <p className="text-sm text-muted-foreground">
        Page {page.toLocaleString()} of {pageCount.toLocaleString()} · {totalCount.toLocaleString()}{" "}
        {totalCount === 1 ? "item" : "items"}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {sizes.length > 1 && onPageSizeChange !== undefined && pageSize !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground" aria-hidden="true">
              Rows per page
            </span>
            <Select
              aria-label="Rows per page"
              className="h-9 w-20"
              value={String(pageSize)}
              options={sizes.map((size) => ({ value: String(size), label: String(size) }))}
              onValueChange={(next) => {
                if (next !== null && !busy) onPageSizeChange(Number(next));
              }}
            />
          </div>
        )}
        <div className="flex items-center gap-1">
          <NavButton
            label="First page"
            text={null}
            icon={<FirstPageIcon className="h-4 w-4" />}
            unavailable={!hasPrevious}
            busy={busy}
            spinning={spinning("first")}
            onActivate={() => go(1, "first")}
          />
          <NavButton
            buttonRef={previousRef}
            label="Previous"
            text="Previous"
            icon={<ChevronLeftIcon className="h-4 w-4" />}
            unavailable={!hasPrevious}
            busy={busy}
            spinning={spinning("previous")}
            onActivate={() => go(page - 1, "previous")}
          />
          <NavButton
            buttonRef={nextRef}
            label="Next"
            text="Next"
            icon={<ChevronRightIcon className="h-4 w-4" />}
            iconAfter
            unavailable={!hasNext}
            busy={busy}
            spinning={spinning("next")}
            onActivate={() => go(page + 1, "next")}
          />
          <NavButton
            label="Last page"
            text={null}
            icon={<LastPageIcon className="h-4 w-4" />}
            unavailable={!hasNext || page >= pageCount}
            busy={busy}
            spinning={spinning("last")}
            onActivate={() => go(pageCount, "last")}
          />
        </div>
        {pageCount > 2 && (
          <form
            className="flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              const wanted = Number(jump);
              if (busy || !Number.isInteger(wanted) || jump.trim() === "") return;
              go(wanted, "jump");
              setJump("");
            }}
          >
            <label htmlFor={jumpId} className="sr-only">
              Go to page (1 to {pageCount})
            </label>
            <Input
              id={jumpId}
              type="number"
              inputMode="numeric"
              min={1}
              max={pageCount}
              placeholder="Page"
              value={jump}
              onChange={(event) => setJump(event.target.value)}
              className="h-9 w-20"
            />
            <Button
              type="submit"
              variant="outline"
              size="sm"
              aria-disabled={busy || undefined}
              className="aria-disabled:cursor-wait aria-disabled:opacity-50"
            >
              Go
            </Button>
          </form>
        )}
      </div>
    </nav>
  );
}
