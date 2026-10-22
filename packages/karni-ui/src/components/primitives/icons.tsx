import * as React from "react";

/**
 * Minimal inline SVG icons used by the primitives (no icon dependency).
 * All strokes use `currentColor`, so they follow the text color tokens.
 * Internal to @karni/ui, not part of the public barrel.
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

export function AlertIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

export function LockIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

export function OfflineIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M16.7 11.1A10.9 10.9 0 0 1 19 12.6M5 12.6a10.9 10.9 0 0 1 5.2-2.5M10.7 5A16 16 0 0 1 22.6 9M1.4 9a15.9 15.9 0 0 1 4.7-2.9M8.5 16.1a6 6 0 0 1 7 0" />
      <line x1="12" y1="20" x2="12.01" y2="20" />
    </svg>
  );
}

export function SearchIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

export function SpinnerIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <path d="M21 12a9 9 0 1 1-6.2-8.6" />
    </svg>
  );
}

export function SunIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

export function MoonIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

export function MonitorIcon(props: IconProps): React.ReactElement {
  return (
    <svg {...baseProps(props)}>
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}
