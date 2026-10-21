/**
 * karni/no-style-literals — every visual value resolves from a design token.
 *
 * @karni/ui's preset maps Tailwind's scales (colours, spacing, type, radius,
 * shadow, stacking, opacity, motion) onto --karni-* custom properties, so a
 * project retheming those properties retheming every component. A class
 * outside those scales compiles to a literal the theme cannot reach: an
 * arbitrary value (`w-[13px]`, `bg-[#fff]`), Tailwind's palette
 * (`bg-slate-500`), an opacity modifier on a colour (`bg-primary/90`), a step
 * the spacing scale does not have, or a literal in an inline style.
 *
 * The rule checks the whitespace-separated class tokens of every string in
 * the file and the values of inline `style={{ ... }}` objects. Computed style
 * values (data-driven widths, percentages) are allowed: only literals fail.
 */
import { docsUrl } from "../lib/docs.js";

/** The preset's spacing steps (keep in sync with SPACE_STEPS in tailwind-preset.ts). */
const SPACE_STEPS = new Set([
  "0",
  "px",
  "0.5",
  "1",
  "1.5",
  "2",
  "2.5",
  "3",
  "3.5",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "10",
  "11",
  "12",
  "14",
  "16",
  "20",
  "24",
  "28",
  "32",
  "36",
  "40",
  "44",
  "48",
  "52",
  "56",
  "60",
  "64",
  "72",
  "80",
  "96",
  "128",
]);

const SPACING_UTILITY =
  /^-?(?:p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]|w|h|size|min-w|min-h|max-w|max-h|inset(?:-[xy])?|top|right|bottom|left|start|end|translate-[xy]|scroll-[mp][xytrblse]?|basis|indent)-(\d+(?:\.\d+)?)$/;

const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|black|white";
const COLOR_UTILITY =
  "bg|text|border(?:-[xytrblse])?|ring|ring-offset|outline|fill|stroke|from|via|to|divide|placeholder|decoration|accent|caret|shadow";
const PALETTE_CLASS = new RegExp(`^(?:${COLOR_UTILITY})-(?:${PALETTE})(?:-\\d+)?(?:/\\d+)?$`);
const OPACITY_MODIFIER = new RegExp(`^(?:${COLOR_UTILITY})-[a-z][\\w-]*/\\d+$`);

/** Classes whose value comes from Tailwind's default theme, not a --karni-* token. */
const UNMAPPED = [
  [
    /^max-w-(?:xs|sm|md|lg|xl|[2-7]xl|prose|screen-\w+)$/,
    "a named max-width (use a spacing step, e.g. max-w-96)",
  ],
  [/^text-(?:[3-9]xl)$/, "a type size outside the --karni-font-size-* scale (xs to 2xl)"],
  [/^-?z-\d+$/, "a numeric z-index (use z-raised, z-drawer, z-popover, z-modal or z-toast)"],
  [/^opacity-(?!(?:0|50|60|70|90|100)$)\d+$/, "an opacity outside the --karni-opacity-* steps"],
  [/^(?:duration|delay)-\d+$/, "a literal duration (transitions read --karni-duration)"],
  [
    /^rounded(?:-[tblrse]{1,2})?-(?:2xl|3xl)$/,
    "a radius outside --karni-radius-* (sm to xl, full)",
  ],
  [/^shadow-(?:xl|2xl|inner)$/, "a shadow outside --karni-shadow-* (sm, md, lg)"],
  [/^font-(?:thin|extralight|light|extrabold|black)$/, "a weight outside --karni-font-weight-*"],
  [/^leading-(?!none$)[\w.]+$/, "a line height outside the type scale"],
  [/^tracking-(?:tighter|wider|widest|normal)$/, "letter spacing outside --karni-font-tracking-*"],
  [
    /^(?:border(?:-[xytrblse])?|ring-offset|outline)-(?!0$|2$)\d+$/,
    "a line width outside --karni-border-width / --karni-ring-*",
  ],
  [/^ring-(?!0$|1$|2$)\d+$/, "a ring width outside --karni-ring-width*"],
  [/^underline-offset-(?!4$)\d+$/, "an underline offset outside --karni-font-underline-offset"],
  [/^divide-[xy](?:-\d+)?$/, "a divider whose width Tailwind 4 hard-codes (use [&>*+*]:border-t)"],
];

const HEX = /#[0-9a-fA-F]{3,8}\b/;
const LITERAL_IN_VALUE = /\d|#|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch|color)\(/;

