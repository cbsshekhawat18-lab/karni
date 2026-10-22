import * as React from "react";
import { overridable } from "../../primitives/registry";
import { variants, type VariantProps } from "../../lib/variants";

/**
 * Exported for composition (escape hatch): render any element as a button
 * lookalike with `className={buttonVariants({ variant: "outline" })}`.
 */
export const buttonVariants = variants({
  base: "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  variants: {
    variant: {
      default: "bg-primary text-primary-foreground hover:bg-primary-hover",
      destructive: "bg-destructive text-destructive-foreground hover:bg-destructive-hover",
      outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
      secondary: "bg-secondary text-secondary-foreground hover:bg-secondary-hover",
      ghost: "hover:bg-accent hover:text-accent-foreground",
      link: "text-primary underline-offset-4 hover:underline",
    },
    size: {
      default: "h-10 px-4 py-2",
      sm: "h-9 rounded-md px-3",
      lg: "h-11 rounded-md px-8",
      icon: "h-10 w-10",
    },
  },
  defaultVariants: {
    variant: "default",
    size: "default",
  },
});

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & ButtonVariantProps;

const KarniButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type, ...props }, ref) => (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonVariants({ variant, size, className })}
      {...props}
    />
  ),
);
KarniButton.displayName = "Button";

/**
 * Themed button. `type` defaults to "button" (pass type="submit" in forms).
 * `className` is merged via cn(), so consumer classes win.
 * A project replaces it with its own through `primitives={{ button: ... }}` on KarniProvider.
 */
export const Button = overridable<ButtonProps, HTMLButtonElement>("button", KarniButton);
