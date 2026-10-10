/**
 * karni/no-direct-http — direct HTTP/WS clients (fetch, axios,
 * XMLHttpRequest, new WebSocket) are banned outside the generated client
 * directory (allowPatterns, default **-slash-api). Data access goes through
 * the generated typed hooks and the KarniClient from @karni/ui.
 */
import { docsUrl } from "../lib/docs.js";
import { matchesAny } from "../lib/glob.js";

const DEFAULT_ALLOW_PATTERNS = ["**/api/**"];
const GLOBAL_OBJECTS = new Set(["window", "globalThis", "self"]);

/** True when `name` resolves to a declared (shadowing) binding in scope. */
function isShadowed(sourceCode, node, name) {
  let scope = sourceCode.getScope(node);
  while (scope) {
    const variable = scope.set.get(name);
    if (variable && variable.defs.length > 0) return true;
    scope = scope.upper;
  }
  return false;
}

/** Matches `fetch(...)`, `window.fetch(...)`, `globalThis.fetch(...)`. */
function calleeIsGlobal(sourceCode, callee, name) {
  if (callee.type === "Identifier" && callee.name === name) {
    return !isShadowed(sourceCode, callee, name);
  }
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    GLOBAL_OBJECTS.has(callee.object.name) &&
    callee.property.type === "Identifier" &&
    callee.property.name === name
  ) {
    return true;
  }
  return false;
}

function checkAxiosSource(context, sourceNode) {
  if (!sourceNode || sourceNode.type !== "Literal") return;
  if (typeof sourceNode.value !== "string") return;
  if (sourceNode.value !== "axios" && !sourceNode.value.startsWith("axios/")) return;
  context.report({ node: sourceNode, messageId: "axios" });
}

export default {
  meta: {
    type: "problem",
    docs: {
      url: docsUrl("no-direct-http"),
      description:
        "Ban fetch/axios/XMLHttpRequest/new WebSocket outside the generated api client directory: use the generated typed hooks or KarniClient.",
    },
    schema: [
      {
        type: "object",
        properties: {
          allowPatterns: {
            type: "array",
            items: { type: "string" },
            description:
              "Glob patterns of file paths where direct HTTP is allowed (the generated client's home).",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      fetch:
        "Direct fetch() outside the api client directory. Use the generated typed hooks " +
        "(useResourceList/useResourceItem/useResourceMutations) or the KarniClient from " +
        "@karni/ui — raw HTTP lives only under the allowed api/ paths. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-direct-http -- <reason>",
      axios:
        "Do not add axios. Karni already ships an HTTP layer: the generated typed hooks and " +
        "createKarniClient from @karni/ui. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-direct-http -- <reason>",
      xhr:
        "XMLHttpRequest outside the api client directory. Use the generated typed hooks or " +
        "the KarniClient from @karni/ui instead. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-direct-http -- <reason>",
      websocket:
        "new WebSocket() outside the api client directory. Wrap realtime transports in the " +
        "api/ layer next to the KarniClient so every consumer shares one implementation. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-direct-http -- <reason>",
    },
  },

  create(context) {
    const options = context.options[0] ?? {};
    const allowPatterns = options.allowPatterns ?? DEFAULT_ALLOW_PATTERNS;
    if (matchesAny(context.filename, allowPatterns)) {
      return {};
    }
    const { sourceCode } = context;
    return {
      CallExpression(node) {
        if (calleeIsGlobal(sourceCode, node.callee, "fetch")) {
          context.report({ node, messageId: "fetch" });
          return;
        }
        if (node.callee.type === "Identifier" && node.callee.name === "require") {
          checkAxiosSource(context, node.arguments[0]);
        }
      },
      NewExpression(node) {
        if (calleeIsGlobal(sourceCode, node.callee, "XMLHttpRequest")) {
          context.report({ node, messageId: "xhr" });
        } else if (calleeIsGlobal(sourceCode, node.callee, "WebSocket")) {
          context.report({ node, messageId: "websocket" });
        }
      },
      ImportDeclaration(node) {
        checkAxiosSource(context, node.source);
      },
      ImportExpression(node) {
        checkAxiosSource(context, node.source);
      },
    };
  },
};
