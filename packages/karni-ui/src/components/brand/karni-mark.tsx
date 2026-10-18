import * as React from "react";
import { cn } from "../../lib/cn";
import { MARK_PATHS, MARK_SIMPLE_BODY, MARK_VIEWBOX } from "./mark-paths";

export interface KarniMarkProps extends Omit<React.SVGAttributes<SVGSVGElement>, "children"> {
  /** Rendered size in px (width and height). Default 28. */
  size?: number;
  /**
   * Which drawing: the full mark, the small-size variant, or `auto` (the
   * default) — the small variant at 32px and below, the full mark above.
   */
  variant?: "auto" | "full" | "simple";
  /** Accessible name; pass an empty string to hide a purely decorative mark. */
  title?: string;
}

/**
 * The Karni mark, inline SVG — no asset to load or bundle.
 *
 * It is the default content of `<Layout>`'s `sidebarHeader` slot so a bare
 * shell is never nameless; a project replaces it by passing its own
 * `sidebarHeader` (the scaffold already does). Do not recolour or restyle it:
 * the mark is Karni's, see assets/brand/README.md in the repository.
 */
export const KarniMark = React.forwardRef<SVGSVGElement, KarniMarkProps>(
  ({ size = 28, variant = "auto", title = "Karni", className, ...props }, ref) => {
    const simple = variant === "simple" || (variant === "auto" && size <= 32);
    const labelled = title !== "";
    return (
      <svg
        ref={ref}
        viewBox={MARK_VIEWBOX}
        width={size}
        height={size}
        role={labelled ? "img" : undefined}
        aria-hidden={labelled ? undefined : true}
        aria-label={labelled ? title : undefined}
        className={cn("shrink-0", className)}
        {...props}
        {...(simple ? { dangerouslySetInnerHTML: { __html: MARK_SIMPLE_BODY } } : {})}
      >
        {simple
          ? null
          : MARK_PATHS.map((path) => (
              <path key={path.fill + path.d.length} fill={path.fill} d={path.d} />
            ))}
      </svg>
    );
  },
);
KarniMark.displayName = "KarniMark";
