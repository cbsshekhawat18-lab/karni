/**
 * ESLint flat config for @karni/game (ESLint >= 9).
 *
 * Repo rules enforced here: TypeScript strict, no `any`, no non-null
 * assertions. The package has no runtime dependency, so nothing here needs
 * a plugin beyond typescript-eslint.
 */
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/", "coverage/", "example/**/dist/"] },
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
    files: [
      "src/tooling/**",
      "src/smoke/**",
      "bin/**",
      "**/*.config.ts",
      "eslint.config.js",
      "tests/**",
    ],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  prettier,
);
