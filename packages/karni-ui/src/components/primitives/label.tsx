import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";
import { cn } from "../../lib/cn";
import { overridable } from "../../primitives/registry";

export type LabelProps = React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>;

const KarniLabel = React.forwardRef<React.ElementRef<typeof LabelPrimitive.Root>, LabelProps>(
  ({ className, ...props }, ref) => (
    <LabelPrimitive.Root
      ref={ref}
      className={cn(
        "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className,
      )}
      {...props}
    />
  ),
);
KarniLabel.displayName = "Label";

/** Themed form label (Radix Label) that dims when its field is disabled.
 *
 * A project replaces it with its own through `primitives={{ label: ... }}` on KarniProvider.
 */
export const Label = overridable<LabelProps, HTMLLabelElement>("label", KarniLabel);
