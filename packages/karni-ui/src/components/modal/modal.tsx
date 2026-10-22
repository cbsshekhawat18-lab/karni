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
 * Escape hatch for footer buttons: any element wrapped in
 * `<ModalClose asChild>` closes the modal on click (re-exported Radix
 * Dialog.Close).
 */
export const ModalClose = DialogPrimitive.Close;

/**
 * The modal's title: names the dialog (aria-labelledby). A custom `Header`
 * slot renders it so the dialog stays labelled.
 */
export const ModalTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight", className)}
    {...props}
  />
));
ModalTitle.displayName = "ModalTitle";

/** The modal's description: describes the dialog (aria-describedby). */
export const ModalDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
ModalDescription.displayName = "ModalDescription";

/** What the `Header` slot receives. Render ModalTitle (and ModalDescription) inside it. */
export interface ModalHeaderProps {
  title: React.ReactNode;
  /** The `description` prop, or undefined. */
  description?: React.ReactNode;
}

/** What the `Footer` slot receives: the `footer` prop. */
export interface ModalFooterProps {
  children: React.ReactNode;
}

/** What the `CloseButton` slot receives. Wrap your button in <ModalClose asChild>. */
export interface ModalCloseButtonProps {
  /** Its accessible name ("Close"). */
  label: string;
}

/** The parts of the dialog a project can replace (`slots={{ Footer: StickyFooter }}`). */
export interface ModalSlots {
  /** Title and description; must render ModalTitle. */
  Header: React.ComponentType<ModalHeaderProps>;
  /** The actions row. */
  Footer: React.ComponentType<ModalFooterProps>;
  /** The top-right close button; must close through ModalClose. */
  CloseButton: React.ComponentType<ModalCloseButtonProps>;
}

function DefaultHeader({ title, description }: ModalHeaderProps): React.ReactElement {
  return (
    <div className="grid gap-1.5">
      <ModalTitle>{title}</ModalTitle>
      {description != null && <ModalDescription>{description}</ModalDescription>}
    </div>
  );
}

function DefaultFooter({ children }: ModalFooterProps): React.ReactElement {
  return <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{children}</div>;
}

function DefaultCloseButton({ label }: ModalCloseButtonProps): React.ReactElement {
  return (
    <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none">
      <CloseIcon className="h-4 w-4" />
      <span className="sr-only">{label}</span>
    </DialogPrimitive.Close>
  );
}

/** The default pieces of the dialog, for wrapping one. */
export const defaultModalSlots: ModalSlots = {
  Header: DefaultHeader,
  Footer: DefaultFooter,
  CloseButton: DefaultCloseButton,
};

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
  /** Replaces the Header, Footer or CloseButton; see ModalSlots. */
  slots?: Partial<ModalSlots>;
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
 * uncontrolled via the `trigger` slot, and `footer` is the actions row.
 *
 * Keyboard and screen readers: the dialog is named by its title and
 * described by its description; focus moves into it on open, Tab stays
 * inside, Escape closes, and focus returns to what opened it.
 *
 * Escape hatches: `slots` replaces the Header, Footer or CloseButton,
 * `contentProps` reaches the Radix content part, `className` restyles the
 * panel, `hideCloseButton` drops the X, and `ModalClose` lets any footer
 * element close the dialog.
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
  slots,
  className,
  contentProps,
}: ModalProps): React.ReactElement {
  const { Header, Footer, CloseButton } = { ...defaultModalSlots, ...slots };
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
        <DialogPrimitive.Overlay className="fixed inset-0 z-modal bg-overlay" />
        <DialogPrimitive.Content
          {...contentProps}
          {...clearDescribedBy}
          className={cn(
            // Centred, with a gutter on phones: inset-x-4 + mx-auto under max-w-128.
            // Never taller than the viewport (a phone on its side, an open
            // keyboard): it scrolls inside, since the page behind is locked.
            "fixed inset-x-4 top-1/2 z-modal mx-auto grid max-h-full max-w-128 -translate-y-1/2 gap-4 overflow-y-auto rounded-lg border border-border bg-background p-6 text-foreground shadow-lg",
            className,
          )}
        >
          <Header title={title} description={description ?? undefined} />
          {children}
          {footer != null && <Footer>{footer}</Footer>}
          {!hideCloseButton && <CloseButton label="Close" />}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
