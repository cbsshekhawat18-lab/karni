import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";
import { cn } from "../../lib/cn";

export type LabelProps = React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>;

export const Label = React.forwardRef<React.ElementRef<typeof LabelPrimitive.Root>, LabelProps>(
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
Label.displayName = "Label";
