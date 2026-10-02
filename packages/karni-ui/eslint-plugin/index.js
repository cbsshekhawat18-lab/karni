/**
 * @karni/ui/eslint-plugin — Karni's frontend enforcement rules.
 *
 * Plain ESM, no build step; ships inside the @karni/ui package (enforcement
 * contract §2 + F1, F15) and is consumed from flat config (ESLint >= 9):
 *
 *   // eslint.config.js
 *   import karni from "@karni/ui/eslint-plugin";
 *   export default [...karni.configs.recommended];
 *
 * Every rule fails the build ("error", never "warn"), and every rule's
 * documented opt-out is ESLint's own disable comment WITH a required reason:
 *
 *   // eslint-disable-next-line karni/no-direct-http -- <reason>
 *
 * The reason requirement is enforced by
 * @eslint-community/eslint-comments/require-description (a regular dependency
 * of @karni/ui — eslint itself is only a peer), and unused disable directives
 * are themselves errors (linterOptions.reportUnusedDisableDirectives).
 */
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";

import maxPageLines from "./rules/max-page-lines.js";
import noDeepImports from "./rules/no-deep-imports.js";
import noDirectHttp from "./rules/no-direct-http.js";
import noRawElements from "./rules/no-raw-elements.js";

const plugin = {
  meta: {
    name: "@karni/ui/eslint-plugin",
    version: "0.1.0",
  },
  rules: {
    "no-raw-elements": noRawElements,
    "max-page-lines": maxPageLines,
    "no-deep-imports": noDeepImports,
    "no-direct-http": noDirectHttp,
  },
  // Filled below so the config entries can reference the plugin object itself.
  configs: {},
};

plugin.configs.recommended = [
  {
    name: "karni/recommended",
    plugins: {
      karni: plugin,
      "@eslint-community/eslint-comments": eslintComments,
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      "karni/no-raw-elements": "error",
      "karni/max-page-lines": "error",
      "karni/no-deep-imports": "error",
      "karni/no-direct-http": "error",
      // Every eslint-disable needs a `-- reason`; a bare opt-out is a failure.
      "@eslint-community/eslint-comments/require-description": "error",
    },
  },
  {
    // Tests, mocks and vitest setup files stub the network by design.
    name: "karni/recommended-test-files",
    files: ["**/*.test.*", "**/mocks/**", "**/vitest.setup.*"],
    rules: {
      "karni/no-direct-http": "off",
    },
  },
];

export default plugin;
