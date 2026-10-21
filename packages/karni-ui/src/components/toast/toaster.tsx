import * as ToastPrimitive from "@radix-ui/react-toast";
import * as React from "react";
import { cn } from "../../lib/cn";
import { variants, type VariantProps } from "../../lib/variants";
import { dismissToast, type ToastVariant } from "./toast-store";
import { useToast } from "./use-toast";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("toast", "Toaster");

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
 * Per-variant toast styling — colors resolve through --karni-* tokens only
 * (success leans on primary, error on destructive, info on muted).
 */
export const toastVariants = variants({
  base: "pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-md border p-4 pr-8 shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  variants: {
    variant: {
      default: "border-border bg-background text-foreground",
      success: "border-primary bg-background text-foreground",
      error: "border-destructive bg-destructive text-destructive-foreground",
      info: "border-border bg-muted text-foreground",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

export type ToastVariantProps = VariantProps<typeof toastVariants>;

/** What the `Title` and `Description` slots receive. */
export interface ToasterSlotProps {
  children: React.ReactNode;
  variant: ToastVariant;
}

/** What the `CloseButton` slot receives. */
export interface ToasterCloseButtonProps {
  /** Its accessible name ("Dismiss"). */
  label: string;
  variant: ToastVariant;
  /** Removes the toast. */
  dismiss: () => void;
}

/** The parts of each toast a project can replace (`slots={{ CloseButton: MyClose }}`). */
export interface ToasterSlots {
  Title: React.ComponentType<ToasterSlotProps>;
  Description: React.ComponentType<ToasterSlotProps>;
  /** The top-right dismiss button. */
  CloseButton: React.ComponentType<ToasterCloseButtonProps>;
}

function DefaultTitle({ children }: ToasterSlotProps): React.ReactElement {
  return <ToastPrimitive.Title className="text-sm font-semibold">{children}</ToastPrimitive.Title>;
}

function DefaultDescription({ children }: ToasterSlotProps): React.ReactElement {
  return (
    <ToastPrimitive.Description className="text-sm opacity-90">
      {children}
    </ToastPrimitive.Description>
  );
}

function DefaultCloseButton({ label }: ToasterCloseButtonProps): React.ReactElement {
  // The focus indicator takes the toast's text colour, so it shows on every variant.
  return (
    <ToastPrimitive.Close
      aria-label={label}
      className="absolute right-2 top-2 rounded-md p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
    >
      <CloseIcon className="h-4 w-4" />
    </ToastPrimitive.Close>
  );
}

/** The default pieces of a toast, for wrapping one. */
export const defaultToasterSlots: ToasterSlots = {
  Title: DefaultTitle,
  Description: DefaultDescription,
  CloseButton: DefaultCloseButton,
};

/**
 * How urgently screen readers announce each variant: an error interrupts
 * (assertive), everything else waits for a pause (polite).
 */
const ANNOUNCE: Record<ToastVariant, "foreground" | "background"> = {
  default: "background",
  success: "background",
  info: "background",
  error: "foreground",
};

export interface ToasterProps {
  /** Auto-dismiss duration in ms for toasts without their own (default 5000). */
  duration?: number;
  /** Swipe-to-dismiss direction (default "right"). */
  swipeDirection?: "right" | "left" | "up" | "down";
  /** Accessible label prefix announced with each toast (Radix Provider). */
  label?: string;
  /** Extra classes for the viewport, the list the toasts render in. */
  className?: string;
  /** Same as `className` (kept for compatibility). */
  viewportClassName?: string;
  /** Extra classes for every toast root. */
  toastClassName?: string;
  /** Replaces the Title, Description or CloseButton of every toast; see ToasterSlots. */
  slots?: Partial<ToasterSlots>;
}

/**
 * Renders the toasts pushed through useToast(). Mount exactly one near the
 * app root. Position defaults to the bottom-right corner; override with
 * `className` (it merges via cn(), so e.g. "top-0 bottom-auto" wins).
 *
 * Keyboard and screen readers: an error is announced at once (assertive),
 * other toasts politely. F8 moves focus to the toasts; Tab reaches each one
 * and its buttons, Escape dismisses the focused toast. A toast's timer pauses
 * while the pointer is over the toasts or focus is inside them, and while
 * the window is in the background.
 */
export function Toaster({
  duration = 5000,
  swipeDirection = "right",
  label = "Notification",
  className,
  viewportClassName,
  toastClassName,
  slots,
}: ToasterProps): React.ReactElement {
  const { toasts } = useToast();
  const { Title, Description, CloseButton } = { ...defaultToasterSlots, ...slots };

  return (
    <ToastPrimitive.Provider duration={duration} swipeDirection={swipeDirection} label={label}>
      {toasts.map((item) => (
        <ToastPrimitive.Root
          key={item.id}
          duration={item.duration}
          type={ANNOUNCE[item.variant]}
          data-variant={item.variant satisfies ToastVariant}
          onOpenChange={(open) => {
            if (!open) {
              dismissToast(item.id);
            }
          }}
          className={toastVariants({ variant: item.variant, className: toastClassName })}
        >
          <div className="grid flex-1 gap-1">
            {item.title != null && <Title variant={item.variant}>{item.title}</Title>}
            {item.description != null && (
              <Description variant={item.variant}>{item.description}</Description>
            )}
          </div>
          {item.action != null && <div className="flex shrink-0 items-center">{item.action}</div>}
          <CloseButton
            label="Dismiss"
            variant={item.variant}
            dismiss={() => dismissToast(item.id)}
          />
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport
        className={cn(
          "fixed bottom-0 right-0 z-toast flex w-full max-w-96 flex-col gap-2 p-4 outline-none",
          viewportClassName,
          className,
        )}
      />
    </ToastPrimitive.Provider>
  );
}
