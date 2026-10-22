#!/usr/bin/env node
/**
 * axe-core over every Storybook story, in a real browser, in both themes.
 *
 *   npm run build-storybook -- -o storybook-static
 *   node scripts/a11y-stories.mjs storybook-static [--only a,b]
 *
 * Opens every story's iframe in Chromium (light, then `globals=theme:dark`),
 * lets it settle (stories that fetch through msw included), runs axe's WCAG
 * 2.0, 2.1 and 2.2 A and AA rules (colour contrast included, on the real
 * styles) and fails on any violation, listing the story, theme, rule and
 * elements. A story opts out only with a reason:
 * `parameters: { a11y: { disable: true, reason: "..." } }`, or one rule only:
 * `parameters: { a11y: { disableRules: { "rule-id": "why it does not apply" } } }`.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { listStories, openStory, serveStatic, storyParameters } from "./lib/storybook.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW ?? "playwright");
const AXE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const THEMES = ["light", "dark"];

const root = path.resolve(process.argv[2] ?? "storybook-static");
const stories = listStories(root);
const { base, close } = await serveStatic(root);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const failures = [];
const skipped = [];
let checked = 0;

for (const story of stories) {
  for (const theme of THEMES) {
    const rendered = await openStory(page, base, story, theme);
    const parameters = (await storyParameters(page))?.a11y ?? null;
    if (parameters?.disable) {
      if (theme === "light")
        skipped.push(`${story.id}: ${parameters.reason ?? "(no reason given)"}`);
      continue;
    }
    // `disableRules: { "rule-id": "why it does not apply here" }` turns off one rule.
    const disabled = Object.entries(parameters?.disableRules ?? {});
    for (const [rule, reason] of disabled) {
      if (!reason) throw new Error(`${story.id}: disableRules.${rule} needs a reason`);
      if (theme === "light") skipped.push(`${story.id} (${rule} only): ${reason}`);
    }
    if (!rendered) {
      failures.push({
        story: story.id,
        theme,
        id: "story-did-not-render",
        impact: "n/a",
        help: "the story rendered nothing within 5s",
        nodes: [],
      });
      continue;
    }
    await page.addScriptTag({ content: AXE });
    const violations = await page.evaluate(
      async ({ tags, off }) => {
        // axe is the script tag injected just above; eslint cannot see it.
        const rules = Object.fromEntries(off.map((rule) => [rule, { enabled: false }]));
        const result = await globalThis.axe.run(document, {
          runOnly: { type: "tag", values: tags },
          rules,
        });
        return result.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.slice(0, 5).map((node) => {
            const why = (node.failureSummary ?? "").split("\n").slice(1, 2).join("").trim();
            return `${node.target.join(" ")}  — ${why}`;
          }),
        }));
      },
      { tags: TAGS, off: disabled.map(([rule]) => rule) },
    );
    checked += 1;
    for (const violation of violations) failures.push({ story: story.id, theme, ...violation });
  }
}

await browser.close();
close();

for (const line of skipped) console.log(`skipped  ${line}`);
if (failures.length > 0) {
  for (const failure of failures) {
    console.log(
      `FAIL  ${failure.story} [${failure.theme}] ${failure.id} (${failure.impact}): ${failure.help}`,
    );
    for (const node of failure.nodes) console.log(`        ${node}`);
  }
  console.log(
    `\n${failures.length} violation(s) in ${checked} story renders (${stories.length} stories × ${THEMES.length} themes).`,
  );
  process.exit(1);
}
console.log(
  `axe: no violations in ${checked} story renders (${stories.length} stories × ${THEMES.length} themes, WCAG 2.x A/AA).`,
);
