import * as React from "react";
import { cn } from "../../lib/cn";
import { overridable } from "../../primitives/registry";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const KarniInput = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive",
        className,
      )}
      {...props}
    />
  ),
);
KarniInput.displayName = "Input";

/** Themed text input that passes every native `<input>` prop through.
 *
 * A project replaces it with its own through `primitives={{ input: ... }}` on KarniProvider.
 */
export const Input = overridable<InputProps, HTMLInputElement>("input", KarniInput);
