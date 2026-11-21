/**
 * The purity check for a game's `src/rules/` folder: the rules are a
 * function of a seed and inputs, so they may not read a clock, ask for
 * outside randomness, touch the page or use the network. The check reads
 * source text and has no dependency, so it runs in a test, a script or the
 * browser.
 *
 * An allowed use carries a marker with a reason, on its line or the line
 * above:
 *
 *     // karni-allow: clock the build stamp is shown, never read by a step
 *
 * Several rules go in one marker, joined by commas with no space:
 * `karni-allow: clock,random reason`.
 */

export type PurityRule = "clock" | "random" | "dom" | "network" | "timer";

export interface Impurity {
  file: string;
  line: number;
  column: number;
  rule: PurityRule | "marker";
  /** The text found, or the marker. */
  found: string;
  message: string;
}

interface Pattern {
  rule: PurityRule;
  pattern: RegExp;
  message: string;
}

/** A name that is not a property of something else (`x.Date` is not the global). */
const G = String.raw`(?<![\w$.])`;

const PATTERNS: readonly Pattern[] = [
  {
    rule: "clock",
    pattern: new RegExp(`${G}Date\\b`, "g"),
    message: "the clock is not an input: take time from ctx.dt and the tick",
  },
  {
    rule: "clock",
    pattern: new RegExp(`${G}performance\\b`, "g"),
    message: "the clock is not an input: take time from ctx.dt and the tick",
  },
  {
    rule: "random",
    pattern: /(?<![\w$.])Math\s*\.\s*random\b/g,
    message: "use ctx.rng or ctx.stream(label): they are seeded and part of the hash",
  },
  {
    rule: "random",
    pattern: new RegExp(`${G}crypto\\b`, "g"),
    message: "use ctx.rng or ctx.stream(label): they are seeded and part of the hash",
  },
  {
    rule: "dom",
    pattern: new RegExp(
      `${G}(?:document|window|navigator|location|globalThis|localStorage|sessionStorage|indexedDB|` +
        `requestAnimationFrame|cancelAnimationFrame|AudioContext|CanvasRenderingContext2D|HTML\\w*Element)\\b`,
      "g",
    ),
    message: "the rules cannot touch the page: pass what they need in as state, input or config",
  },
  {
    rule: "network",
    pattern: new RegExp(`${G}(?:fetch|XMLHttpRequest|WebSocket|EventSource|Worker)\\b`, "g"),
    message:
      "the rules cannot reach the network: the game's code outside rules/ talks to the server",
  },
  {
    rule: "timer",
    pattern: new RegExp(
      `${G}(?:setTimeout|setInterval|setImmediate|requestIdleCallback|queueMicrotask)\\b`,
      "g",
    ),
    message: "a timer is a clock: count ticks in the state instead",
  },
];

/** `karni-allow: rule[,rule] reason`: rule names are joined by commas with no space. */
const MARKER = /karni-allow:\s*([a-z]+(?:,[a-z]+)*)(?:\s+(\S.*))?$/;
const RULES = new Set(PATTERNS.map((pattern) => pattern.rule));

