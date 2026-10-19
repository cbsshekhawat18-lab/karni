/**
 * ESLint for @karni/impersonation-ui (eslintrc format, self-contained).
 *
 * packages/karni-ui itself moved to flat config (eslint.config.js) with the
 * @karni/ui/eslint-plugin preset; this package keeps its pinned eslintrc
 * stack for now and migrates when its eslint devDeps are next bumped.
 *
 * Repo rules enforced here:
 * - TypeScript strict, no `any`, no non-null assertions.
 * - D7: no runtime-concatenated Tailwind class fragments — every class name
 *   must appear whole in source (merge conditionals with cn(), never build
 *   class strings with `+` or template interpolation inside className).
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:@typescript-eslint/strict",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  ignorePatterns: ["dist/", "node_modules/", "coverage/"],
  rules: {
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
  overrides: [
    {
      files: ["*.cjs", "*.mjs", "*.config.ts", "vitest.setup.ts"],
      env: { node: true },
    },
    {
      files: ["**/*.test.ts", "**/*.test.tsx", "tests/**"],
      env: { node: true },
    },
  ],
};
