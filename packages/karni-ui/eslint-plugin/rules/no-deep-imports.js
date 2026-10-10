/**
 * karni/no-deep-imports — importing @karni/ui internals (dist/, src/) is
 * banned. Deep imports are how component code gets vendored and forked;
 * compose the public API instead, and if it does not fit, extend it through
 * its props/overrides (or upstream the change).
 */
import { docsUrl } from "../lib/docs.js";
const DEEP_IMPORT = /^@karni\/ui\/(?:dist|src)(?:\/|$)/;

function checkSource(context, sourceNode) {
  if (!sourceNode || sourceNode.type !== "Literal") return;
  if (typeof sourceNode.value !== "string") return;
  if (!DEEP_IMPORT.test(sourceNode.value)) return;
  context.report({
    node: sourceNode,
    messageId: "deepImport",
    data: { source: sourceNode.value },
  });
}

export default {
  meta: {
    type: "problem",
    docs: {
      url: docsUrl("no-deep-imports"),
      description:
        "Ban imports from @karni/ui/dist/* and @karni/ui/src/*: compose the public API, never vendor a copy of an internal.",
    },
    schema: [],
    messages: {
      deepImport:
        'Deep import "{{source}}" reaches into @karni/ui internals. Import from the public ' +
        'barrel "@karni/ui" and compose/extend the exported component — vendoring an internal ' +
        "copy forks it. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-deep-imports -- <reason>",
    },
  },

  create(context) {
    return {
      ImportDeclaration(node) {
        checkSource(context, node.source);
      },
      ExportNamedDeclaration(node) {
        checkSource(context, node.source);
      },
      ExportAllDeclaration(node) {
        checkSource(context, node.source);
      },
      ImportExpression(node) {
        checkSource(context, node.source);
      },
      CallExpression(node) {
        if (node.callee.type === "Identifier" && node.callee.name === "require") {
          checkSource(context, node.arguments[0]);
        }
      },
    };
  },
};
