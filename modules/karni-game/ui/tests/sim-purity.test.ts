// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { checkPurity, findImpurities, formatImpurities } from "../src/sim";
import { checkRules } from "../src/tooling";
import { main as cli } from "../src/tooling/cli";

const rules = (source: string) =>
  findImpurities("rules.ts", source).map((p) => `${p.rule}:${p.found}:${p.line}`);

describe("the purity check of a game's rules", () => {
  it("passes plain rules, and finds every kind of impurity with its place", () => {
    expect(
      rules(
        "export const step = (s: number, ctx: { rng: { next(): number } }) => s + ctx.rng.next();",
      ),
    ).toEqual([]);
    const source = [
      "const a = Date.now();",
      "const b = new Date();",
      "const c = performance.now();",
      "const d = Math.random();",
      "const e = crypto.getRandomValues(new Uint8Array(1));",
      "const f = document.title;",
      "const g = window.innerWidth;",
      "const h = localStorage.getItem('x');",
      "const i = await fetch('/x');",
      "const j = new WebSocket('wss://x');",
      "setTimeout(() => 1, 5);",
      "requestAnimationFrame(() => 1);",
    ].join("\n");
    expect(rules(source)).toEqual([
      "clock:Date:1",
      "clock:Date:2",
      "clock:performance:3",
      "random:Math.random:4",
      "random:crypto:5",
      "dom:document:6",
      "dom:window:7",
      "dom:localStorage:8",
      "network:fetch:9",
      "network:WebSocket:10",
      "timer:setTimeout:11",
      "dom:requestAnimationFrame:12",
    ]);
    const [first] = findImpurities("rules.ts", "  const t = Math . random();");
    expect(first).toMatchObject({ line: 1, column: 13, rule: "random" });
    expect(formatImpurities([first as NonNullable<typeof first>])).toContain(
      "rules.ts:1:13 random",
    );
  });

  it("does not flag names in comments, strings or as properties of rules' own objects", () => {
    expect(
      rules(
        [
          "// the old version used Date.now() and Math.random()",
          "/* window.document\n   fetch() */",
          "const label = 'Date and Math.random()';",
          'const other = "document.cookie";',
          "const text = `window ${1 + 1} fetch`;",
          "const nested = `a ${`b ${1}`} document`;",
          "const calendar = { day: 1 }; calendar.Date;",
          "const dateOfBirth = 1, update = 2, windowSize = 3;",
        ].join("\n"),
      ),
    ).toEqual([]);
    // Code inside `${}` is code.
    expect(rules("const t = `x ${Date.now()} y`;")).toEqual(["clock:Date:1"]);
    // A line number survives a multi-line template.
    expect(rules("const t = `a\nb\nc`;\nconst n = Date.now();")).toEqual(["clock:Date:4"]);
  });

  it("allows a use that carries a marker with a reason, on its line or the line above", () => {
    expect(
      rules(
        "const t = Date.now(); // karni-allow: clock stamps the debug log, never read by a step",
      ),
    ).toEqual([]);
    expect(rules("// karni-allow: clock the build stamp\nconst t = Date.now();")).toEqual([]);
    // The marker names a rule: another rule on the line is still found.
    expect(
      rules("// karni-allow: clock the build stamp\nconst t = Date.now() + Math.random();"),
    ).toEqual(["random:Math.random:2"]);
    // It covers one line only.
    expect(rules("// karni-allow: clock a reason\nconst a = 1;\nconst t = Date.now();")).toEqual([
      "clock:Date:3",
    ]);
    expect(
      rules(
        "// karni-allow: clock,random both are logged only\nconst t = Date.now() + Math.random();",
      ),
    ).toEqual([]);
  });

  it("fails a marker with no reason", () => {
    expect(rules("const t = Date.now(); // karni-allow: clock")).toEqual([
      "marker:karni-allow: clock:1",
      "clock:Date:1",
    ]);
    expect(rules("const t = Date.now(); // karni-allow: clok a reason")[0]).toBe(
      "marker:karni-allow: clok a reason:1",
    );
  });

  it("checks many files", () => {
    const problems = checkPurity([
      { file: "a.ts", text: "export const a = 1;" },
      { file: "b.ts", text: "export const b = Date.now();" },
    ]);
    expect(problems.map((p) => p.file)).toEqual(["b.ts"]);
  });
});

describe("checking a rules folder on disk", () => {
  const make = (files: Record<string, string>): string => {
    const dir = mkdtempSync(join(tmpdir(), "karni-rules-"));
    for (const [name, text] of Object.entries(files)) {
      mkdirSync(join(dir, name, ".."), { recursive: true });
      writeFileSync(join(dir, name), text);
    }
    return dir;
  };

  it("reads every source file below it, skips test files, and reports the others", () => {
    const dir = make({
      "ok.ts": "export const a = 1;",
      "deep/bad.ts": "export const t = Date.now();",
      "deep/bad.test.ts": "const t = Date.now();",
      "notes.md": "Date.now()",
    });
    try {
      const problems = checkRules(dir);
      expect(problems.map((p) => [p.file.endsWith("bad.ts"), p.rule])).toEqual([[true, "clock"]]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("fails a folder that is missing, and the command prints and exits by the result", async () => {
    expect(checkRules(join(tmpdir(), "karni-no-such-rules"))[0]?.message).toContain(
      "does not exist",
    );
    const clean = make({ "ok.ts": "export const a = 1;" });
    const dirty = make({ "bad.ts": "export const r = Math.random();" });
    try {
      const lines: string[] = [];
      expect(await cli(["check-rules", clean], (l) => lines.push(l))).toBe(0);
      expect(await cli(["check-rules", dirty], (l) => lines.push(l))).toBe(1);
      expect(lines.join("\n")).toContain("random Math.random");
    } finally {
      rmSync(clean, { recursive: true, force: true });
      rmSync(dirty, { recursive: true, force: true });
    }
  });
});
