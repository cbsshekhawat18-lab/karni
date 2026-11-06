/**
 * The heading levels a component may take below a page's own `<h1>`. A
 * component renders its headings at the level it is given (`headingLevel`)
 * so the page's outline never skips a level (WCAG 1.3.1, axe `heading-order`).
 */
export type HeadingLevel = 2 | 3 | 4 | 5 | 6;

export const HEADING_TAGS = { 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" } as const;

/** The level under `level`, at most h6. */
export function nextHeadingLevel(level: HeadingLevel): HeadingLevel {
  return Math.min(level + 1, 6) as HeadingLevel;
}
