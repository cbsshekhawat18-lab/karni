import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { findImpurities, formatImpurities, type Impurity } from "../sim/purity";

const SOURCE = new Set([".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs"]);

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir).sort()) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (SOURCE.has(extname(name)) && !/\.(test|spec)\./.test(name)) yield path;
  }
}

/**
 * Check a game's rules folder (`src/rules` by default) for the clock, outside
 * randomness, the page and the network. Test files are skipped. A folder that
 * does not exist is a problem, so a renamed folder cannot pass by being empty.
 */
export function checkRules(dir = "src/rules"): Impurity[] {
  if (!existsSync(dir)) {
    return [
      {
        file: dir,
        line: 0,
        column: 0,
        rule: "marker",
        found: dir,
        message: "the rules folder does not exist",
      },
    ];
  }
  const problems: Impurity[] = [];
  for (const path of walk(dir)) {
    problems.push(...findImpurities(relative(process.cwd(), path), readFileSync(path, "utf8")));
  }
  return problems;
}

export { formatImpurities };
export type { Impurity };
