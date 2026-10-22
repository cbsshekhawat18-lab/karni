import * as React from "react";
import { cn } from "../../lib/cn";
import { overridable } from "../../primitives/registry";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

const KarniTextarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive",
        className,
      )}
      {...props}
    />
  ),
);
KarniTextarea.displayName = "Textarea";

/** Themed multi-line text input; every native `<textarea>` prop passes through.
 *
 * A project replaces it with its own through `primitives={{ textarea: ... }}` on KarniProvider.
 */
export const Textarea = overridable<TextareaProps, HTMLTextAreaElement>("textarea", KarniTextarea);
