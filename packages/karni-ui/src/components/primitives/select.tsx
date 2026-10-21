import * as SelectPrimitive from "@radix-ui/react-select";
import * as React from "react";
import { cn } from "../../lib/cn";
import { overridableSelectPart } from "../../primitives/registry";
import { CheckIcon, ChevronDownIcon, ChevronUpIcon } from "./icons";

/**
 * The value that stands for "nothing selected" inside Radix Select, which reserves the empty string.
 *
 * This package maps the empty state through this sentinel at the component boundary (contract D8). Consumers of
 * the composed <Select> never see it: `value`/`onValueChange` use `null`.
 */
export const KARNI_SELECT_EMPTY = "__karni_empty__";

// ---------------------------------------------------------------------------
// Low-level styled Radix parts (escape hatch for fully custom selects)
// ---------------------------------------------------------------------------

/** Radix Select root, for composing a custom select from the styled parts. */
export const SelectRoot = overridableSelectPart("Root", SelectPrimitive.Root);
/** Groups related options inside `SelectContent`. */
export const SelectGroup = overridableSelectPart("Group", SelectPrimitive.Group);
/** Shows the selected option's label inside `SelectTrigger`. */
export const SelectValue = overridableSelectPart("Value", SelectPrimitive.Value);

const KarniSelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
KarniSelectTrigger.displayName = "SelectTrigger";

/** The styled button that opens the select.
 *
 * Part of the `select` family a project can replace (`primitives={{ select: ... }}` on KarniProvider).
 */
export const SelectTrigger = overridableSelectPart("Trigger", KarniSelectTrigger);

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronUpIcon className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = "SelectScrollUpButton";

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronDownIcon className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = "SelectScrollDownButton";

const KarniSelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      className={cn(
        "relative z-popover max-h-96 min-w-32 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md",
        position === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className,
      )}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-1",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]",
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
KarniSelectContent.displayName = "SelectContent";

/** The styled dropdown panel that lists the options.
 *
 * Part of the `select` family a project can replace (`primitives={{ select: ... }}` on KarniProvider).
 */
export const SelectContent = overridableSelectPart("Content", KarniSelectContent);

const KarniSelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("py-1.5 pl-8 pr-2 text-sm font-semibold", className)}
    {...props}
  />
));
KarniSelectLabel.displayName = "SelectLabel";

/** A heading inside a `SelectGroup`.
 *
 * Part of the `select` family a project can replace (`primitives={{ select: ... }}` on KarniProvider).
 */
export const SelectLabel = overridableSelectPart("Label", KarniSelectLabel);

const KarniSelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <CheckIcon className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
KarniSelectItem.displayName = "SelectItem";

/** One selectable option; `value` is what the select reports.
 *
 * Part of the `select` family a project can replace (`primitives={{ select: ... }}` on KarniProvider).
 */
export const SelectItem = overridableSelectPart("Item", KarniSelectItem);

const KarniSelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-muted", className)}
    {...props}
  />
));
KarniSelectSeparator.displayName = "SelectSeparator";

/** A divider line between option groups.
 *
 * Part of the `select` family a project can replace (`primitives={{ select: ... }}` on KarniProvider).
 */
export const SelectSeparator = overridableSelectPart("Separator", KarniSelectSeparator);

// ---------------------------------------------------------------------------
// Composed, options-driven Select (what ResourceForm / the filter bar use)
// ---------------------------------------------------------------------------

export interface SelectOption {
  /** Must be non-empty and not the reserved sentinel. */
  value: string;
  label: React.ReactNode;
  disabled?: boolean;
}

export interface SelectProps {
  /** `null`/`""`/`undefined` all mean "no selection". */
  value: string | null | undefined;
  /** Receives `null` when the clear item is chosen, else the option value. */
  onValueChange?: (value: string | null) => void;
  options: readonly SelectOption[];
  placeholder?: React.ReactNode;
  /**
   * Renders a clear item at the top of the list (contract D8): pass it for
   * nullable fields (label "—" by default) and filter contexts (e.g. "All").
   * Choosing it emits `null`.
   */
  clearable?: boolean;
  clearLabel?: React.ReactNode;
  disabled?: boolean;
  /** Forwarded to the hidden native select for HTML form submission. */
  name?: string;
  id?: string;
  /** Merged onto the trigger. */
  className?: string;
  contentClassName?: string;
  "aria-label"?: string;
  /** Extra <SelectItem>/<SelectGroup> nodes appended after `options` (escape hatch). */
  children?: React.ReactNode;
}

/**
 * Styled select for a list of `options`, with `null` for no selection. Maps the
 * empty state through the KARNI_SELECT_EMPTY sentinel so `""` never reaches
 * Radix (D8). For fully custom composition use SelectRoot/SelectTrigger/
 * SelectContent/SelectItem directly.
 */
export const Select = React.forwardRef<HTMLButtonElement, SelectProps>((props, ref) => {
  const {
    value,
    onValueChange,
    options,
    placeholder,
    clearable = false,
    clearLabel = "—",
    disabled,
    name,
    id,
    className,
    contentClassName,
    children,
    "aria-label": ariaLabel,
  } = props;

  const safeOptions = React.useMemo(() => {
    const filtered = options.filter(
      (option) => option.value !== "" && option.value !== KARNI_SELECT_EMPTY,
    );
    if (filtered.length !== options.length) {
      console.warn(
        `[karni-ui] <Select> option values "" and "${KARNI_SELECT_EMPTY}" are reserved; those options were dropped. Use the \`clearable\` prop for an empty choice.`,
      );
    }
    return filtered;
  }, [options]);

  const isEmpty = value == null || value === "";
  // With a clear item present, the sentinel is a real Radix value, so the
  // trigger shows the clear label and the item renders checked. Without one,
  // "" makes Radix show the placeholder.
  const radixValue = isEmpty ? (clearable ? KARNI_SELECT_EMPTY : "") : value;

  const handleValueChange = React.useCallback(
    (next: string) => {
      onValueChange?.(next === KARNI_SELECT_EMPTY ? null : next);
    },
    [onValueChange],
  );

  return (
    <SelectRoot
      value={radixValue}
      onValueChange={handleValueChange}
      disabled={disabled}
      name={name}
    >
      <SelectTrigger ref={ref} id={id} className={className} aria-label={ariaLabel}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className={contentClassName}>
        {clearable ? (
          <SelectItem value={KARNI_SELECT_EMPTY} className="text-muted-foreground">
            {clearLabel}
          </SelectItem>
        ) : null}
        {safeOptions.map((option) => (
          <SelectItem key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </SelectItem>
        ))}
        {children}
      </SelectContent>
    </SelectRoot>
  );
});
Select.displayName = "Select";
