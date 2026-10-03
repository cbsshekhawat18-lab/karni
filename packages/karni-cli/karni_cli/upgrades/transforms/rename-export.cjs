/**
 * jscodeshift transform: rename one named export of a module at every use site.
 *
 * Driven by data (karni_cli.upgrades.typescript.RenameExport), never edited
 * per change. Options:
 *   --karni-module=@karni/ui  --karni-from=OldName  --karni-to=NewName
 *
 *   import { Old } from "mod"         -> import { New } from "mod"   (+ every reference)
 *   import { Old as X } from "mod"    -> import { New as X } from "mod"
 *   export { Old } from "mod"         -> export { New as Old } from "mod"  (your export keeps its name)
 *
 * References are renamed only where `Old` resolves to the module-level
 * import, so a local variable or parameter that shadows it is left alone,
 * as are object keys and member names. Reports `karni-count <n>` per file.
 */
module.exports = function renameExport(file, api, options) {
  const j = api.jscodeshift;
  const mod = options["karni-module"];
  const from = options["karni-from"];
  const to = options["karni-to"];
  if (!mod || !from || !to) {
    throw new Error("rename-export needs --karni-module, --karni-from and --karni-to");
  }
  const root = j(file.source);
  const program = root.find(j.Program).paths()[0];
  const bindsToImport = (path) => path.scope != null && path.scope.lookup(from) === program.scope;

  const specifiers = [];
  let unaliased = false;
  root.find(j.ImportDeclaration, { source: { value: mod } }).forEach((path) => {
    for (const spec of path.node.specifiers || []) {
      if (spec.type !== "ImportSpecifier" || spec.imported.name !== from) continue;
      specifiers.push(spec);
      if (!spec.local || spec.local.name === from) unaliased = true;
    }
  });

  // Collect references before renaming anything: scope lookups use the old name.
  // A Set: the AST walk can reach one JSX tag name through two paths.
  const references = new Set();
  if (unaliased) {
    root
      .find(j.Identifier, { name: from })
      .filter((path) => {
        const parent = path.parent.node;
        if (parent.type === "ImportSpecifier" || parent.type === "ExportSpecifier") return false;
        const member =
          parent.type === "MemberExpression" || parent.type === "OptionalMemberExpression";
        if (member && parent.property === path.node && !parent.computed) return false;
        const keyed =
          parent.type === "Property" ||
          parent.type === "ObjectProperty" ||
          parent.type === "ClassProperty" ||
          parent.type === "TSPropertySignature";
        if (keyed && parent.key === path.node && !parent.computed) return false;
        if (parent.type === "TSQualifiedName" && parent.right === path.node) return false;
        return bindsToImport(path);
      })
      .forEach((path) => references.add(path.node));
    root
      .find(j.JSXIdentifier, { name: from })
      .filter((path) => {
        const parent = path.parent.node;
        const tag =
          parent.type === "JSXOpeningElement" ||
          parent.type === "JSXClosingElement" ||
          (parent.type === "JSXMemberExpression" && parent.object === path.node);
        return tag && bindsToImport(path);
      })
      .forEach((path) => references.add(path.node));
  }

  let count = 0;
  for (const spec of specifiers) {
    const aliased = spec.local && spec.local.name !== from;
    spec.imported = j.identifier(to);
    if (!aliased) spec.local = j.identifier(to);
    count += 1;
  }
  for (const node of references) {
    node.name = to;
    count += 1;
  }
  root.find(j.ExportNamedDeclaration, { source: { value: mod } }).forEach((path) => {
    path.node.specifiers = (path.node.specifiers || []).map((spec) => {
      if (spec.type !== "ExportSpecifier" || spec.local.name !== from) return spec;
      count += 1;
      const exported = spec.exported ? spec.exported.name : from;
      return j.exportSpecifier.from({ local: j.identifier(to), exported: j.identifier(exported) });
    });
  });

  if (count === 0) return null;
  api.report(`karni-count ${count}`);
  return root.toSource();
};
