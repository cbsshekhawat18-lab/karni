/**
 * ESLint flat config for @karni/ui (ESLint >= 9).
 *
 * Repo rules enforced here:
 * - TypeScript strict, no `any`, no non-null assertions.
 * - D7: no runtime-concatenated Tailwind class fragments — every class name
 *   must appear whole in source (merge conditionals with cn(), never build
 *   class strings with `+` or template interpolation inside className).
 * - The package dogfoods its own enforcement plugin (eslint-plugin/):
 *   karni/* rules + required eslint-disable descriptions. The UI package is
 *   the one allowed home of raw elements, so karni/no-raw-elements is off
 *   here; fetch lives only in the schema client (src/schema/).
 */
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

import karni from "./eslint-plugin/index.js";

export default tseslint.config(
  {
    ignores: ["dist/", "node_modules/", "storybook-static/", "public/", "coverage/"],
  },
  js.configs.recommended,
  ...tseslint.configs.strict,
  ...karni.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    files: ["**/*.ts", "**/*.tsx"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='className'] BinaryExpression[operator='+']",
          message:
            "Do not concatenate Tailwind class fragments (D7). Write whole class names and merge them with cn().",
        },
        {
          selector: "JSXAttribute[name.name='className'] TemplateLiteral[expressions.length>0]",
          message:
            "Do not interpolate Tailwind class fragments (D7). Write whole class names and merge them with cn().",
        },
      ],
    },
  },
  {
    // This package IS the allowed home of raw elements; its HTTP layer is the
    // schema client itself.
    rules: {
      "karni/no-raw-elements": "off",
      "karni/no-direct-http": ["error", { allowPatterns: ["**/src/schema/**"] }],
    },
  },
  {
    // Every visual value in a shipped component resolves from a --karni-*
    // token; `npm run build` runs lint, so a literal fails the build.
    files: ["src/**/*.ts", "src/**/*.tsx"],
    // mark-paths.ts is the Karni logo, generated from assets/brand/: its
    // colours are the brand's, fixed by its usage rules, not theme values.
    ignores: [
      "**/*.test.*",
      "**/*.stories.*",
      "**/demo-fixtures.ts",
      "**/fixtures.ts",
      "src/components/brand/mark-paths.ts",
    ],
    rules: { "karni/no-style-literals": "error" },
  },
  {
    // Re-assert the preset's test-file carve-out after the override above
    // (later entries win in flat config); tests/ holds msw infrastructure.
    files: ["**/*.test.*", "**/mocks/**", "**/vitest.setup.*", "tests/**"],
    rules: { "karni/no-direct-http": "off" },
  },
  {
    files: ["**/*.cjs", "**/*.mjs", "scripts/**", "eslint-plugin/**", "eslint.config.js"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["**/*.test.*", "tests/**", "vitest.setup.ts", ".storybook/**"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  prettier,
);
