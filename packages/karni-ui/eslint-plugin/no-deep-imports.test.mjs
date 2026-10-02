/**
 * RuleTester suite for karni/no-deep-imports (ESLint 9 under vitest).
 */
import { RuleTester } from "eslint";

import rule from "./rules/no-deep-imports.js";

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: "latest", sourceType: "module" },
});

ruleTester.run("no-deep-imports", rule, {
  valid: [
    { code: 'import { ResourceTable } from "@karni/ui";' },
    { code: 'import "@karni/ui/styles.css";' },
    { code: 'import preset from "@karni/ui/tailwind-preset";' },
    { code: 'import manifest from "@karni/ui/manifest.json";' },
    { code: 'import karni from "@karni/ui/eslint-plugin";' },
    { code: 'import { helper } from "./dist/local";' },
    { code: 'import { other } from "@karni/ui-extras/dist/x";' },
    { code: 'const mod = await import("@karni/ui");' },
  ],
  invalid: [
    {
      code: 'import { ResourceTable } from "@karni/ui/dist/index.js";',
      errors: [{ messageId: "deepImport" }],
    },
    {
      code: 'import { table } from "@karni/ui/src/components/resource/table/ResourceTable";',
      errors: [{ messageId: "deepImport" }],
    },
    {
      code: 'export { cn } from "@karni/ui/src/lib/cn";',
      errors: [{ messageId: "deepImport" }],
    },
    {
      code: 'export * from "@karni/ui/dist/chunks/table";',
      errors: [{ messageId: "deepImport" }],
    },
    {
      code: 'const mod = await import("@karni/ui/src/lib/variants");',
      errors: [{ messageId: "deepImport" }],
    },
    {
      code: 'const mod = require("@karni/ui/dist/index.js");',
      errors: [{ messageId: "deepImport" }],
    },
  ],
});
