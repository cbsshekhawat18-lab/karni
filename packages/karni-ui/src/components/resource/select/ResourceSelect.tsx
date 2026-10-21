import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as React from "react";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { useParsedSchema } from "../../../schema/useSchema";
import { describeError } from "../../../states/describe-error";
import { AlertIcon, ChevronDownIcon, SpinnerIcon } from "../../primitives/icons";
import { displayLabel } from "../displayLabel";
import { resourceNames, type ResourceLabel } from "../resource-names";
import {
  defaultResourceSelectSlots,
  emptyText,
  ResourceSelectClearIcon,
  type ResourceSelectEmptyProps,
  type ResourceSelectSlots,
} from "./select-states";
import { useDebouncedValue } from "./use-debounced-value";
import { useOptionPages, useSelectedRows, type OptionRow } from "./use-option-pages";

registerComponentRole("async-select", "ResourceSelect");

export interface ResourceSelectProps {
  resource: string;
  value: string | number | ReadonlyArray<string | number> | null;
  onChange: (value: string | number | Array<string | number> | null) => void;
  multiple?: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** Defaults to displayLabel(). */
  getOptionLabel?: (item: Record<string, unknown>) => React.ReactNode;
  /** Extra filter params sent with the search request. */
  filter?: Record<string, string | number | boolean>;
  id?: string;
  className?: string;
  /** Rows per options request; default the API's own page size. More load as the list scrolls. */
  pageSize?: number;
  /** Set false to hide the clear affordance (which emits null). Default true. */
  clearable?: boolean;
  /** Debounce for the ?search= request in ms. Default 300 (D8). */
  searchDebounceMs?: number;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  /** Ids of the help text and error message that describe the field. */
  "aria-describedby"?: string;
  /** Marks the field invalid (destructive border). */
  "aria-invalid"?: boolean | "true" | "false";
  "aria-required"?: boolean | "true" | "false";
  /** Called when focus leaves the select (not when it moves into its own list). */
  onBlur?: () => void;
  /** Replaces parts of the picker: Option, Chip, Loading, Empty, Error. */
  slots?: Partial<ResourceSelectSlots>;
  /**
   * Whether typing searches the server (`?search=`). Default: what the
   * schema says (a list without `search_fields` documents no `search`
   * parameter). Without search, typing narrows the rows already loaded and
   * the list says so.
   */
  searchable?: boolean;
  /**
   * The list filter that takes several ids at once, used to label
   * preselected values in one request. Default `"id__in"` when the schema
   * documents it; otherwise (or with `false`) each id loads from its detail
   * endpoint.
   */
  idsFilter?: string | false;
  /** How the related resource is named in messages; default derived from `resource`. */
  resourceLabel?: ResourceLabel;
}

/** Lists longer than this render only the rows in view (plus a margin). */
const VIRTUALIZE_AFTER = 100;
const OVERSCAN = 6;
/** h-8 at the default root font size; measured from the first option once rendered. */
const DEFAULT_ROW_HEIGHT = 32;
/** max-h-64 at the default root font size; measured once the list is open. */
const DEFAULT_VIEWPORT_HEIGHT = 256;
const LOADING_ROWS = 5;

function idOf(item: OptionRow): string | number {
  const value = item["id"];
  if (typeof value === "string" || typeof value === "number") return value;
  return String(value);
}

