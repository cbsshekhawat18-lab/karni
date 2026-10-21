/**
 * ResourceTable's own icons (pagination arrows, create, view options). Inline
 * SVG with `currentColor` strokes, like the primitives' icons.
 * Internal to @karni/ui.
 */
import * as React from "react";

type IconProps = React.SVGAttributes<SVGSVGElement>;

function Icon({
  children,
  ...props
}: IconProps & { children: React.ReactNode }): React.ReactElement {
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
      {children}
    </svg>
  );
}

export function ChevronLeftIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polyline points="15 18 9 12 15 6" />
    </Icon>
  );
}

export function ChevronRightIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polyline points="9 18 15 12 9 6" />
    </Icon>
  );
}

export function FirstPageIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polyline points="17 18 11 12 17 6" />
      <line x1="7" y1="6" x2="7" y2="18" />
    </Icon>
  );
}

export function LastPageIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polyline points="7 18 13 12 7 6" />
      <line x1="17" y1="6" x2="17" y2="18" />
    </Icon>
  );
}

export function PlusIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </Icon>
  );
}

export function SlidersIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="9" cy="6" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="8" cy="18" r="2" />
    </Icon>
  );
}

export function FilterOffIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polygon points="22 3 2 3 10 12.5 10 19 14 21 14 12.5 22 3" />
    </Icon>
  );
}

export function InboxIcon(props: IconProps): React.ReactElement {
  return (
    <Icon {...props}>
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </Icon>
  );
}
