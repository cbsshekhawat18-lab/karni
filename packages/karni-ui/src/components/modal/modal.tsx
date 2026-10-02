import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("modal", "Modal");

type IconProps = React.SVGAttributes<SVGSVGElement>;

function CloseIcon(props: IconProps): React.ReactElement {
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
 * Escape hatch for footer buttons: any element wrapped in <ModalClose asChild>
 * closes the modal on click (re-exported Radix Dialog.Close).
 */
export const ModalClose = DialogPrimitive.Close;

export interface ModalProps {
  /** Dialog title — always rendered (Radix requires it for accessibility). */
  title: React.ReactNode;
  /** Optional description under the title, linked via aria-describedby. */
  description?: React.ReactNode;
  /** Body content. */
  children?: React.ReactNode;
  /** Footer slot (actions row). Use <ModalClose asChild> for cancel buttons. */
  footer?: React.ReactNode;
  /**
   * Uncontrolled usage: a node (usually a Button) that opens the modal,
   * rendered through Radix `asChild`.
   */
  trigger?: React.ReactNode;
  /** Controlled open state (pair with onOpenChange). */
  open?: boolean;
  /** Initial state for uncontrolled usage. */
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Hides the top-right X button. */
  hideCloseButton?: boolean;
  /** Extra classes for the content panel. */
  className?: string;
  /**
   * Escape hatch: props spread onto Radix Dialog.Content
   * (onEscapeKeyDown, onInteractOutside, …).
   */
  contentProps?: Omit<
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>,
    "children" | "className"
  >;
}

/**
 * Themed Radix Dialog. Works controlled (`open` + `onOpenChange`) or
 * uncontrolled via the `trigger` slot; `footer` is the actions row.
 *
 * Escape hatches: `contentProps` reaches the Radix content part, `className`
 * restyles the panel, `hideCloseButton` drops the X, and `ModalClose` lets any
 * footer element close the dialog.
 */
export function Modal({
  title,
  description,
  children,
  footer,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
  hideCloseButton = false,
  className,
  contentProps,
}: ModalProps): React.ReactElement {
  // Without a Description part, Radix warns unless aria-describedby is
  // explicitly cleared; with one (or a consumer-supplied id) leave the key
  // alone so the automatic wiring stands.
  const clearDescribedBy =
    description == null && contentProps?.["aria-describedby"] === undefined
      ? { "aria-describedby": undefined }
      : {};
  return (
    <DialogPrimitive.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      {trigger != null && <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-foreground/40" />
        <DialogPrimitive.Content
          {...contentProps}
          {...clearDescribedBy}
          className={cn(
            "fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border border-border bg-background p-6 text-foreground shadow-lg",
            className,
          )}
        >
          <div className="grid gap-1.5">
            <DialogPrimitive.Title className="text-lg font-semibold leading-none tracking-tight">
              {title}
            </DialogPrimitive.Title>
            {description != null && (
              <DialogPrimitive.Description className="text-sm text-muted-foreground">
                {description}
              </DialogPrimitive.Description>
            )}
          </div>
          {children}
          {footer != null && (
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{footer}</div>
          )}
          {!hideCloseButton && (
            <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm text-muted-foreground opacity-70 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none">
              <CloseIcon className="h-4 w-4" />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
