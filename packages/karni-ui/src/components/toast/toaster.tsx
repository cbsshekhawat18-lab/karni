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
  base: "pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-md border p-4 pr-8 shadow-lg",
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

export interface ToasterProps {
  /** Auto-dismiss duration in ms for toasts without their own (default 5000). */
  duration?: number;
  /** Swipe-to-dismiss direction (default "right"). */
  swipeDirection?: "right" | "left" | "up" | "down";
  /** Accessible label prefix announced with each toast (Radix Provider). */
  label?: string;
  /** Extra classes for the viewport (position/stacking escape hatch). */
  viewportClassName?: string;
  /** Extra classes for every toast root. */
  toastClassName?: string;
}

/**
 * Renders the toasts pushed through useToast(). Mount exactly one near the
 * app root. Position defaults to the bottom-right corner; override with
 * `viewportClassName` (it merges via cn(), so e.g. "top-0 bottom-auto" wins).
 */
export function Toaster({
  duration = 5000,
  swipeDirection = "right",
  label = "Notification",
  viewportClassName,
  toastClassName,
}: ToasterProps): React.ReactElement {
  const { toasts } = useToast();

  return (
    <ToastPrimitive.Provider duration={duration} swipeDirection={swipeDirection} label={label}>
      {toasts.map((item) => (
        <ToastPrimitive.Root
          key={item.id}
          duration={item.duration}
          data-variant={item.variant satisfies ToastVariant}
          onOpenChange={(open) => {
            if (!open) {
              dismissToast(item.id);
            }
          }}
          className={toastVariants({ variant: item.variant, className: toastClassName })}
        >
          <div className="grid flex-1 gap-1">
            {item.title != null && (
              <ToastPrimitive.Title className="text-sm font-semibold">
                {item.title}
              </ToastPrimitive.Title>
            )}
            {item.description != null && (
              <ToastPrimitive.Description className="text-sm opacity-90">
                {item.description}
              </ToastPrimitive.Description>
            )}
          </div>
          {item.action != null && <div className="flex shrink-0 items-center">{item.action}</div>}
          <ToastPrimitive.Close
            aria-label="Dismiss"
            className="absolute right-2 top-2 rounded-md p-1 opacity-70 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <CloseIcon className="h-4 w-4" />
          </ToastPrimitive.Close>
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport
        className={cn(
          "fixed bottom-0 right-0 z-[100] flex w-full max-w-sm flex-col gap-2 p-4 outline-none",
          viewportClassName,
        )}
      />
    </ToastPrimitive.Provider>
  );
}
