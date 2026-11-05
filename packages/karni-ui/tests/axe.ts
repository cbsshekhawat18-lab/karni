/**
 * axe-core over one rendered component, with the options of tests/a11y.test.tsx:
 * the WCAG 2.x A and AA rules, colour contrast off (jsdom computes no styles,
 * so tests/contrast.test.ts checks the token pairs instead).
 */
import axe from "axe-core";
import { vi } from "vitest";

const OPTIONS: axe.RunOptions = {
  runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
  rules: { "color-contrast": { enabled: false } },
};

/** The ids of the rules `container` violates (an empty list passes). */
export async function axeViolations(container: Element): Promise<string[]> {
  // axe probes a canvas for icon fonts. jsdom has none (and says so on stderr).
  const canvas = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  try {
    const results = await axe.run(container, OPTIONS);
    return results.violations.map((violation) => violation.id);
  } finally {
    canvas.mockRestore();
  }
}
