#!/usr/bin/env node
/**
 * Prints @karni/ui's public surface as JSON, read with the TypeScript
 * compiler from the package's own barrel (packages/karni-ui/src/index.ts).
 * scripts/gen_reference.py calls this; it is not meant to be run alone.
 *
 * For every value export, in barrel order:
 *   name, kind (component | hook | function | constant), source file,
 *   summary (the first sentence of its JSDoc), and
 *   - components: the required props with their types;
 *   - hooks and functions: the parameter list.
 *
 * TypeScript is resolved from packages/karni-ui/node_modules, so the output
 * follows the version pinned in that package's lockfile.
 */
import { createRequire } from "node:module";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = resolve(repo, "packages/karni-ui");
const ts = createRequire(resolve(pkg, "package.json"))("typescript");

const configPath = resolve(pkg, "tsconfig.json");
const config = ts.readConfigFile(configPath, ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, pkg);
const barrel = resolve(pkg, "src/index.ts");
const program = ts.createProgram([barrel], { ...parsed.options, noEmit: true });
const checker = program.getTypeChecker();
const source = program.getSourceFile(barrel);
if (!source) throw new Error(`cannot read ${barrel}`);

const typeText = (type) =>
  checker
    .typeToString(
      type,
      undefined,
      ts.TypeFormatFlags.NoTruncation |
        ts.TypeFormatFlags.UseFullyQualifiedType,
    )
    .replace(/import\("[^"]+"\)\./g, "")
    .replace(/\s+/g, " ");

/** The first sentence of a symbol's JSDoc, or "". */
function summary(symbol) {
  const text = ts
    .displayPartsToString(symbol.getDocumentationComment(checker))
    .trim();
  if (!text) return "";
  const paragraph = text
    .split(/\n\s*\n/)[0]
    .replace(/\s+/g, " ")
    .trim();
  const sentence = paragraph.match(/^(.+?[.!?])(\s|$)/);
  return sentence ? sentence[1] : paragraph;
}

function declarationFile(symbol) {
  const declaration = symbol.declarations?.[0];
  return declaration
    ? relative(repo, declaration.getSourceFile().fileName)
    : "";
}

/** Call signatures of a value (a function, a forwardRef/memo component). */
function signatures(symbol, node) {
  const type = checker.getTypeOfSymbolAtLocation(symbol, node);
  return type.getCallSignatures();
}

function requiredProps(signature, node) {
  const first = signature.getParameters()[0];
  if (!first) return [];
  const propsType = checker.getTypeOfSymbolAtLocation(first, node);
  return checker
    .getPropertiesOfType(propsType)
    .filter((prop) => !(prop.flags & ts.SymbolFlags.Optional))
    .map((prop) => ({
      name: prop.getName(),
      type: typeText(checker.getTypeOfSymbolAtLocation(prop, node)),
    }));
}

function parameters(signature, node) {
  return signature.getParameters().map((param) => {
    const declaration = param.valueDeclaration;
    const optional =
      declaration &&
      ts.isParameter(declaration) &&
      (declaration.questionToken || declaration.initializer);
    return `${param.getName()}${optional ? "?" : ""}: ${typeText(checker.getTypeOfSymbolAtLocation(param, node))}`;
  });
}

const NON_COMPONENTS = new Set(["KarniApiError"]);
const out = [];
for (const statement of source.statements) {
  if (
    !ts.isExportDeclaration(statement) ||
    statement.isTypeOnly ||
    !statement.exportClause
  )
    continue;
  if (!ts.isNamedExports(statement.exportClause)) continue;
  for (const element of statement.exportClause.elements) {
    if (element.isTypeOnly) continue;
    const name = element.name.text;
    const local = checker.getSymbolAtLocation(element.name);
    const symbol =
      local && local.flags & ts.SymbolFlags.Alias
        ? checker.getAliasedSymbol(local)
        : local;
    if (!symbol) continue;
    const calls = signatures(symbol, element);
    let kind = "constant";
    if (/^use[A-Z]/.test(name)) kind = "hook";
    else if (
      /^[A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*$/.test(name) &&
      !NON_COMPONENTS.has(name) &&
      calls.length
    )
      kind = "component";
    else if (symbol.flags & ts.SymbolFlags.Class) kind = "class";
    else if (calls.length) kind = "function";
    const entry = {
      name,
      kind,
      source: declarationFile(symbol),
      summary: summary(symbol),
    };
    if (kind === "component") entry.required = requiredProps(calls[0], element);
    if (kind === "hook" || kind === "function")
      entry.parameters = parameters(calls[0], element);
    out.push(entry);
  }
}
process.stdout.write(JSON.stringify(out, null, 2) + "\n");
