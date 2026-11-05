/**
 * <Accordion>: sections that open and close, after the WAI-ARIA accordion pattern.
 *
 * Experimental. Each item is a heading holding a button and a region the
 * button controls. The button says whether its region is open
 * (`aria-expanded`), and the region is named by its heading. Enter and Space
 * open and close (the native button), Down and Up move between the headers,
 * Home and End go to the first and the last. A closed region is `hidden`, so
 * neither the tab order nor a screen reader reaches inside it.
 *
 * `type="multiple"` (the default) lets any number be open. `type="single"`
 * keeps one open at a time, and `collapsible={false}` keeps that one open.
 *
 * Escape hatches: `open` and `onOpenChange` control it from outside, every
 * item may carry its own `className`, `slots.Trigger` replaces how a header
 * reads, `headingLevel` fits it into the page's outline, and `className`
 * merges on the root.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { ChevronDownIcon, ChevronUpIcon } from "../primitives/icons";

registerComponentRole("accordion", "Accordion");

export interface AccordionItem {
  /** Stable and unique within the accordion: what `open` and `defaultOpen` list. */
  id: string;
  /** The header's text. */
  title: React.ReactNode;
  /** The region shown while the item is open. */
  content: React.ReactNode;
  /** The header cannot be toggled. */
  disabled?: boolean;
  className?: string;
}

/** What the `Trigger` slot receives: the content of one header's button. */
export interface AccordionTriggerProps {
  item: AccordionItem;
  open: boolean;
}

export interface AccordionSlots {
  /** The inside of a header's button (the button itself stays the accordion's). */
  Trigger: React.ComponentType<AccordionTriggerProps>;
}

export interface AccordionProps extends Omit<
  React.HTMLAttributes<HTMLDivElement>,
  "defaultValue" | "onChange"
> {
  items: readonly AccordionItem[];
  /** `"multiple"` (default): any number open. `"single"`: one at a time. */
  type?: "single" | "multiple";
  /** With `type="single"`: whether the open item can be closed (default true). */
  collapsible?: boolean;
  /** The ids open at first (uncontrolled). */
  defaultOpen?: readonly string[];
  /** The ids open now (controlled, with `onOpenChange`). */
  open?: readonly string[];
  onOpenChange?: (open: string[]) => void;
  /** The level of the item headings (default 3). */
  headingLevel?: 2 | 3 | 4 | 5 | 6;
  slots?: Partial<AccordionSlots>;
}

function DefaultTrigger({ item, open }: AccordionTriggerProps): React.ReactElement {
  const Icon = open ? ChevronUpIcon : ChevronDownIcon;
  return (
    <>
      <span className="min-w-0 flex-1">{item.title}</span>
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
    </>
  );
}

/** The accordion's default slots, exported so a project can wrap one. */
export const defaultAccordionSlots: AccordionSlots = { Trigger: DefaultTrigger };

const HEADINGS = { 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" } as const;

/** The ids open after `id` was toggled, by the accordion's rules. */
export function toggleAccordion(
  current: readonly string[],
  id: string,
  type: "single" | "multiple",
  collapsible: boolean,
): string[] {
  const isOpen = current.includes(id);
  if (type === "single") {
    if (isOpen) return collapsible ? [] : [...current];
    return [id];
  }
  return isOpen ? current.filter((value) => value !== id) : [...current, id];
}

/** Experimental. Sections that open and close (the WAI-ARIA accordion pattern). */
export const Accordion = React.forwardRef<HTMLDivElement, AccordionProps>(
  (
    {
      items,
      type = "multiple",
      collapsible = true,
      defaultOpen,
      open: controlled,
      onOpenChange,
      headingLevel = 3,
      slots,
      className,
      ...props
    },
    ref,
  ) => {
    const Slots: AccordionSlots = { ...defaultAccordionSlots, ...slots };
    const [uncontrolled, setUncontrolled] = React.useState<readonly string[]>(
      () => defaultOpen ?? [],
    );
    const open = controlled ?? uncontrolled;
    const baseId = React.useId();
    const buttons = React.useRef<Array<HTMLButtonElement | null>>([]);
    const Heading = HEADINGS[headingLevel];

    const toggle = (id: string): void => {
      const next = toggleAccordion(open, id, type, collapsible);
      if (controlled === undefined) setUncontrolled(next);
      onOpenChange?.(next);
    };

    const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number): void => {
      const enabled = items
        .map((item, position) => (item.disabled ? -1 : position))
        .filter((position) => position >= 0);
      const at = enabled.indexOf(index);
      let target: number | undefined;
      if (event.key === "ArrowDown") target = enabled[(at + 1) % enabled.length];
      else if (event.key === "ArrowUp")
        target = enabled[(at - 1 + enabled.length) % enabled.length];
      else if (event.key === "Home") target = enabled[0];
      else if (event.key === "End") target = enabled[enabled.length - 1];
      if (target === undefined) return;
      event.preventDefault();
      buttons.current[target]?.focus();
    };

    return (
      <div ref={ref} className={cn("rounded-lg border border-border", className)} {...props}>
        {items.map((item, index) => {
          const isOpen = open.includes(item.id);
          const buttonId = `${baseId}-trigger-${index}`;
          const panelId = `${baseId}-panel-${index}`;
          const locked = type === "single" && !collapsible && isOpen;
          return (
            <div
              key={item.id}
              data-state={isOpen ? "open" : "closed"}
              className={cn("border-b border-border last:border-b-0", item.className)}
            >
              <Heading className="text-sm font-medium">
                <button
                  ref={(element) => {
                    buttons.current[index] = element;
                  }}
                  id={buttonId}
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  aria-disabled={locked || undefined}
                  disabled={item.disabled}
                  onClick={() => toggle(item.id)}
                  onKeyDown={(event) => onKeyDown(event, index)}
                  className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-muted-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Slots.Trigger item={item} open={isOpen} />
                </button>
              </Heading>
              <div
                id={panelId}
                role="region"
                aria-labelledby={buttonId}
                hidden={!isOpen}
                className="px-4 pb-4 text-sm"
              >
                {item.content}
              </div>
            </div>
          );
        })}
      </div>
    );
  },
);
Accordion.displayName = "Accordion";
