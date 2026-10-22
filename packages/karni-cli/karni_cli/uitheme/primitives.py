"""The primitive registry for a shadcn/ui project: ``karni-primitives.tsx``.

Karni's components look every primitive up in ``<KarniProvider primitives>``
before rendering. For each role whose shadcn component exists (and exports
the expected name), the generated file registers it; the ``select`` family
only when all eight parts are exported and the file is built on Radix (Karni's
select contract). Components built on Base UI or React Aria take different
props, so they are reported, not registered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from karni_cli.uitheme.frontend import Frontend
from karni_cli.uitheme.model import Unmapped
from karni_cli.uitheme.shadcn import ShadcnConfig

#: role -> (shadcn file stem, exported component)
ROLES: dict[str, tuple[str, str]] = {
    "button": ("button", "Button"),
    "input": ("input", "Input"),
    "textarea": ("textarea", "Textarea"),
    "checkbox": ("checkbox", "Checkbox"),
    "switch": ("switch", "Switch"),
    "label": ("label", "Label"),
    "skeleton": ("skeleton", "Skeleton"),
}
#: Karni's select part -> shadcn's export (select.tsx).
SELECT_PARTS: dict[str, str] = {
    "Root": "Select",
    "Trigger": "SelectTrigger",
    "Value": "SelectValue",
    "Content": "SelectContent",
    "Item": "SelectItem",
    "Group": "SelectGroup",
    "Label": "SelectLabel",
    "Separator": "SelectSeparator",
}
#: Roles whose Karni contract is Radix's component API.
RADIX_ROLES = frozenset({"checkbox", "switch", "select"})

_OTHER_LIBRARIES = re.compile(
    r"""from\s+["'](@base-ui[^"']*|@base-ui-components[^"']*|react-aria-components|"""
    r"""react-aria|@ark-ui[^"']*|@headlessui[^"']*)["']"""
)
_RADIX = re.compile(r"""from\s+["'](radix-ui|@radix-ui/[^"']+)["']""")
_EXPORT_DECL = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_LIST = re.compile(r"export\s*(?:type\s*)?\{([^}]*)\}")


def exported_names(source: str) -> set[str]:
    names = set(_EXPORT_DECL.findall(source))
    for group in _EXPORT_LIST.findall(source):
        for item in group.split(","):
            item = item.strip()
            if not item or item.startswith("type "):
                continue
            names.add(item.split(" as ")[-1].strip())
    return names


@dataclass
class PrimitivePlan:
    ui_alias: str
    ui_dir: Path
    tsx: bool
    #: (role, module specifier, imported names)
    roles: list[tuple[str, str, list[str]]] = field(default_factory=list)
    missing: list[Unmapped] = field(default_factory=list)

    @property
    def registered(self) -> list[str]:
        return [role for role, _, _ in self.roles]

    @property
    def suffix(self) -> str:
        return ".tsx" if self.tsx else ".jsx"


def _component_file(ui_dir: Path, stem: str) -> Path | None:
    for suffix in (".tsx", ".jsx", ".ts", ".js"):
        path = ui_dir / f"{stem}{suffix}"
        if path.is_file():
            return path
    index = ui_dir / stem / "index.tsx"
    return index if index.is_file() else None


def _library_problem(role: str, source: str, rel: str) -> str | None:
    other = _OTHER_LIBRARIES.search(source)
    if other:
        return (
            f"{rel} is built on {other.group(1)}, whose props differ from Karni's {role} "
            "contract (Radix-style props). Register an adapter by hand"
        )
    if role in RADIX_ROLES and not _RADIX.search(source):
        return (
            f"{rel} does not import Radix. Karni's {role} contract is Radix's props, so "
            "register an adapter by hand"
        )
    return None


def plan(frontend: Frontend, config: ShadcnConfig) -> PrimitivePlan | Unmapped:
    """What karni-primitives.tsx registers, or why it cannot be generated."""
    alias = config.ui_alias
    if not alias:
        return Unmapped(
            "components.json aliases.ui",
            "components.json names no ui (or components) alias, so the shadcn/ui components "
            "cannot be found",
        )
    ui_dir = frontend.resolve_alias(alias)
    if ui_dir is None or not ui_dir.is_dir():
        return Unmapped(
            f"components.json aliases.ui ({alias})",
            "the alias does not resolve to a directory (tsconfig compilerOptions.paths)",
        )
    result = PrimitivePlan(alias, ui_dir, config.tsx)
    for role, (stem, component) in ROLES.items():
        path = _component_file(ui_dir, stem)
        if path is None:
            result.missing.append(
                Unmapped(role, f"no {alias}/{stem} (npx shadcn@latest add {stem})")
            )
            continue
        source = frontend.read(path)
        rel = frontend.rel(path)
        if component not in exported_names(source):
            result.missing.append(Unmapped(role, f"{rel} does not export {component}"))
            continue
        problem = _library_problem(role, source, rel)
        if problem:
            result.missing.append(Unmapped(role, problem))
            continue
        result.roles.append((role, f"{alias}/{stem}", [component]))

    path = _component_file(ui_dir, "select")
    if path is None:
        result.missing.append(
            Unmapped("select", f"no {alias}/select (npx shadcn@latest add select)")
        )
        return result
    source = frontend.read(path)
    rel = frontend.rel(path)
    exported = exported_names(source)
    absent = [name for name in SELECT_PARTS.values() if name not in exported]
    if absent:
        result.missing.append(
            Unmapped(
                "select",
                f"{rel} does not export {', '.join(absent)}. The select family is registered "
                "whole or not at all (Radix parts share one context)",
            )
        )
        return result
    problem = _library_problem("select", source, rel)
    if problem:
        result.missing.append(Unmapped("select", problem))
        return result
    result.roles.append(("select", f"{alias}/select", list(SELECT_PARTS.values())))
    return result


def render_body(result: PrimitivePlan) -> str:
    lines: list[str] = []
    if result.tsx:
        lines.append('import type { KarniPrimitiveOverrides } from "@karni/ui";')
    for _, module, names in result.roles:
        if len(names) == 1:
            lines.append(f'import {{ {names[0]} }} from "{module}";')
        else:
            lines.append("import {")
            lines += [f"  {name}," for name in sorted(names)]
            lines.append(f'}} from "{module}";')
    lines.append("")
    annotation = ": KarniPrimitiveOverrides" if result.tsx else ""
    lines.append(f"export const primitives{annotation} = {{")
    for role, _, names in result.roles:
        if role == "select":
            lines.append("  select: {")
            lines += [f"    {part}: {name}," for part, name in SELECT_PARTS.items()]
            lines.append("  },")
        else:
            lines.append(f"  {role}: {names[0]},")
    lines.append("};")
    return "\n".join(lines) + "\n"
