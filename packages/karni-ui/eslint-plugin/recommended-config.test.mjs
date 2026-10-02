/**
 * configs.recommended — flat-config preset shape + end-to-end Linter runs
 * (enforcement contract §2 + F1, F12): all four rules at "error", unused
 * disable directives are errors, and every eslint-disable needs a reason.
 */
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin from "./index.js";

const [base, testOverride] = plugin.configs.recommended;

/**
 * The base entry plus the file patterns and parser options the consumer's
 * config provides (a bare Linter has no default `files`, so without them the
 * .tsx filename below would match no configuration).
 */
function flatConfig(extra = {}) {
  return {
    files: ["**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"],
    ...base,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    ...extra,
  };
}

describe("configs.recommended", () => {
  it("is a flat-config array (F1)", () => {
    expect(Array.isArray(plugin.configs.recommended)).toBe(true);
    expect(base.plugins.karni).toBe(plugin);
    expect(base.plugins["@eslint-community/eslint-comments"]).toBeDefined();
    expect(base.linterOptions.reportUnusedDisableDirectives).toBe("error");
  });

  it("sets every rule to error, never warn", () => {
    expect(base.rules).toMatchObject({
      "karni/no-raw-elements": "error",
      "karni/max-page-lines": "error",
      "karni/no-deep-imports": "error",
      "karni/no-direct-http": "error",
      "@eslint-community/eslint-comments/require-description": "error",
    });
  });

  it("carves no-direct-http out of tests, mocks and vitest setup (F12)", () => {
    expect(testOverride.files).toEqual(["**/*.test.*", "**/mocks/**", "**/vitest.setup.*"]);
    expect(testOverride.rules).toEqual({ "karni/no-direct-http": "off" });
  });

  it("reports raw elements and direct HTTP through the preset", () => {
    const linter = new Linter();
    const messages = linter.verify(
      'export function Page() { return <form onSubmit={() => fetch("/x")} />; }\n',
      flatConfig(),
      "src/pages/Home.tsx",
    );
    const ruleIds = messages.map((m) => m.ruleId).sort();
    expect(ruleIds).toEqual(["karni/no-direct-http", "karni/no-raw-elements"]);
    expect(messages.every((m) => m.severity === 2)).toBe(true);
  });

  it("accepts a described disable and rejects a bare one", () => {
    const linter = new Linter();
    const described = linter.verify(
      '// eslint-disable-next-line karni/no-direct-http -- legacy health probe, removed in #42\nawait fetch("/health/");\n',
      flatConfig(),
      "src/pages/Home.tsx",
    );
    expect(described).toEqual([]);

    const bare = linter.verify(
      '// eslint-disable-next-line karni/no-direct-http\nawait fetch("/health/");\n',
      flatConfig(),
      "src/pages/Home.tsx",
    );
    expect(bare.map((m) => m.ruleId)).toContain(
      "@eslint-community/eslint-comments/require-description",
    );
  });

  it("errors on unused disable directives", () => {
    const linter = new Linter();
    const messages = linter.verify(
      "// eslint-disable-next-line karni/no-direct-http -- not actually needed\nconst a = 1;\nexport default a;\n",
      flatConfig(),
      "src/pages/Home.tsx",
    );
    expect(messages.some((m) => /unused eslint-disable/i.test(m.message))).toBe(true);
    expect(messages.every((m) => m.severity === 2)).toBe(true);
  });
});