/** The base utility of a class token: variants (`hover:`, `md:`, `data-[x]:`) and `!` stripped. */
function utilityOf(token) {
  let depth = 0;
  let start = 0;
  for (let i = 0; i < token.length; i += 1) {
    const ch = token[i];
    if (ch === "[") depth += 1;
    else if (ch === "]") depth -= 1;
    else if (ch === ":" && depth === 0) start = i + 1;
  }
  return token.slice(start).replace(/^!/, "");
}

/** Why `utility` is a literal, or null when it resolves from a token. */
function problemOf(utility) {
  const arbitrary = /^-?[\w-]*\[(.+)\]$/.exec(utility);
  if (arbitrary) {
    const value = arbitrary[1]
      .replace(/var\(--[\w-]+(?:,[^)]*)?\)/g, "")
      .replace(/\d+fr\b/g, "")
      .replace(/\b(?:min|max|fit)-content\b/g, "");
    return LITERAL_IN_VALUE.test(value) ? "an arbitrary literal value" : null;
  }
  if (PALETTE_CLASS.test(utility)) return "a Tailwind palette colour (use a --karni-color-* token)";
  if (OPACITY_MODIFIER.test(utility)) {
    return "an opacity modifier on a colour (use a token such as bg-primary-hover or bg-muted-subtle)";
  }
  const spacing = SPACING_UTILITY.exec(utility);
  if (spacing && !SPACE_STEPS.has(spacing[1]))
    return "a step the --karni-space-* scale does not have";
  for (const [pattern, why] of UNMAPPED) if (pattern.test(utility)) return why;
  return null;
}

function checkClasses(context, node, text) {
  if (HEX.test(text)) {
    context.report({
      node,
      messageId: "literal",
      data: { value: HEX.exec(text)[0], why: "a hex colour" },
    });
  }
  for (const token of text.split(/\s+/)) {
    if (!token) continue;
    const why = problemOf(utilityOf(token));
    if (why) context.report({ node, messageId: "literal", data: { value: token, why } });
  }
}

function literalStyleValue(node) {
  if (node.type === "Literal") {
    if (typeof node.value === "number") return node.value !== 0;
    return (
      typeof node.value === "string" &&
      LITERAL_IN_VALUE.test(node.value.replace(/var\(--[\w-]+\)/g, ""))
    );
  }
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    return LITERAL_IN_VALUE.test(node.quasis[0].value.cooked ?? "");
  }
  return false;
}

export default {
  meta: {
    type: "problem",
    docs: {
      url: docsUrl("no-style-literals"),
      description:
        "Every visual value resolves from a --karni-* token: no arbitrary literal values, palette colours, colour opacity modifiers or literal inline styles.",
    },
    schema: [],
    messages: {
      literal:
        '"{{value}}" is {{why}}: the theme cannot reach it. Use a class from the @karni/ui preset ' +
        "(it resolves from --karni-* tokens), or add a token to styles.css and the preset. " +
        "Opt out only with an explained disable: " +
        "// eslint-disable-next-line karni/no-style-literals -- <reason>",
    },
  },

  create(context) {
    return {
      Literal(node) {
        if (typeof node.value !== "string") return;
        if (
          node.parent?.type === "ImportDeclaration" ||
          node.parent?.type === "ExportNamedDeclaration"
        )
          return;
        if (node.parent?.type === "Property" && node.parent.key === node) return;
        if (insideStyleObject(node)) return;
        checkClasses(context, node, node.value);
      },
      TemplateElement(node) {
        if (insideStyleObject(node)) return;
        checkClasses(context, node, node.value.cooked ?? "");
      },
      JSXAttribute(node) {
        if (node.name.name !== "style") return;
        const expression =
          node.value?.type === "JSXExpressionContainer" ? node.value.expression : null;
        if (expression?.type !== "ObjectExpression") return;
        for (const property of expression.properties) {
          if (property.type === "Property" && literalStyleValue(property.value)) {
            context.report({
              node: property.value,
              messageId: "literal",
              data: { value: context.sourceCode.getText(property), why: "a literal inline style" },
            });
          }
        }
      },
    };
  },
};

/** Inline style values are checked by the JSXAttribute visitor, not as class strings. */
function insideStyleObject(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (current.type === "JSXAttribute") return current.name.name === "style";
    if (current.type === "JSXElement" || current.type === "Program") return false;
  }
  return false;
}
