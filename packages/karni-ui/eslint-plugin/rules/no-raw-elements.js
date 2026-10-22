/**
 * karni/no-raw-elements — raw data-entry/table JSX elements are banned in
 * project code; @karni/ui is their only home. Each message names the
 * component to compose instead.
 */
import { docsUrl } from "../lib/docs.js";
import { matchesAny } from "../lib/glob.js";

const REPLACEMENTS = {
  table: "ResourceTable",
  form: "ResourceForm",
  input: "Input (or ResourceForm, which renders the right field for you)",
  select: "Select / ResourceSelect",
  textarea: "Textarea (or ResourceForm)",
};

export default {
  meta: {
    type: "problem",
    docs: {
      url: docsUrl("no-raw-elements"),
      description:
        "Ban raw <table>/<form>/<input>/<select>/<textarea> JSX outside @karni/ui: compose the shipped components instead of rebuilding them.",
    },
    schema: [
      {
        type: "object",
        properties: {
          allow: {
            type: "array",
            items: { type: "string" },
            description: "Glob patterns of file paths where raw elements are allowed.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      rawElement:
        "Raw <{{element}}> is Karni boilerplate. Compose {{replacement}} from @karni/ui instead. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-raw-elements -- <reason>",
    },
  },

  create(context) {
    const options = context.options[0] ?? {};
    const allow = options.allow ?? [];
    if (allow.length > 0 && matchesAny(context.filename, allow)) {
      return {};
    }
    return {
      JSXOpeningElement(node) {
        if (node.name.type !== "JSXIdentifier") return;
        const element = node.name.name;
        if (!Object.hasOwn(REPLACEMENTS, element)) return;
        context.report({
          node: node.name,
          messageId: "rawElement",
          data: { element, replacement: REPLACEMENTS[element] },
        });
      },
    };
  },
};
