import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as React from "react";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceList } from "../../../hooks/useResourceList";
import type { ResourceListParams } from "../../../hooks/types";
import { cn } from "../../../lib/cn";
import { CheckIcon, ChevronDownIcon } from "../../primitives/icons";
import { displayLabel } from "../displayLabel";
import { useDebouncedValue } from "./use-debounced-value";
import { registerComponentRole } from "../../../lib/roles";

registerComponentRole("async-select", "ResourceSelect");

type ResourceItemRecord = Record<string, unknown>;

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
  /** Page size for the option request (only the first page is fetched, D8). */
  pageSize?: number;
  /** Set false to hide the clear affordance (which emits null). Default true. */
  clearable?: boolean;
  /** Debounce for the ?search= request in ms. Default 300 (D8). */
  searchDebounceMs?: number;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}

function idOf(item: ResourceItemRecord): string | number {
  const value = item["id"];
  if (typeof value === "string" || typeof value === "number") return value;
  return String(value);
}

function optionDomId(listboxId: string, index: number): string {
  return `${listboxId}-option-${index}`;
}

function XIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
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
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/**
 * Searchable picker for a related row, querying the related resource as you type.
 *
 * Contract D8.
 *
 * A text input drives a debounced `?search=` list request; options render in
 * a NON-MODAL Radix Popover whose auto-focus is prevented so keyboard focus
 * never leaves the input. The input implements the ARIA 1.2 combobox pattern
 * (combobox → listbox with aria-activedescendant). Pre-selected ids that were
 * never seen in a result page are resolved through detail fetches, and the
 * clear affordance emits `null`.
 */
