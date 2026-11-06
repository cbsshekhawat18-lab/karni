/**
 * axe-core over one rendered component, with the options of tests/a11y.test.tsx:
 * the WCAG 2.x A and AA rules, colour contrast off (jsdom computes no styles,
 * so tests/contrast.test.ts checks the token pairs instead).
 */
import axe from "axe-core";
import { vi } from "vitest";

/**
 * WCAG 2.5.3 (label in name). axe has this rule, but it is experimental and
 * jsdom has no layout, so it never fails here. This one reads the same two
 * things: the accessible name (axe's own computation) and the text a sighted
 * person reads (the text content without `aria-hidden` parts and icons). It
 * runs with the other WCAG 2.1 A rules in every axe pass that imports this file.
 */
const CONTROLS =
  'button, a[href], summary, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="checkbox"], [role="radio"], [role="switch"]';

/** Words only: case, punctuation and spacing do not count in WCAG 2.5.3. */
function words(text: string): string {
  return (text.match(/[\p{L}\p{N}]+/gu) ?? []).join(" ").toLowerCase();
}

/** The text a sighted person reads: text nodes joined by a space, icons and aria-hidden parts left out. */
function visibleText(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  for (const hidden of Array.from(copy.querySelectorAll('[aria-hidden="true"], svg'))) {
    hidden.remove();
  }
  const parts: string[] = [];
  const walker = copy.ownerDocument.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
  for (let current = walker.nextNode(); current !== null; current = walker.nextNode()) {
    parts.push(current.textContent ?? "");
  }
  return parts.join(" ");
}

axe.configure({
  checks: [
    {
      id: "karni-label-in-name",
      evaluate: (node: Element, _options: unknown, virtualNode: unknown) => {
        const visible = words(visibleText(node));
        if (visible === "") return true;
        const name = words(axe.commons.text.accessibleTextVirtual(virtualNode as never));
        return ` ${name} `.includes(` ${visible} `);
      },
      metadata: {
        impact: "serious",
        messages: {
          pass: "The accessible name contains the visible text",
          fail: "The accessible name does not contain the visible text (WCAG 2.5.3)",
        },
      },
    },
  ],
  rules: [
    {
      id: "label-content-name-mismatch",
      enabled: true,
      selector: CONTROLS,
      any: ["karni-label-in-name"],
      tags: ["cat.semantics", "wcag21a", "wcag253"],
      metadata: {
        description: "Controls whose accessible name starts with their visible text",
        help: "The accessible name must contain the visible text",
      },
    },
  ],
});

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
