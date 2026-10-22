/**
 * karni/max-page-lines — page files cap at 50 physical lines. A longer page
 * is rebuilding something @karni/ui ships; reach for the component's props
 * (columns, fields, slots) instead.
 */
import { docsUrl } from "../lib/docs.js";
import { matchesAny } from "../lib/glob.js";

const DEFAULT_MAX_LINES = 50;
const DEFAULT_FILES = ["**/pages/**"];

export default {
  meta: {
    type: "problem",
    docs: {
      url: docsUrl("max-page-lines"),
      description:
        "Fail page files (default **/pages/**) with more than 50 physical lines: pages compose @karni/ui components, they do not reimplement them.",
    },
    schema: [
      {
        type: "object",
        properties: {
          maxLines: { type: "integer", minimum: 1 },
          files: {
            type: "array",
            items: { type: "string" },
            description: "Glob patterns of the files the cap applies to.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      tooLong:
        "Page file is {{count}} physical lines (max {{max}}). Past the cap you are rebuilding " +
        "something @karni/ui ships. Compose Page/ResourceTable/ResourceForm/ResourceDetail and " +
        "their props, or move logic into hooks/components. " +
        "Opt out only with an explained disable: /* eslint-disable karni/max-page-lines -- <reason> */",
    },
  },

  create(context) {
    const options = context.options[0] ?? {};
    const maxLines = options.maxLines ?? DEFAULT_MAX_LINES;
    const files = options.files ?? DEFAULT_FILES;
    if (!matchesAny(context.filename, files)) {
      return {};
    }
    return {
      Program(node) {
        const lines = context.sourceCode.lines;
        // A trailing newline produces one empty final element — not a line.
        const count = lines.at(-1) === "" ? lines.length - 1 : lines.length;
        if (count <= maxLines) return;
        context.report({
          node,
          loc: { start: { line: 1, column: 0 }, end: { line: 1, column: 0 } },
          messageId: "tooLong",
          data: { count: String(count), max: String(maxLines) },
        });
      },
    };
  },
};
