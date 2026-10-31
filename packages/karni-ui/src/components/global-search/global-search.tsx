import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as React from "react";
import {
  useGlobalSearch,
  type GlobalSearchGroup,
  type GlobalSearchHit,
} from "../../hooks/useGlobalSearch";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { useDebouncedValue } from "../resource/table/use-debounced-value";

registerComponentRole("global-search", "GlobalSearch");

type IconProps = React.SVGAttributes<SVGSVGElement>;

function SearchIcon(props: IconProps): React.ReactElement {
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
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

/** Experimental. What the `Trigger` slot (the button that opens the palette) receives. */
export interface GlobalSearchTriggerProps {
  onClick: () => void;
  /** The shortcut as shown ("⌘K", "Ctrl K"), or null when it is off. */
  shortcut: string | null;
  /** The button's text ("Search"). */
  label: string;
}

/** Experimental. What the `ResultLink` slot (one hit, a listbox option) receives. */
export interface GlobalSearchResultLinkProps<R extends string = string> {
  hit: GlobalSearchHit<R>;
  href: string;
  id: string;
  role: "option";
  "aria-selected": boolean;
  tabIndex: -1;
  className: string;
  onClick: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  onMouseMove: () => void;
  /** The title and the subtitle. */
  children: React.ReactNode;
}

/** Experimental. The parts of the palette a project can replace. */
export interface GlobalSearchSlots<R extends string = string> {
  /** The button in the header. `() => null` keeps only the shortcut. */
  Trigger: React.ComponentType<GlobalSearchTriggerProps>;
  /** Each hit. Replace it with your router's link, passing every prop on. */
  ResultLink: React.ComponentType<GlobalSearchResultLinkProps<R>>;
}

/** Experimental. The props of GlobalSearch. */
export interface GlobalSearchProps<R extends string = string> {
  /** Controlled open state (pair with onOpenChange). */
  open?: boolean;
  /** Initial open state when uncontrolled. */
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Cmd (macOS) or Ctrl plus this key opens and closes the palette. `false` turns it off. */
  shortcut?: string | false;
  /** The resources to search (default: every one search covers). */
  models?: readonly R[];
  /** Hits per resource. */
  limit?: number;
  /** The shortest query sent (default 2, the server's KARNI_GLOBAL_SEARCH_MIN_LENGTH). */
  minLength?: number;
  /** Milliseconds a pause in typing waits before searching (default 200). */
  debounceMs?: number;
  /** The input's placeholder and accessible name. */
  placeholder?: string;
  /** The trigger button's text and the dialog's title (default "Search"). */
  label?: string;
  /** Where a hit links (default `/<resource>/<id>`, the ResourceDetail route `karni make page` writes). */
  hrefFor?: (hit: GlobalSearchHit<R>) => string;
  /**
   * Called when a hit is chosen (a click, or Enter on the active one). The
   * palette then closes. Without it, the hit's link is followed.
   */
  onSelect?: (hit: GlobalSearchHit<R>) => void;
  /** Replaces the Trigger or the ResultLink. See GlobalSearchSlots. */
  slots?: Partial<GlobalSearchSlots<R>>;
  /** Extra classes for the trigger's wrapper. */
  className?: string;
}

const ICON_BUTTON_CLASS =
  "inline-flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const OPTION_CLASS =
  "flex cursor-pointer flex-col rounded-md px-3 py-2 text-sm text-foreground no-underline focus:outline-none";
const ACTIVE_OPTION_CLASS = "bg-accent text-accent-foreground";

function shortcutText(key: string): string {
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  return mac ? `⌘${key.toUpperCase()}` : `Ctrl ${key.toUpperCase()}`;
}

function DefaultTrigger({
  onClick,
  shortcut,
  label,
}: GlobalSearchTriggerProps): React.ReactElement {
  return (
    <button type="button" onClick={onClick} className={ICON_BUTTON_CLASS} aria-haspopup="dialog">
      <SearchIcon className="h-4 w-4" />
      <span>{label}</span>
      {shortcut !== null && (
        <kbd className="ml-2 rounded border border-border bg-muted px-1.5 font-mono text-xs text-muted-foreground">
          {shortcut}
        </kbd>
      )}
    </button>
  );
}

function DefaultResultLink<R extends string>(
  props: GlobalSearchResultLinkProps<R>,
): React.ReactElement {
  const { hit, children, ...link } = props;
  return (
    <a {...link} data-resource={hit.resource}>
      {children}
    </a>
  );
}

/** Experimental. The default pieces of the palette, for wrapping one. */
export const defaultGlobalSearchSlots: GlobalSearchSlots = {
  Trigger: DefaultTrigger,
  ResultLink: DefaultResultLink,
};

/** Experimental. The default link of a hit: `/<resource>/<id>`. */
export function defaultHitHref(hit: GlobalSearchHit): string {
  return `/${hit.resource}/${encodeURIComponent(String(hit.id))}`;
}

interface Option<R extends string> {
  hit: GlobalSearchHit<R>;
  id: string;
}

const NO_GROUPS: never[] = [];

/**
 * Experimental. A command palette over cross-model search (`GET /search/`).
 *
 * Cmd+K (macOS) or Ctrl+K opens it, as does the trigger button. Typing
 * searches every model that declares `class Karni: search`, after a short
 * pause, and the results come grouped per resource, best first. Each hit
 * links to its ResourceDetail page (`/<resource>/<id>`).
 *
 * Keyboard and screen readers: the WAI-ARIA combobox pattern. The input is a
 * combobox that owns a listbox of grouped options. Arrow Down and Arrow Up
 * move the active option (focus stays in the input, `aria-activedescendant`
 * names the option), Enter opens it, Escape closes the palette and focus
 * returns to what opened it. A polite live region says how many hits there
 * are.
 *
 * Escape hatches: `hrefFor` changes where a hit links, `onSelect` navigates
 * with your router, `slots.ResultLink` renders your router's link,
 * `slots.Trigger` replaces the button, `open`/`onOpenChange` control it, and
 * `shortcut={false}` turns the shortcut off. `useGlobalSearch` is the data
 * underneath, for a search page of your own.
 */
export function GlobalSearch<R extends string = string>({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  shortcut = "k",
  models,
  limit,
  minLength = 2,
  debounceMs = 200,
  placeholder = "Search…",
  label = "Search",
  hrefFor = defaultHitHref,
  onSelect,
  slots,
  className,
}: GlobalSearchProps<R>): React.ReactElement {
  const { Trigger, ResultLink } = {
    ...(defaultGlobalSearchSlots as unknown as GlobalSearchSlots<R>),
    ...slots,
  };
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const open = openProp ?? uncontrolledOpen;
  const setOpen = React.useCallback(
    (next: boolean) => {
      if (openProp === undefined) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [openProp, onOpenChange],
  );

  React.useEffect(() => {
    if (shortcut === false) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === shortcut.toLowerCase()) {
        event.preventDefault();
        setOpen(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [shortcut, open, setOpen]);

  return (
    <div className={cn("inline-flex", className)}>
      <Trigger
        onClick={() => setOpen(true)}
        shortcut={shortcut === false ? null : shortcutText(shortcut)}
        label={label}
      />
      <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-modal bg-overlay" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-x-4 top-20 z-modal mx-auto max-w-[var(--karni-search-width)] rounded-lg border border-border bg-popover text-popover-foreground shadow-lg focus:outline-none"
          >
            <DialogPrimitive.Title className="sr-only">{label}</DialogPrimitive.Title>
            {open && (
              <Palette<R>
                models={models}
                limit={limit}
                minLength={minLength}
                debounceMs={debounceMs}
                placeholder={placeholder}
                hrefFor={hrefFor}
                onSelect={onSelect}
                onClose={() => setOpen(false)}
                ResultLink={ResultLink}
              />
            )}
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </div>
  );
}

interface PaletteProps<R extends string> {
  models: readonly R[] | undefined;
  limit: number | undefined;
  minLength: number;
  debounceMs: number;
  placeholder: string;
  hrefFor: (hit: GlobalSearchHit<R>) => string;
  onSelect: ((hit: GlobalSearchHit<R>) => void) | undefined;
  onClose: () => void;
  ResultLink: React.ComponentType<GlobalSearchResultLinkProps<R>>;
}

function Palette<R extends string>({
  models,
  limit,
  minLength,
  debounceMs,
  placeholder,
  hrefFor,
  onSelect,
  onClose,
  ResultLink,
}: PaletteProps<R>): React.ReactElement {
  const baseId = React.useId();
  const listboxId = `${baseId}-listbox`;
  const [text, setText] = React.useState("");
  const query = useDebouncedValue(text.trim(), debounceMs);
  const long = query.length >= minLength;
  const search = useGlobalSearch<R>(
    {
      q: query,
      ...(models !== undefined ? { models } : {}),
      ...(limit !== undefined ? { limit } : {}),
    },
    { minLength },
  );
  const groups: Array<GlobalSearchGroup<R>> =
    long && search.data !== undefined ? search.data.groups : NO_GROUPS;
  const options = React.useMemo<Array<Option<R>>>(
    () =>
      groups.flatMap((group) =>
        group.hits.map((hit) => ({ hit, id: `${baseId}-${hit.resource}-${String(hit.id)}` })),
      ),
    [groups, baseId],
  );
  const [active, setActive] = React.useState(0);
  React.useEffect(() => setActive(0), [options]);
  const activeOption = options[active];

  React.useEffect(() => {
    if (activeOption === undefined) return;
    document.getElementById(activeOption.id)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOption]);

  const choose = (option: Option<R>, event?: React.SyntheticEvent): void => {
    if (onSelect !== undefined) {
      event?.preventDefault();
      onSelect(option.hit);
      onClose();
      return;
    }
    if (event === undefined) {
      // Enter: follow the option's own link, as a click would.
      document.getElementById(option.id)?.click();
      return;
    }
    onClose();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (options.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + options.length) % options.length);
    } else if (event.key === "Home" && event.ctrlKey) {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End" && event.ctrlKey) {
      event.preventDefault();
      setActive(options.length - 1);
    } else if (event.key === "Enter" && activeOption !== undefined) {
      event.preventDefault();
      choose(activeOption);
    }
  };

  const pending = long && (search.isPending || (search.isFetching && search.isPlaceholderData));
  let status: string;
  if (!long) status = `Type at least ${minLength} characters to search.`;
  else if (search.isError) status = "Search failed. Try again.";
  else if (pending && options.length === 0) status = "Searching…";
  else if (options.length === 0) status = `No results for “${query}”.`;
  else status = `${options.length} ${options.length === 1 ? "result" : "results"}.`;

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3">
        <SearchIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
        <input
          autoFocus
          type="text"
          role="combobox"
          aria-label={placeholder}
          aria-expanded={options.length > 0}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeOption?.id}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          className="h-12 w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
      </div>
      <div
        id={listboxId}
        role="listbox"
        aria-label="Search results"
        className="max-h-[var(--karni-search-max-height)] overflow-y-auto p-2"
      >
        {groups.map((group) => {
          const headingId = `${baseId}-${group.resource}-heading`;
          return (
            <div key={group.resource} role="group" aria-labelledby={headingId} className="py-1">
              <div
                id={headingId}
                role="presentation"
                className="px-3 py-1 text-xs font-medium text-muted-foreground"
              >
                {group.label}
              </div>
              {group.hits.map((hit) => {
                const option = options.find((item) => item.hit === hit);
                if (option === undefined) return null;
                const selected = option === activeOption;
                return (
                  <ResultLink
                    key={option.id}
                    hit={hit}
                    href={hrefFor(hit)}
                    id={option.id}
                    role="option"
                    aria-selected={selected}
                    tabIndex={-1}
                    className={cn(OPTION_CLASS, selected && ACTIVE_OPTION_CLASS)}
                    onClick={(event) => choose(option, event)}
                    onMouseMove={() => setActive(options.indexOf(option))}
                  >
                    <span className="truncate font-medium">{hit.title}</span>
                    {hit.subtitle !== null && hit.subtitle !== "" && (
                      <span className="truncate text-xs text-muted-foreground">{hit.subtitle}</span>
                    )}
                  </ResultLink>
                );
              })}
            </div>
          );
        })}
      </div>
      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className={cn(
          "border-t border-border px-3 py-2 text-xs text-muted-foreground",
          options.length > 0 && "sr-only",
        )}
      >
        {status}
      </p>
    </div>
  );
}
