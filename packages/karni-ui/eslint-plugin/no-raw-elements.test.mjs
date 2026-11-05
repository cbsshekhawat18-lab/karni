/**
 * RuleTester suite for karni/no-raw-elements (ESLint 9 under vitest; the
 * RuleTester picks up vitest's global describe/it).
 */
import { RuleTester } from "eslint";

import rule from "./rules/no-raw-elements.js";

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

ruleTester.run("no-raw-elements", rule, {
  valid: [
    { code: 'const x = <div className="p-2">ok</div>;' },
    { code: 'const x = <ResourceTable resource="events" />;' },
    { code: 'const x = <DataTable caption="Totals" columns={columns} rows={rows} />;' },
    { code: "const x = <Accordion items={items} />;" },
    { code: 'const x = <Form onSubmit={go}><Input name="a" /></Form>;' },
    // Member-expression JSX names are component references, never raw tags.
    { code: "const x = <UI.table />;" },
    // Allowlisted paths (the UI package itself is configured this way).
    {
      code: "const x = <table><tbody /></table>;",
      options: [{ allow: ["**/karni-ui/src/**"] }],
      filename: "/repo/packages/karni-ui/src/components/resource/table/ResourceTable.tsx",
    },
  ],
  invalid: [
    {
      code: "const x = <table><tbody /></table>;",
      errors: [
        {
          messageId: "rawElement",
          data: {
            element: "table",
            replacement:
              "ResourceTable (a resource's rows), DataTable (rows the page computed) or ComparisonTable (entities side by side)",
          },
        },
      ],
    },
    {
      // A disclosure is an Accordion (the WAI-ARIA pattern, keyboard included).
      code: "const x = <details><summary>More</summary>text</details>;",
      errors: [{ messageId: "rawElement", data: { element: "details", replacement: "Accordion" } }],
    },
    {
      code: "const x = <form onSubmit={go} />;",
      errors: [{ messageId: "rawElement" }],
    },
    {
      code: "const x = <input value={v} />;",
      errors: [{ messageId: "rawElement" }],
    },
    {
      code: "const x = <select>{options}</select>;",
      errors: [{ messageId: "rawElement" }],
    },
    {
      code: "const x = <textarea rows={4} />;",
      errors: [{ messageId: "rawElement" }],
    },
    {
      // A non-matching allowlist does not exempt the file.
      code: "const x = <form />;",
      options: [{ allow: ["**/karni-ui/src/**"] }],
      filename: "/repo/app/src/pages/Home.tsx",
      errors: [{ messageId: "rawElement" }],
    },
  ],
});
