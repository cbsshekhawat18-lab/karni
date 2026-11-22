/**
 * ESLint flat config for @karni/game (ESLint >= 9).
 *
 * Repo rules enforced here: TypeScript strict, no `any`, no non-null
 * assertions, and the rules of hooks for the React Three Fiber entry point.
 */
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/", "coverage/", "example/**/dist/", "**/*.gen.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
    },
  },
  {
    files: ["**/*.tsx"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
  {
    files: [
      "src/tooling/**",
      "src/smoke/**",
      "bin/**",
      "**/*.config.ts",
      "eslint.config.js",
      "tests/**",
      "tests-browser/**",
    ],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  prettier,
);
