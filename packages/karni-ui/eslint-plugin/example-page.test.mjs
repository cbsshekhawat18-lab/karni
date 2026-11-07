/**
 * The example dashboard page (examples/eventhub/frontend/src/pages/venue-overview.tsx)
 * composes the page blocks under the frontend rules a project runs: it stays
 * within karni/max-page-lines (50 lines), uses no raw table and imports only
 * the @karni/ui barrel. EventHub's CI job type-checks and builds it against
 * this package.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Linter } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";
import plugin from "./index.js";

const PAGE = join(
  process.cwd(),
  "..",
  "..",
  "examples",
  "eventhub",
  "frontend",
  "src",
  "pages",
  "venue-overview.tsx",
);

function lint(source) {
  const linter = new Linter({ configType: "flat" });
  return linter
    .verify(
      source,
      [
        ...plugin.configs.recommended,
        {
          files: ["**/*.tsx"],
          languageOptions: {
            parser: tseslint.parser,
            parserOptions: { ecmaFeatures: { jsx: true } },
          },
        },
      ],
      { filename: join(process.cwd(), "project/frontend/src/pages/venue-overview.tsx") },
    )
    .map((message) => `${message.ruleId ?? ""}: ${message.message}`);
}

describe("the example dashboard page", () => {
  const source = readFileSync(PAGE, "utf8");

  it("passes the project rules (the 50-line cap, no raw elements, the barrel only)", () => {
    expect(lint(source)).toEqual([]);
    expect(source.split("\n").length - 1).toBeLessThan(50);
  });

  it("would fail them with a raw table or past the cap (the check is live)", () => {
    const raw = source.replace("<DashboardGrid>", "<DashboardGrid><table />");
    expect(lint(raw).some((line) => line.startsWith("karni/no-raw-elements"))).toBe(true);
    const long = source + "\n".repeat(10) + "export const x = 1;\n";
    expect(lint(long).some((line) => line.startsWith("karni/max-page-lines"))).toBe(true);
  });

  it("composes DashboardGrid, ChartCard, DataTable and ComparisonTable", () => {
    for (const block of ["DashboardGrid", "ChartCard", "DataTable", "ComparisonTable"]) {
      expect(source, block).toContain(`<${block}`);
    }
    const imports = [...source.matchAll(/from "([^"]+)"/g)].map((match) => match[1]);
    expect(new Set(imports)).toEqual(new Set(["@karni/ui"]));
  });
});