export function ResourceSelect(props: ResourceSelectProps): React.ReactElement {
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
  } = props;

  const reactId = React.useId();
  const inputId = id ?? reactId;
  const listboxId = `${inputId}-listbox`;

  const [open, setOpen] = React.useState(false);
  const [inputText, setInputText] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [cache, setCache] = React.useState<Record<string, ResourceItemRecord>>({});

  const rootRef = React.useRef<HTMLDivElement>(null);
  const contentRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const debouncedSearch = useDebouncedValue(inputText.trim(), searchDebounceMs);

  const selected: ReadonlyArray<string | number> = React.useMemo(() => {
    if (value == null) return [];
    return Array.isArray(value) ? value : [value as string | number];
  }, [value]);

  const listParams: ResourceListParams = React.useMemo(() => {
    const params: ResourceListParams = { page: 1 };
    if (pageSize !== undefined) params.pageSize = pageSize;
    if (debouncedSearch !== "") params.search = debouncedSearch;
    if (filter !== undefined) params.filters = filter;
    return params;
  }, [pageSize, debouncedSearch, filter]);

  const listQuery = useResourceList(resource, listParams, { enabled: open && !disabled });
  const results: readonly ResourceItemRecord[] = listQuery.data?.results ?? [];

  // Remember every row we have seen, so selected values can always be labelled.
  React.useEffect(() => {
    const rows = listQuery.data?.results;
    if (rows === undefined || rows.length === 0) return;
    setCache((previous) => {
      let changed = false;
      const next = { ...previous };
      for (const row of rows) {
        const key = String(idOf(row));
        if (!(key in next)) {
          next[key] = row;
          changed = true;
        }
      }
      return changed ? next : previous;
    });
  }, [listQuery.data]);

  // Pre-selected ids never seen in a result page are resolved one at a time
  // through the detail endpoint (D8 selected-id resolution).
  const unresolvedId = selected.find((sel) => !(String(sel) in cache));
  const itemQuery = useResourceItem(resource, unresolvedId ?? "", undefined, {
    enabled: unresolvedId !== undefined && !disabled,
    retry: false,
  });
  const resolvedItem = itemQuery.data;
  const resolveError = itemQuery.error;

  React.useEffect(() => {
    if (unresolvedId === undefined) return;
    if (resolvedItem !== undefined) {
      setCache((previous) => ({ ...previous, [String(unresolvedId)]: resolvedItem }));
    } else if (resolveError != null) {
      // Give up on this id (the raw id becomes its label) so resolution of any
      // remaining ids can continue instead of refetching forever.
      setCache((previous) => ({ ...previous, [String(unresolvedId)]: { id: unresolvedId } }));
    }
  }, [unresolvedId, resolvedItem, resolveError]);

  const labelOf = React.useCallback(
    (item: ResourceItemRecord): React.ReactNode =>
      getOptionLabel !== undefined ? getOptionLabel(item) : displayLabel(item),
    [getOptionLabel],
  );

  const textOf = React.useCallback(
    (sel: string | number): string => {
      const item = cache[String(sel)];
      if (item === undefined) return String(sel);
      const label = getOptionLabel !== undefined ? getOptionLabel(item) : displayLabel(item);
      if (typeof label === "string") return label;
      if (typeof label === "number") return String(label);
      return displayLabel(item);
    },
    [cache, getOptionLabel],
  );

  const openPopover = React.useCallback(() => {
    if (disabled) return;
    setInputText("");
    setActiveIndex(0);
    setOpen(true);
  }, [disabled]);

  const closePopover = React.useCallback(() => {
    setOpen(false);
    setInputText("");
  }, []);

  const isSelected = React.useCallback(
    (optionId: string | number): boolean =>
      selected.some((sel) => String(sel) === String(optionId)),
    [selected],
  );

  const toggleOption = (item: ResourceItemRecord): void => {
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

  const clearSelection = (): void => {
    onChange(null);
    setInputText("");
    inputRef.current?.focus();
  };

  const singleText = !multiple && selected.length > 0 ? textOf(selected[0]) : "";
  const inputValue = open ? inputText : multiple ? "" : singleText;

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const next = event.target.value;
    if (!open) {
      if (disabled) return;
      setActiveIndex(0);
      setOpen(true);
      // While closed the input showed the selected label; typing appends to
      // it, so strip the label prefix and keep only the fresh keystrokes.
      setInputText(
        singleText !== "" && next.startsWith(singleText) ? next.slice(singleText.length) : next,
      );
      return;
    }
    setActiveIndex(0);
    setInputText(next);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (disabled) return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!open) openPopover();
        else if (results.length > 0) setActiveIndex((index) => (index + 1) % results.length);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (!open) openPopover();
        else if (results.length > 0) {
          setActiveIndex((index) => (index - 1 + results.length) % results.length);
        }
        break;
      case "Enter":
        if (open) {
          event.preventDefault();
          const item = results[activeIndex];
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

  const handleBlur = (event: React.FocusEvent<HTMLInputElement>): void => {
    const next = event.relatedTarget as Node | null;
    if (
      next !== null &&
      (rootRef.current?.contains(next) === true || contentRef.current?.contains(next) === true)
    ) {
      return;
    }
    if (open) closePopover();
  };

  const listContent = ((): React.ReactNode => {
    if (listQuery.isLoading) {
      return <div className="px-2 py-1.5 text-sm text-muted-foreground">Loading…</div>;
    }
    if (listQuery.error != null) {
      return (
        <div role="alert" className="px-2 py-1.5 text-sm text-destructive">
          Failed to load options.
        </div>
      );
    }
    if (results.length === 0) {
      return <div className="px-2 py-1.5 text-sm text-muted-foreground">No results</div>;
    }
    return results.map((item, index) => {
      const optionId = idOf(item);
      const optionSelected = isSelected(optionId);
      return (
        <div
          key={String(optionId)}
          id={optionDomId(listboxId, index)}
          role="option"
          aria-selected={optionSelected}
          data-highlighted={index === activeIndex ? "true" : undefined}
          className="flex cursor-default select-none items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[highlighted=true]:bg-accent data-[highlighted=true]:text-accent-foreground"
          onMouseDown={(event) => event.preventDefault()}
          onMouseMove={() => setActiveIndex(index)}
          onClick={() => toggleOption(item)}
        >
          <span className="truncate">{labelOf(item)}</span>
          {optionSelected ? <CheckIcon className="h-4 w-4 shrink-0" /> : null}
        </div>
      );
    });
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
          className={cn(
            "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2",
            disabled && "cursor-not-allowed opacity-50",
            className,
          )}
        >
          {multiple
            ? selected.map((sel) => {
                const chipText = textOf(sel);
                return (
                  <span
                    key={String(sel)}
                    className="inline-flex items-center gap-1 rounded-sm bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground"
                  >
                    {chipText}
                    {!disabled ? (
                      <button
                        type="button"
                        aria-label={`Remove ${chipText}`}
                        className="rounded-sm opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        onClick={(event) => {
                          event.stopPropagation();
                          onChange([...selected.filter((other) => String(other) !== String(sel))]);
                        }}
                      >
                        <XIcon className="h-3 w-3" />
                      </button>
                    ) : null}
                  </span>
                );
              })
            : null}
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={listboxId}
            aria-autocomplete="list"
            aria-activedescendant={
              open && results.length > 0 ? optionDomId(listboxId, activeIndex) : undefined
            }
            aria-label={props["aria-label"]}
            aria-labelledby={props["aria-labelledby"]}
            autoComplete="off"
            disabled={disabled}
            placeholder={selected.length === 0 ? placeholder : undefined}
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onClick={() => {
              if (!open) openPopover();
            }}
            onBlur={handleBlur}
            className="min-w-16 flex-1 bg-transparent outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
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
              <XIcon className="h-4 w-4" />
            </button>
          ) : null}
          <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
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
          className="z-50 max-h-72 w-[var(--radix-popover-trigger-width)] min-w-[12rem] overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <div role="listbox" id={listboxId} aria-multiselectable={multiple || undefined}>
            {listContent}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