/** Replace comments and string contents with spaces (newlines kept), and collect the comments. */
function mask(text: string): { code: string; comments: { line: number; text: string }[] } {
  const comments: { line: number; text: string }[] = [];
  const out: string[] = [];
  // Template literals nest: each open `${` pushes the brace depth to return to.
  const templates: number[] = [];
  let braces = 0;
  let line = 1;
  let index = 0;
  const blank = (char: string): string => (char === "\n" ? "\n" : " ");
  while (index < text.length) {
    const char = text[index] as string;
    const next = text[index + 1];
    if (char === "/" && next === "/") {
      let end = text.indexOf("\n", index);
      if (end < 0) end = text.length;
      comments.push({ line, text: text.slice(index + 2, end) });
      out.push(" ".repeat(end - index));
      index = end;
    } else if (char === "/" && next === "*") {
      let end = text.indexOf("*/", index + 2);
      end = end < 0 ? text.length : end + 2;
      const body = text.slice(index, end);
      comments.push({ line, text: body.slice(2, -2) });
      for (const c of body) {
        out.push(blank(c));
        if (c === "\n") line += 1;
      }
      index = end;
    } else if (char === '"' || char === "'" || char === "`") {
      // A string or template chunk: blank its contents, keep the quotes.
      out.push(char);
      index += 1;
      for (;;) {
        const c = text[index];
        if (c === undefined) break;
        if (c === "\\") {
          out.push(" ", blank(text[index + 1] ?? " "));
          if (text[index + 1] === "\n") line += 1;
          index += 2;
          continue;
        }
        if (c === char) {
          out.push(c);
          index += 1;
          break;
        }
        if (char === "`" && c === "$" && text[index + 1] === "{") {
          out.push("${");
          templates.push(braces);
          braces += 1;
          index += 2;
          break;
        }
        if (c === "\n") {
          if (char !== "`") break; // an unterminated plain string ends at the line
          line += 1;
        }
        out.push(blank(c));
        index += 1;
      }
    } else {
      if (char === "{") braces += 1;
      if (char === "}") {
        braces -= 1;
        if (templates.length && templates[templates.length - 1] === braces) {
          // Back inside the template text after `${ ... }`.
          templates.pop();
          out.push("}");
          index += 1;
          for (;;) {
            const c = text[index];
            if (c === undefined) break;
            if (c === "\\") {
              out.push(" ", blank(text[index + 1] ?? " "));
              index += 2;
              continue;
            }
            if (c === "`") {
              out.push(c);
              index += 1;
              break;
            }
            if (c === "$" && text[index + 1] === "{") {
              out.push("${");
              templates.push(braces);
              braces += 1;
              index += 2;
              break;
            }
            if (c === "\n") line += 1;
            out.push(blank(c));
            index += 1;
          }
          continue;
        }
      }
      if (char === "\n") line += 1;
      out.push(char);
      index += 1;
    }
  }
  return { code: out.join(""), comments };
}

/** The impurities of one source file. An allowed use (a marker with a reason) is left out. */
export function findImpurities(file: string, text: string): Impurity[] {
  const { code, comments } = mask(text);
  const problems: Impurity[] = [];
  // line -> rules allowed there
  const allowed = new Map<number, Set<string>>();
  const lines = text.split("\n");
  for (const comment of comments) {
    const match = MARKER.exec(comment.text.trim());
    if (!match) continue;
    const rules = (match[1] ?? "").split(",");
    const unknown = rules.find((rule) => !RULES.has(rule as PurityRule));
    if (unknown) {
      problems.push({
        file,
        line: comment.line,
        column: 1,
        rule: "marker",
        found: comment.text.trim(),
        message: `${unknown} is not a rule: use ${[...RULES].join(", ")}`,
      });
      continue;
    }
    if (!match[2]?.trim()) {
      problems.push({
        file,
        line: comment.line,
        column: 1,
        rule: "marker",
        found: comment.text.trim(),
        message: "a karni-allow marker needs a reason after the rule names",
      });
      continue;
    }
    // A marker alone on its line covers the next line, one after code covers its own.
    const own = (lines[comment.line - 1] ?? "").trim().startsWith("/")
      ? comment.line + 1
      : comment.line;
    const set = allowed.get(own) ?? new Set<string>();
    for (const rule of rules) set.add(rule);
    allowed.set(own, set);
  }
  const codeLines = code.split("\n");
  codeLines.forEach((source, index) => {
    for (const { rule, pattern, message } of PATTERNS) {
      pattern.lastIndex = 0;
      for (let match = pattern.exec(source); match; match = pattern.exec(source)) {
        if (allowed.get(index + 1)?.has(rule)) continue;
        problems.push({
          file,
          line: index + 1,
          column: match.index + 1,
          rule,
          found: match[0],
          message,
        });
      }
    }
  });
  return problems.sort((a, b) => a.line - b.line || a.column - b.column);
}

/** The impurities of several files. */
export function checkPurity(files: readonly { file: string; text: string }[]): Impurity[] {
  return files.flatMap(({ file, text }) => findImpurities(file, text));
}

/** One line per problem: `file:line:col rule found: message`. */
export function formatImpurities(problems: readonly Impurity[]): string {
  return problems
    .map((p) => `${p.file}:${p.line}:${p.column} ${p.rule} ${p.found}: ${p.message}`)
    .join("\n");
}
