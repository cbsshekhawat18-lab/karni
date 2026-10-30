import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as React from "react";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { AlertIcon, ChevronDownIcon } from "../../primitives/icons";
import { displayLabel } from "../displayLabel";
import { resourceNames, type ResourceLabel } from "../resource-names";
import {
  defaultResourceSelectSlots,
  ResourceSelectClearIcon,
  type ResourceSelectChipProps,
} from "../select/select-states";
import { useSelectedRows, type OptionRow } from "../select/use-option-pages";
import type { TreeViewSlots } from "./tree-states";
import { TreeView } from "./TreeView";

registerComponentRole("tree-select", "TreeSelect");

/** Experimental. TreeSelect's replaceable parts. */
export interface TreeSelectSlots {
  /** One selected value in `multiple` mode (ResourceSelect's chip by default). */
  Chip: React.ComponentType<ResourceSelectChipProps>;
}

export interface TreeSelectProps {
  /** The tree resource the value points at: "regions". */
  resource: string;
  value: string | number | ReadonlyArray<string | number> | null;
  onChange: (value: string | number | Array<string | number> | null) => void;
  multiple?: boolean;
  disabled?: boolean;
  /** Shown while nothing is chosen. Default "Choose a <node>" ("Add <nodes>" with `multiple`). */
  placeholder?: string;
  /** Defaults to displayLabel(). */
  getOptionLabel?: (item: Record<string, unknown>) => React.ReactNode;
  /** Levels the tree loads per request. Default 2. */
  depth?: number;
  /** Set false to hide the clear button (which emits null). Default true. */
  clearable?: boolean;
  id?: string;
  className?: string;
  /** How the resource is named in messages. Default: derived from `resource`. */
  resourceLabel?: ResourceLabel;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  /** Ids of the help text and error message that describe the field. */
  "aria-describedby"?: string;
  /** Marks the field invalid (destructive border). */
  "aria-invalid"?: boolean | "true" | "false";
  /**
   * Accepted for the form's sake but not set: the picker is a button, which
   * cannot carry aria-required. ResourceForm says "required" in the label.
   */
  "aria-required"?: boolean | "true" | "false";
  /** Called when focus leaves the picker (not when it moves into its tree). */
  onBlur?: () => void;
  /** Replaces the chip. */
  slots?: Partial<TreeSelectSlots>;
  /** Replaces parts of the tree in the popover (Node, Loading, Empty, Error). */
  treeSlots?: Partial<TreeViewSlots>;
}

function shortId(id: string | number): string {
  const text = String(id);
  return text.length > 12 ? `${text.slice(0, 8)}…` : text;
}

/**
 * Experimental. A picker for a relation that points at a tree resource.
 *
 * A button opens a popover with a TreeView (lazy branches, search, the
 * keyboard pattern), opened at the chosen node. Enter, Space or a click
 * chooses a node: one closes the popover, `multiple` toggles and keeps it
 * open. Chosen values show as the button's text, or as removable chips with
 * `multiple`. A preselected id is labelled from its detail endpoint, and one
 * that cannot be loaded says so. ResourceForm uses it for every FK or M2M
 * whose schema carries `x-karni-tree`.
 */
