/**
 * RuleTester suite for karni/max-page-lines (ESLint 9 under vitest).
 */
import { RuleTester } from "eslint";

import rule from "./rules/max-page-lines.js";

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: "latest", sourceType: "module" },
});

/** @param {number} count @returns {string} a file with `count` physical lines */
function fileOfLines(count) {
  return Array.from({ length: count }, (_, i) => `const line${i} = ${i};`).join("\n") + "\n";
}

ruleTester.run("max-page-lines", rule, {
  valid: [
    // Exactly at the cap (the trailing newline is not a 51st line).
    { code: fileOfLines(50), filename: "/app/frontend/src/pages/Home.tsx" },
    // Over the cap but not a page file.
    { code: fileOfLines(80), filename: "/app/frontend/src/components/Big.tsx" },
    // Custom cap.
    {
      code: fileOfLines(60),
      options: [{ maxLines: 60 }],
      filename: "/app/frontend/src/pages/Home.tsx",
    },
    // Custom file patterns exclude the default pages dir.
    {
      code: fileOfLines(80),
      options: [{ files: ["**/screens/**"] }],
      filename: "/app/frontend/src/pages/Home.tsx",
    },
  ],
  invalid: [
    {
      code: fileOfLines(51),
      filename: "/app/frontend/src/pages/Home.tsx",
      errors: [{ messageId: "tooLong", data: { count: "51", max: "50" } }],
    },
    {
      code: fileOfLines(4),
      options: [{ maxLines: 3 }],
      filename: "/app/frontend/src/pages/Home.tsx",
      errors: [{ messageId: "tooLong" }],
    },
    {
      code: fileOfLines(10),
      options: [{ maxLines: 5, files: ["**/screens/**"] }],
      filename: "/app/frontend/src/screens/Detail.tsx",
      errors: [{ messageId: "tooLong" }],
    },
  ],
});
