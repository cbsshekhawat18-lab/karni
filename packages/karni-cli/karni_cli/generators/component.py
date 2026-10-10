"""``karni make component <Name>`` — a React component that claims a role.

Every component registers its semantic role (``registerComponentRole`` from
@karni/ui), so two components doing the same job fail loudly instead of
drifting apart (K303: extend, never fork). A role @karni/ui or the project
already claims is refused; replacing one on purpose takes ``--replace-reason``.
"""

from __future__ import annotations

import json
import re

import typer

from karni_cli.commands.context import find_manifest
from karni_cli.generators.core import (
    DRY_RUN_OPTION,
    FORCE_OPTION,
    FRONTEND,
    Workspace,
    project_workspace,
    require_frontend,
)
from karni_cli.generators.naming import kebab, require_kebab, require_pascal
from karni_cli.project import CliError

NAME = "component"
SUMMARY = "Add a React component that claims a role (registerComponentRole)."

COMPONENTS = FRONTEND / "src" / "components"
_REGISTERED = re.compile(r"""registerComponentRole\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']""")


def _claimed(ws: Workspace, skip: str) -> dict[str, str]:
    """``role -> owner`` from the @karni/ui manifest and the project's own sources."""
    claimed: dict[str, str] = {}
    manifest = find_manifest(ws.root, None)
    if manifest is not None:
        try:
            roles = json.loads(manifest.read_text()).get("roles") or {}
        except (OSError, json.JSONDecodeError):
            roles = {}
        claimed.update({role: f"@karni/ui's {owner}" for role, owner in roles.items()})
    else:
        ws.note("note: @karni/ui is not installed — its roles could not be checked.")
    src = ws.path(FRONTEND / "src")
    if src.is_dir():
        for path in sorted(src.rglob("*.ts*")):
            if "node_modules" in path.parts or ws.rel(path) == skip:
                continue
            text = ws.read(path) or ""
            for role, owner in _REGISTERED.findall(text):
                claimed[role] = f"{owner} ({ws.rel(path)})"
    return claimed


def plan(ws: Workspace, name: str, *, role: str | None, replace_reason: str | None) -> str:
    require_frontend(ws)
    component = require_pascal(name, "Component name")
    role = require_kebab(role or kebab(component), "--role")
    target = COMPONENTS / f"{component}.tsx"
    owner = _claimed(ws, ws.rel(ws.path(target))).get(role)
    options = ""
    if owner is not None:
        if not replace_reason:
            raise CliError(
                f"Role {role!r} is already claimed by {owner}. Compose or extend it instead "
                "(K303), pick another --role, or replace it on purpose with "
                '--replace-reason "<why>".',
                code="C107",
            )
        reason = json.dumps(replace_reason)
        options = f", {{ replace: true, reason: {reason} }}"
    elif replace_reason:
        raise CliError(f"--replace-reason: no component claims role {role!r} yet.", code="C106")
    source = (
        'import type { ReactNode } from "react";\n'
        'import { registerComponentRole } from "@karni/ui";\n'
        "\n"
        f'registerComponentRole("{role}", "{component}"{options});\n'
        "\n"
        f"export interface {component}Props {{\n"
        "    children?: ReactNode;\n"
        "}\n"
        "\n"
        f"export function {component}({{ children }}: {component}Props) {{\n"
        "    return <div>{children}</div>;\n"
        "}\n"
    )
    ws.create(target, source)
    ws.note(f"role: {role} -> {component}")
    return role


def command(
    name: str = typer.Argument(..., help="Component name, PascalCase (e.g. StatusBadge)."),
    role: str | None = typer.Option(
        None, "--role", help="Semantic role it claims (default: kebab-case of NAME)."
    ),
    replace_reason: str | None = typer.Option(
        None, "--replace-reason", help="Take over a role another component claims, saying why."
    ),
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add frontend/src/components/NAME.tsx, registered with registerComponentRole.

    A role already claimed by @karni/ui (its manifest) or by another project
    component is refused — compose that component instead, or pass
    --replace-reason to replace it on purpose.
    """
    ws = project_workspace(force)
    plan(ws, name, role=role, replace_reason=replace_reason)
    ws.commit(dry_run=dry_run)
