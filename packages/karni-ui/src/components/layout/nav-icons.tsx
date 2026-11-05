/**
 * Experimental. Icons by name for the server's menu (`NavigationItem.icon`).
 *
 * The server sends a name (`"home"`, `"bar-chart"`). Layout looks it up in
 * `defaultNavIcons`, merged under its `icons` prop, so a project adds names
 * or replaces these with its own icon set. An unknown name shows no icon.
 * Each one is an inline SVG drawn with `currentColor` (no icon dependency).
 */
import * as React from "react";

function icon(name: string, children: React.ReactNode): React.ReactElement {
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
      data-icon={name}
    >
      {children}
    </svg>
  );
}

const grid = (
  <>
    <rect x="4" y="4" width="7" height="7" rx="1" />
    <rect x="13" y="4" width="7" height="7" rx="1" />
    <rect x="4" y="13" width="7" height="7" rx="1" />
    <rect x="13" y="13" width="7" height="7" rx="1" />
  </>
);
const chart = (
  <>
    <line x1="4" y1="20" x2="20" y2="20" />
    <rect x="6" y="11" width="3" height="6" />
    <rect x="11" y="6" width="3" height="11" />
    <rect x="16" y="13" width="3" height="4" />
  </>
);
const sliders = (
  <>
    <line x1="4" y1="7" x2="20" y2="7" />
    <line x1="4" y1="17" x2="20" y2="17" />
    <circle cx="9" cy="7" r="2" />
    <circle cx="15" cy="17" r="2" />
  </>
);

/** Experimental. The icons Layout knows by name. Spread it to add or replace names. */
export const defaultNavIcons: Readonly<Record<string, React.ReactNode>> = {
  home: icon(
    "home",
    <>
      <path d="M3 11 12 4l9 7" />
      <path d="M5 10v10h14V10" />
      <path d="M10 20v-6h4v6" />
    </>,
  ),
  list: icon(
    "list",
    <>
      <line x1="9" y1="6" x2="20" y2="6" />
      <line x1="9" y1="12" x2="20" y2="12" />
      <line x1="9" y1="18" x2="20" y2="18" />
      <circle cx="4.5" cy="6" r="1" />
      <circle cx="4.5" cy="12" r="1" />
      <circle cx="4.5" cy="18" r="1" />
    </>,
  ),
  grid: icon("grid", grid),
  dashboard: icon("dashboard", grid),
  folder: icon("folder", <path d="M3 6h6l2 2h10v11H3z" />),
  file: icon(
    "file",
    <>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
    </>,
  ),
  chart: icon("chart", chart),
  "bar-chart": icon("bar-chart", chart),
  settings: icon("settings", sliders),
  sliders: icon("sliders", sliders),
  user: icon(
    "user",
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
    </>,
  ),
  users: icon(
    "users",
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M16 14.2c2.8.4 5 2.8 5 5.8" />
    </>,
  ),
  box: icon(
    "box",
    <>
      <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
      <path d="M3 7l9 4 9-4" />
      <line x1="12" y1="11" x2="12" y2="21" />
    </>,
  ),
  calendar: icon(
    "calendar",
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <line x1="8" y1="3" x2="8" y2="7" />
      <line x1="16" y1="3" x2="16" y2="7" />
    </>,
  ),
  map: icon(
    "map",
    <>
      <path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" />
      <line x1="9" y1="4" x2="9" y2="18" />
      <line x1="15" y1="6" x2="15" y2="20" />
    </>,
  ),
  tag: icon(
    "tag",
    <>
      <path d="M3 12V3h9l9 9-9 9z" />
      <circle cx="7.5" cy="7.5" r="1.5" />
    </>,
  ),
  search: icon(
    "search",
    <>
      <circle cx="11" cy="11" r="6" />
      <line x1="16" y1="16" x2="20" y2="20" />
    </>,
  ),
};

/** Experimental. The icon for `name`: from `icons`, else `defaultNavIcons`, else none. */
export function navIcon(
  name: string | null | undefined,
  icons?: Readonly<Record<string, React.ReactNode>>,
): React.ReactNode {
  if (name === null || name === undefined || name === "") return undefined;
  if (icons !== undefined && name in icons) return icons[name];
  return defaultNavIcons[name];
}