function shortId(id: string | number): string {
  const text = String(id);
  return text.length > 12 ? `${text.slice(0, 8)}…` : text;
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Searchable picker for a related row, querying the related resource as you type.
 *
 * Contract D8.
 *
 * A text input drives a debounced `?search=` request (or, when the API cannot
 * search, narrows the loaded rows and says so); options render in a
 * NON-MODAL Radix Popover that never takes focus from the input. Options load
 * a page at a time as the list scrolls or the keyboard reaches its end, never
 * all at once, and long lists render only the rows in view. The input
 * implements the ARIA 1.2 combobox pattern (aria-expanded, aria-controls,
 * aria-activedescendant); arrows, Home/End and PageUp/PageDown move through
 * every loaded page. Preselected ids are labelled in one request where the
 * API has an id-list filter, else per id; an id that cannot be loaded says
 * so instead of showing a bare id. The clear affordance emits `null`.
 */
export const ResourceSelect = React.forwardRef<HTMLInputElement, ResourceSelectProps>(
  function ResourceSelect(props, forwardedRef): React.ReactElement {
    const {
      resource,
      value,
      onChange,
      multiple = false,
      disabled = false,
      placeholder,
      getOptionLabel,
      filter,
      id,
      className,
      pageSize,
      clearable = true,
      searchDebounceMs = 300,
      onBlur,
      slots: slotOverrides,
      searchable: searchableProp,
      idsFilter: idsFilterProp,
      resourceLabel,
    } = props;
    const slots = { ...defaultResourceSelectSlots, ...slotOverrides };
    const names = resourceNames(resource, resourceLabel);

    const reactId = React.useId();
    const inputId = id ?? reactId;
    const listboxId = `${inputId}-listbox`;
    const optionDomId = (index: number): string => `${listboxId}-option-${index}`;

    // What the related resource's list can do, from the schema.
    const parsed = useParsedSchema();
    const listOperation = parsed.data?.resources[resource]?.operations.list;
    const searchable =
      searchableProp ?? (listOperation === undefined || listOperation.hasSearch === true);
    const idsFilter =
      idsFilterProp === false
        ? undefined
        : (idsFilterProp ??
          (listOperation?.queryParams.includes("id__in") === true ? "id__in" : undefined));

    const [open, setOpen] = React.useState(false);
    const [inputText, setInputText] = React.useState("");
    const [activeIndex, setActiveIndex] = React.useState(0);
    const [cache, setCache] = React.useState<Record<string, OptionRow>>({});
    const [scrollTop, setScrollTop] = React.useState(0);
    const [rowHeight, setRowHeight] = React.useState(DEFAULT_ROW_HEIGHT);
    const [viewportHeight, setViewportHeight] = React.useState(DEFAULT_VIEWPORT_HEIGHT);

    const rootRef = React.useRef<HTMLDivElement>(null);
    const contentRef = React.useRef<HTMLDivElement>(null);
    const scrollRef = React.useRef<HTMLDivElement>(null);
    const inputRef = React.useRef<HTMLInputElement | null>(null);
    /** ArrowDown at the last loaded option: move on once the next page arrives. */
    const advanceRef = React.useRef(false);

    const setInputRef = React.useCallback(
      (element: HTMLInputElement | null) => {
        inputRef.current = element;
        if (typeof forwardedRef === "function") forwardedRef(element);
        else if (forwardedRef !== null) forwardedRef.current = element;
      },
      [forwardedRef],
    );

    const term = inputText.trim();
    const debouncedTerm = useDebouncedValue(term, searchDebounceMs);
    const search = searchable ? debouncedTerm : "";

    const pages = useOptionPages({
      resource,
      search,
      filter,
      pageSize,
      enabled: open && !disabled,
    });

    const loadedRows = React.useMemo(() => {
      const seen = new Set<string>();
      const rows: OptionRow[] = [];
      for (const page of pages.data?.pages ?? []) {
        for (const row of page.results) {
          const key = String(idOf(row));
          if (seen.has(key)) continue;
          seen.add(key);
          rows.push(row);
        }
      }
      return rows;
    }, [pages.data]);
    const total = pages.data?.pages[0]?.count;
    const hasMore = pages.hasNextPage;

    // Remember every row seen, so selected values can always be labelled.
    React.useEffect(() => {
      if (loadedRows.length === 0) return;
      setCache((previous) => {
        let changed = false;
        const next = { ...previous };
        for (const row of loadedRows) {
          const key = String(idOf(row));
          if (!(key in next)) {
            next[key] = row;
            changed = true;
          }
        }
        return changed ? next : previous;
      });
    }, [loadedRows]);

    const labelOf = React.useCallback(
      (item: OptionRow): React.ReactNode =>
        getOptionLabel !== undefined ? getOptionLabel(item) : displayLabel(item),
      [getOptionLabel],
    );
    const labelTextOf = React.useCallback(
      (item: OptionRow): string => {
        const label = labelOf(item);
        if (typeof label === "string") return label;
        if (typeof label === "number") return String(label);
        return displayLabel(item);
      },
      [labelOf],
    );

    // Without server search, typing narrows the loaded rows.
    const options = React.useMemo(() => {
      if (searchable || term === "") return loadedRows;
      const needle = term.toLowerCase();
      return loadedRows.filter((row) => labelTextOf(row).toLowerCase().includes(needle));
    }, [searchable, term, loadedRows, labelTextOf]);
    const count = options.length;

    // --- selected values -------------------------------------------------
    const selected: ReadonlyArray<string | number> = React.useMemo(() => {
      if (value == null) return [];
      return Array.isArray(value) ? value : [value as string | number];
    }, [value]);
    const selectedKey = selected.map(String).join("\u0000");
    const cacheRef = React.useRef(cache);
    cacheRef.current = cache;
    // The ids to load are fixed when the value changes, so rows arriving in
    // option pages later never re-key (and repeat) the request.
    const toResolve = React.useMemo(
      () => selected.filter((sel) => !(String(sel) in cacheRef.current)),
      // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the value, read from the cache at that moment
      [selectedKey],
    );
    // Wait for the schema (or its failure): it decides between one batched
    // request and one request per id.
    const schemaSettled = parsed.data !== undefined || parsed.isError;
    const resolution = useSelectedRows(resource, toResolve, {
      idsFilter,
      enabled: schemaSettled,
    });

    const rowFor = (sel: string | number): OptionRow | undefined =>
      cache[String(sel)] ?? resolution.rows[String(sel)];
    const stateOf = (sel: string | number): "loaded" | "loading" | "failed" => {
      if (rowFor(sel) !== undefined) return "loaded";
      return resolution.failed.has(String(sel)) ? "failed" : "loading";
    };
    const failedText = (sel: string | number): string =>
      `Couldn't load ${names.singular} ${shortId(sel)}`;
    const selectedText = (sel: string | number): string => {
      const row = rowFor(sel);
      if (row !== undefined) return labelTextOf(row);
      return resolution.failed.has(String(sel)) ? failedText(sel) : "";
    };

    const isSelected = (optionId: string | number): boolean =>
      selected.some((sel) => String(sel) === String(optionId));

    // --- list geometry (virtual window) ------------------------------------
    const virtual = count > VIRTUALIZE_AFTER;
    const start = virtual ? Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN) : 0;
    const end = virtual
      ? Math.min(count, Math.ceil((scrollTop + viewportHeight) / rowHeight) + OVERSCAN)
      : count;

    const hasOptions = count > 0;
    React.useLayoutEffect(() => {
      if (!open) return;
      const container = scrollRef.current;
      if (container === null) return;
      if (container.clientHeight > 0) setViewportHeight(container.clientHeight);
      const first = container.querySelector("[role='option']");
      const height = first?.getBoundingClientRect().height ?? 0;
      if (height > 0) setRowHeight(height);
    }, [open, hasOptions]);

    const scrollToIndex = (index: number): void => {
      const top = index * rowHeight;
      let next = scrollTop;
      if (top < next) next = top;
      else if (top + rowHeight > next + viewportHeight) next = top + rowHeight - viewportHeight;
      if (next === scrollTop) return;
      if (scrollRef.current !== null) scrollRef.current.scrollTop = next;
      setScrollTop(next);
    };

    const loadMore = (): void => {
      if (pages.hasNextPage && !pages.isFetchingNextPage && !pages.isFetchNextPageError) {
        void pages.fetchNextPage();
      }
    };

    const moveTo = (index: number): void => {
      setActiveIndex(index);
      scrollToIndex(index);
    };

    // Keep the highlight inside the list, and move on into a page that just arrived.
    const previousCount = React.useRef(count);
    React.useEffect(() => {
      if (advanceRef.current && count > previousCount.current) {
        advanceRef.current = false;
        moveTo(Math.min(activeIndex + 1, count - 1));
      } else if (activeIndex >= count && count > 0) {
        setActiveIndex(count - 1);
      }
      previousCount.current = count;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the option count only
    }, [count]);

    const resetList = (): void => {
      setActiveIndex(0);
      setScrollTop(0);
      if (scrollRef.current !== null) scrollRef.current.scrollTop = 0;
    };

    // A new search starts at the top of its results.
    React.useEffect(() => {
      setActiveIndex(0);
      setScrollTop(0);
      if (scrollRef.current !== null) scrollRef.current.scrollTop = 0;
    }, [search]);

    const openPopover = (): void => {
      if (disabled) return;
      setInputText("");
      resetList();
      setOpen(true);
    };

    const closePopover = (): void => {
      setOpen(false);
      setInputText("");
      advanceRef.current = false;
    };

    const toggleOption = (item: OptionRow): void => {
      const optionId = idOf(item);
      setCache((previous) =>
        String(optionId) in previous ? previous : { ...previous, [String(optionId)]: item },
      );
      if (multiple) {
        const next = isSelected(optionId)
          ? selected.filter((sel) => String(sel) !== String(optionId))
          : [...selected, optionId];
        onChange([...next]);
      } else {
        onChange(optionId);
        closePopover();
      }
    };

    const removeValue = (sel: string | number): void => {
      onChange([...selected.filter((other) => String(other) !== String(sel))]);
      inputRef.current?.focus();
    };

    const clearSelection = (): void => {
      onChange(null);
      setInputText("");
      inputRef.current?.focus();
    };

    const single = !multiple && selected.length > 0 ? selected[0] : undefined;
    const singleState = single !== undefined ? stateOf(single) : undefined;
    const singleText = single !== undefined ? selectedText(single) : "";
    const inputValue = open ? inputText : multiple ? "" : singleText;

    const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
      const next = event.target.value;
      resetList();
      if (!open) {
        if (disabled) return;
        setOpen(true);
        // While closed the input showed the selected label; typing appends to
        // it, so strip the label prefix and keep only the fresh keystrokes.
        setInputText(
          singleText !== "" && next.startsWith(singleText) ? next.slice(singleText.length) : next,
        );
        return;
      }
      setInputText(next);
    };

    const rowsPerPage = Math.max(1, Math.floor(viewportHeight / rowHeight) - 1);

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
      if (disabled) return;
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          if (!open) openPopover();
          else if (count > 0) {
            if (activeIndex < count - 1) moveTo(activeIndex + 1);
            else if (hasMore) {
              advanceRef.current = true;
              loadMore();
            } else moveTo(0);
          }
          break;
        case "ArrowUp":
          event.preventDefault();
          if (!open) openPopover();
          else if (count > 0) {
            if (activeIndex > 0) moveTo(activeIndex - 1);
            else if (!hasMore) moveTo(count - 1);
          }
          break;
        case "Home":
          if (open && count > 0) {
            event.preventDefault();
            moveTo(0);
          }
          break;
        case "End":
          if (open && count > 0) {
            event.preventDefault();
            moveTo(count - 1);
            loadMore();
          }
          break;
        case "PageDown":
          if (open && count > 0) {
            event.preventDefault();
            const target = Math.min(count - 1, activeIndex + rowsPerPage);
            moveTo(target);
            if (target === count - 1) loadMore();
          }
          break;
        case "PageUp":
          if (open && count > 0) {
            event.preventDefault();
            moveTo(Math.max(0, activeIndex - rowsPerPage));
          }
          break;
        case "Enter":
          if (open) {
            // Inside an open list Enter chooses; it never submits the form.
            event.preventDefault();
            const item = options[activeIndex];
            if (item !== undefined) toggleOption(item);
          }
          break;
        case "Escape":
          if (open) {
            event.preventDefault();
            event.stopPropagation();
            closePopover();
          }
          break;
        case "Backspace":
          if (multiple && inputText === "" && selected.length > 0) {
            onChange([...selected.slice(0, -1)]);
          }
          break;
        case "Tab":
          if (open) closePopover();
          break;
        default:
          break;
      }
    };

    const handleBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
      const next = event.relatedTarget as Node | null;
      if (
        next !== null &&
        (rootRef.current?.contains(next) === true || contentRef.current?.contains(next) === true)
      ) {
        return;
      }
      if (open) closePopover();
      onBlur?.();
    };

    const handleScroll = (event: React.UIEvent<HTMLDivElement>): void => {
      const container = event.currentTarget;
      setScrollTop(container.scrollTop);
      const height = container.clientHeight > 0 ? container.clientHeight : viewportHeight;
      if (container.scrollTop + height >= count * rowHeight - rowHeight * 5) loadMore();
    };

    // --- what the list says ------------------------------------------------
    const firstLoad = pages.data === undefined && pages.error == null;
    const loadError = pages.data === undefined ? pages.error : null;
    const searching =
      searchable && (term !== debouncedTerm || (pages.isPlaceholderData && pages.isFetching));
    const loaded = loadedRows.length;
    const totalText = total !== undefined ? total.toLocaleString() : undefined;

    const emptyReason: ResourceSelectEmptyProps["reason"] | null =
      count > 0 || firstLoad || loadError != null || searching
        ? null
        : term !== ""
          ? searchable
            ? "no-match"
            : "no-loaded-match"
          : "none";
    const emptyProps: ResourceSelectEmptyProps | null =
      emptyReason !== null ? { reason: emptyReason, search: term, names, loaded } : null;

    const status = ((): string => {
      if (searching) return "Searching…";
      if (pages.isFetchingNextPage) return `Loading more ${names.plural}…`;
      if (!searchable) {
        if (term !== "") {
          return `Search isn't available for ${names.plural}: ${count.toLocaleString()} of the ${loaded.toLocaleString()} loaded match`;
        }
        if (hasMore) {
          return `Showing ${loaded.toLocaleString()}${totalText !== undefined ? ` of ${totalText}` : ""} — search isn't available, scroll for more`;
        }
        return `${loaded.toLocaleString()} ${loaded === 1 ? names.singular : names.plural}`;
      }
      if (hasMore) {
        return `Showing ${loaded.toLocaleString()}${totalText !== undefined ? ` of ${totalText}` : ""} — type to narrow`;
      }
      if (term !== "") {
        return `${count.toLocaleString()} ${count === 1 ? `${names.singular} matches` : `${names.plural} match`} “${term}”`;
      }
      return `${count.toLocaleString()} ${count === 1 ? names.singular : names.plural}`;
    })();

    const announcement = ((): string => {
      if (!open) return "";
      if (loadError != null) {
        return describeError(loadError, { action: "view", resource: names.plural }).title;
      }
      if (firstLoad) return `Loading ${names.plural}…`;
      if (emptyProps !== null) return emptyText(emptyProps);
      return status;
    })();

    const activeId =
      open && count > 0 && activeIndex < count && !firstLoad ? optionDomId(activeIndex) : undefined;
    const invalid = props["aria-invalid"] === true || props["aria-invalid"] === "true";

    const Option = slots.Option;
    const Chip = slots.Chip;
    const ListLoading = slots.Loading;
    const Empty = slots.Empty;
    const ListError = slots.Error;

    const listbox = (
      <div
        role="listbox"
        id={listboxId}
        aria-label={
          props["aria-labelledby"] === undefined
            ? (props["aria-label"] ?? capitalised(names.plural))
            : undefined
        }
        aria-labelledby={props["aria-labelledby"]}
        aria-multiselectable={multiple || undefined}
        aria-busy={firstLoad || searching || undefined}
        className={cn("p-1 transition-opacity", searching && "opacity-60")}
        style={
          virtual
            ? { paddingTop: start * rowHeight, paddingBottom: (count - end) * rowHeight }
            : undefined
        }
      >
        {options.slice(start, end).map((item, offset) => {
          const index = start + offset;
          const optionId = idOf(item);
          const optionSelected = isSelected(optionId);
          const active = index === activeIndex;
          return (
            <div
              key={String(optionId)}
              id={optionDomId(index)}
              role="option"
              aria-selected={optionSelected}
              aria-setsize={hasMore ? (total ?? -1) : count}
              aria-posinset={index + 1}
              data-highlighted={active ? "true" : undefined}
              className="flex h-8 cursor-default select-none items-center justify-between gap-2 rounded-sm px-2 text-sm outline-none data-[highlighted=true]:bg-accent data-[highlighted=true]:text-accent-foreground"
              onMouseDown={(event) => event.preventDefault()}
              onMouseMove={() => {
                if (!active) setActiveIndex(index);
              }}
              onClick={() => toggleOption(item)}
            >
              <Option item={item} label={labelOf(item)} selected={optionSelected} active={active} />
            </div>
          );
        })}
      </div>
    );

    const listBody = ((): React.ReactNode => {
      if (loadError != null) {
        return (
          <>
            <div className="p-1">
              <ListError
                error={loadError}
                context={{ action: "view", resource: names.plural }}
                onRetry={() => void pages.refetch()}
                retrying={pages.isFetching}
              />
            </div>
            {listbox}
          </>
        );
      }
      if (firstLoad) {
        return (
          <>
            <p
              className="border-b border-border px-3 py-1.5 text-xs text-muted-foreground"
              aria-hidden="true"
            >
              Loading {names.plural}…
            </p>
            <div className="p-1">
              <ListLoading rows={LOADING_ROWS} />
            </div>
            {listbox}
          </>
        );
      }
      return (
        <>
          {emptyProps === null ? (
            <p
              className="flex items-start gap-2 border-b border-border px-3 py-1.5 text-xs text-muted-foreground"
              aria-hidden="true"
            >
              {searching || pages.isFetchingNextPage ? (
                <SpinnerIcon className="mt-0.5 h-3 w-3 shrink-0 animate-spin" />
              ) : null}
              <span className="min-w-0">{status}</span>
            </p>
          ) : null}
          <div ref={scrollRef} className="max-h-64 overflow-y-auto" onScroll={handleScroll}>
            {emptyProps !== null ? <Empty {...emptyProps} /> : null}
            {listbox}
            {hasMore ? (
              <div className="px-1 pb-1">
                {pages.isFetchNextPageError ? (
                  <p className="flex h-8 items-center gap-2 px-2 text-xs text-muted-foreground">
                    <AlertIcon className="h-3 w-3 shrink-0 text-destructive" />
                    <span className="truncate">Couldn't load more {names.plural}.</span>
                    <button
                      type="button"
                      tabIndex={-1}
                      className="font-medium text-foreground underline underline-offset-4"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => void pages.fetchNextPage()}
                    >
                      Try again
                    </button>
                  </p>
                ) : (
                  <button
                    type="button"
                    tabIndex={-1}
                    disabled={pages.isFetchingNextPage}
                    className="flex h-8 w-full items-center justify-center gap-2 rounded-sm text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={loadMore}
                  >
                    {pages.isFetchingNextPage ? (
                      <>
                        <SpinnerIcon className="h-3 w-3 animate-spin" />
                        Loading more…
                      </>
                    ) : (
                      `Load more ${names.plural}`
                    )}
                  </button>
                )}
              </div>
            ) : null}
          </div>
        </>
      );
    })();

    return (
      <PopoverPrimitive.Root
        open={open}
        onOpenChange={(next) => {
          if (!next) closePopover();
        }}
        modal={false}
      >
        <PopoverPrimitive.Anchor asChild>
          <div
            ref={rootRef}
            onClick={() => {
              if (disabled) return;
              inputRef.current?.focus();
              if (!open) openPopover();
            }}
            onBlur={handleBlur}
            data-invalid={invalid ? "true" : undefined}
            className={cn(
              "relative flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 data-[invalid=true]:border-destructive data-[invalid=true]:focus-within:ring-destructive",
              disabled && "cursor-not-allowed opacity-50",
              className,
            )}
          >
            {multiple
              ? selected.map((sel) => {
                  const state = stateOf(sel);
                  const text = state === "loaded" ? selectedText(sel) : failedText(sel);
                  return (
                    <Chip
                      key={String(sel)}
                      label={state === "loaded" ? labelOf(rowFor(sel) ?? {}) : text}
                      state={state}
                      removeLabel={`Remove ${text}`}
                      onRemove={disabled ? undefined : () => removeValue(sel)}
                    />
                  );
                })
              : null}
            {singleState === "failed" && !open ? (
              <AlertIcon className="h-4 w-4 shrink-0 text-destructive" />
            ) : null}
            <input
              ref={setInputRef}
              id={inputId}
              type="text"
              role="combobox"
              aria-expanded={open}
              aria-controls={listboxId}
              aria-autocomplete="list"
              aria-activedescendant={activeId}
              aria-label={props["aria-label"]}
              aria-labelledby={props["aria-labelledby"]}
              aria-describedby={props["aria-describedby"]}
              aria-invalid={props["aria-invalid"]}
              aria-required={props["aria-required"]}
              autoComplete="off"
              disabled={disabled}
              placeholder={
                singleState === "loading"
                  ? `Loading ${names.singular}…`
                  : selected.length === 0
                    ? placeholder
                    : undefined
              }
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              onClick={() => {
                if (!open) openPopover();
              }}
              className={cn(
                "min-w-16 flex-1 bg-transparent outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed",
                singleState === "failed" && !open && "text-muted-foreground",
              )}
            />
            {clearable && selected.length > 0 && !disabled ? (
              <button
                type="button"
                aria-label="Clear selection"
                className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                onMouseDown={(event) => event.preventDefault()}
                onClick={(event) => {
                  event.stopPropagation();
                  clearSelection();
                }}
              >
                <ResourceSelectClearIcon className="h-4 w-4" />
              </button>
            ) : null}
            <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
            <span className="sr-only" role="status" aria-live="polite">
              {announcement}
            </span>
          </div>
        </PopoverPrimitive.Anchor>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            ref={contentRef}
            side="bottom"
            align="start"
            sideOffset={4}
            onOpenAutoFocus={(event) => event.preventDefault()}
            onCloseAutoFocus={(event) => event.preventDefault()}
            onInteractOutside={(event) => {
              const target = event.target;
              if (
                rootRef.current !== null &&
                target instanceof Node &&
                rootRef.current.contains(target)
              ) {
                event.preventDefault();
              }
            }}
            className="z-popover w-[var(--radix-popover-trigger-width)] min-w-48 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md"
          >
            {listBody}
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    );
  },
);
ResourceSelect.displayName = "ResourceSelect";
