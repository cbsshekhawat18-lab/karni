import * as React from "react";

/**
 * Minimal inline SVG icons used by the primitives (no icon dependency).
 * All strokes use `currentColor`, so they follow the text color tokens.
 * Internal to @karni/ui — not part of the public barrel.
 */

type IconProps = React.SVGAttributes<SVGSVGElement>;

function baseProps(props: IconProps): IconProps {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

export function CheckIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

export function ChevronUpIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <polyline points="18 15 12 9 6 15" />
    </svg>
  );
}