export const TreeSelect = React.forwardRef<HTMLButtonElement, TreeSelectProps>(
  function TreeSelect(props, forwardedRef): React.ReactElement {
    const {
      resource,
      value,
      onChange,
      multiple = false,
      disabled = false,
      placeholder,
      getOptionLabel,
      depth,
      clearable = true,
      id,
      className,
      resourceLabel,
      onBlur,
      slots: slotOverrides,
      treeSlots,
    } = props;
    const Chip = slotOverrides?.Chip ?? defaultResourceSelectSlots.Chip;
    const names = resourceNames(resource, resourceLabel);
    const reactId = React.useId();
    const buttonId = id ?? `${reactId}-button`;
    const valueId = `${reactId}-value`;
    const nameId = `${reactId}-name`;
    const treeId = `${reactId}-tree`;
    const [open, setOpen] = React.useState(false);
    const [cache, setCache] = React.useState<Record<string, OptionRow>>({});
    const rootRef = React.useRef<HTMLDivElement>(null);
    const contentRef = React.useRef<HTMLDivElement>(null);
    const buttonRef = React.useRef<HTMLButtonElement | null>(null);
    const setButtonRef = React.useCallback(
      (element: HTMLButtonElement | null) => {
        buttonRef.current = element;
        if (typeof forwardedRef === "function") forwardedRef(element);
        else if (forwardedRef !== null) forwardedRef.current = element;
      },
      [forwardedRef],
    );

    const selected: ReadonlyArray<string | number> = React.useMemo(() => {
      if (value === null || value === undefined) return [];
      return Array.isArray(value) ? value : [value as string | number];
    }, [value]);
    const selectedKey = selected.map(String).join("\u0000");
    const cacheRef = React.useRef(cache);
    cacheRef.current = cache;
    const toResolve = React.useMemo(
      () => selected.filter((sel) => !(String(sel) in cacheRef.current)),
      // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the value, read from the cache at that moment
      [selectedKey],
    );
    const resolution = useSelectedRows(resource, toResolve, { enabled: true });

    const labelOf = (item: OptionRow): React.ReactNode =>
      getOptionLabel !== undefined ? getOptionLabel(item) : displayLabel(item);
    const rowFor = (sel: string | number): OptionRow | undefined =>
      cache[String(sel)] ?? resolution.rows[String(sel)];
    const stateOf = (sel: string | number): "loaded" | "loading" | "failed" => {
      if (rowFor(sel) !== undefined) return "loaded";
      return resolution.failed.has(String(sel)) ? "failed" : "loading";
    };
    const failedText = (sel: string | number): string =>
      `Couldn't load ${names.singular} ${shortId(sel)}`;
    const textOf = (sel: string | number): string => {
      const row = rowFor(sel);
      if (row === undefined) return failedText(sel);
      const label = labelOf(row);
      return typeof label === "string" || typeof label === "number"
        ? String(label)
        : displayLabel(row);
    };

    const single = !multiple && selected.length > 0 ? selected[0] : undefined;
    const singleState = single !== undefined ? stateOf(single) : undefined;
    const buttonText = ((): React.ReactNode => {
      if (single !== undefined) {
        if (singleState === "loading") return `Loading ${names.singular}…`;
        const row = rowFor(single);
        return row !== undefined ? labelOf(row) : failedText(single);
      }
      return placeholder ?? (multiple ? `Add ${names.plural}` : `Choose a ${names.singular}`);
    })();
    const empty = single === undefined;

    const closeAndReturn = (): void => {
      setOpen(false);
      buttonRef.current?.focus();
    };

    const handleChange = (
      next: string | number | Array<string | number> | null,
      node: Record<string, unknown>,
    ): void => {
      const key = String(node["id"]);
      setCache((previous) => (key in previous ? previous : { ...previous, [key]: node }));
      onChange(next);
      if (!multiple) closeAndReturn();
    };

    const removeValue = (sel: string | number): void => {
      onChange([...selected.filter((other) => String(other) !== String(sel))]);
      buttonRef.current?.focus();
    };

    const handleBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
      const next = event.relatedTarget as Node | null;
      if (
        next !== null &&
        (rootRef.current?.contains(next) === true || contentRef.current?.contains(next) === true)
      ) {
        return;
      }
      if (!open) onBlur?.();
    };

    const invalid = props["aria-invalid"] === true || props["aria-invalid"] === "true";
    const labelledBy =
      props["aria-labelledby"] !== undefined
        ? `${props["aria-labelledby"]} ${valueId}`
        : props["aria-label"] !== undefined
          ? `${nameId} ${valueId}`
          : undefined;
    const treeLabel =
      props["aria-label"] ?? names.plural.charAt(0).toUpperCase() + names.plural.slice(1);

    return (
      <PopoverPrimitive.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) onBlur?.();
        }}
        modal={false}
      >
        <PopoverPrimitive.Anchor asChild>
          <div
            ref={rootRef}
            onBlur={handleBlur}
            data-invalid={invalid ? "true" : undefined}
            className={cn(
              "relative flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 data-[invalid=true]:border-destructive data-[invalid=true]:focus-within:ring-destructive",
              disabled && "cursor-not-allowed opacity-50",
              className,
            )}
          >
            {props["aria-label"] !== undefined ? (
              <span id={nameId} hidden>
                {props["aria-label"]}
              </span>
            ) : null}
            {multiple
              ? selected.map((sel) => {
                  const state = stateOf(sel);
                  const text = textOf(sel);
                  const row = rowFor(sel);
                  return (
                    <Chip
                      key={String(sel)}
                      label={state === "loaded" && row !== undefined ? labelOf(row) : text}
                      state={state}
                      removeLabel={`Remove ${text}`}
                      onRemove={disabled ? undefined : () => removeValue(sel)}
                    />
                  );
                })
              : null}
            {singleState === "failed" ? (
              <AlertIcon className="h-4 w-4 shrink-0 text-destructive" />
            ) : null}
            <PopoverPrimitive.Trigger asChild>
              <button
                ref={setButtonRef}
                id={buttonId}
                type="button"
                disabled={disabled}
                aria-haspopup="tree"
                aria-expanded={open}
                aria-controls={open ? treeId : undefined}
                aria-labelledby={labelledBy}
                aria-describedby={props["aria-describedby"]}
                aria-invalid={props["aria-invalid"]}
                className="flex min-w-16 flex-1 items-center justify-between gap-2 text-left outline-none disabled:cursor-not-allowed"
              >
                <span
                  id={valueId}
                  className={cn(
                    "min-w-0 truncate",
                    (empty || singleState === "failed") && "text-muted-foreground",
                  )}
                >
                  {buttonText}
                </span>
                <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
              </button>
            </PopoverPrimitive.Trigger>
            {clearable && !multiple && selected.length > 0 && !disabled ? (
              <button
                type="button"
                aria-label="Clear selection"
                className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                onClick={() => {
                  onChange(null);
                  buttonRef.current?.focus();
                }}
              >
                <ResourceSelectClearIcon className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </PopoverPrimitive.Anchor>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            ref={contentRef}
            side="bottom"
            align="start"
            sideOffset={4}
            aria-label={`Choose ${multiple ? names.plural : `a ${names.singular}`}`}
            onOpenAutoFocus={(event) => event.preventDefault()}
            className="z-popover w-[var(--radix-popover-trigger-width)] min-w-64 rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-md"
          >
            <TreeView
              id={treeId}
              resource={resource}
              value={value}
              onChange={handleChange}
              multiple={multiple}
              depth={depth}
              reveal={single ?? null}
              autoFocus
              getNodeLabel={getOptionLabel}
              resourceLabel={resourceLabel}
              slots={treeSlots}
              aria-label={treeLabel}
            />
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    );
  },
);
TreeSelect.displayName = "TreeSelect";
