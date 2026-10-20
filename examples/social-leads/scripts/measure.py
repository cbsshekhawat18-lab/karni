"""Count the leads/CRM module before (Social Stats) and after (this Karni rebuild).

    python scripts/measure.py --before <social-stats checkout> [--pristine <karni new output>]
                              [--normalise]

Counted: non-blank, non-comment lines — a line is skipped when it is empty or
starts with ``#``, ``//``, ``/*``, ``*`` or ``\"\"\"`` (the rule EventHub's
scripts/loc.py uses). Migrations, lockfiles, generated API types and the
scaffold ``karni new`` writes are left out. A scaffold file the rebuild edited
(config/settings.py, frontend/src/routes.tsx) counts only the lines it added,
measured against ``--pristine`` (a fresh ``karni new "Social Leads"``);
without it those files count whole, which overstates the rebuild.

The "before" boundary is the module as Social Stats ships it: the Lead and
LeadActivity models, their three serializers, lead_views.py, the router
line, the two lead pages, the leadAPI client block, the two routes and the
sidebar entry. Shared code the module leans on (TenantScopedMixin, the
api.js axios instance, the design tokens) is not counted on either side.

Line counts follow formatting, and the two code bases are formatted
differently (Social Stats is styled by hand; the rebuild's Python is ruff's).
``--normalise`` counts copies of both sides after the same formatters with
their defaults: ``ruff format`` (88 columns) for Python, Prettier (80
columns) for JavaScript and TypeScript. Prettier is found through
``$PRETTIER``, else ``npx prettier``; ruff through ``python -m ruff``.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
COMMENT = ("#", "//", "/*", "*", '"""')


def code_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith(COMMENT)
    ]


def count(text: str) -> int:
    return len(code_lines(text))


def classes(path: Path, names: set[str]) -> int:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    total = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name in names:
            total += count("\n".join(lines[node.lineno - 1 : node.end_lineno]))
    return total


def matching(path: Path, pattern: str) -> int:
    return sum(
        1 for line in code_lines(path.read_text(encoding="utf-8")) if re.search(pattern, line)
    )


def js_block(path: Path, start: str) -> int:
    """Lines of a top-level ``export const NAME = { ... };`` block."""
    lines = path.read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i in range(first, len(lines)) if lines[i].startswith("};"))
    return count("\n".join(lines[first : last + 1]))


def added(path: Path, pristine: Path | None, rel: str) -> int:
    ours = code_lines(path.read_text(encoding="utf-8"))
    if pristine is None or not (pristine / rel).is_file():
        return len(ours)
    theirs = code_lines((pristine / rel).read_text(encoding="utf-8"))
    return sum(1 for line in difflib.ndiff(theirs, ours) if line.startswith("+ "))


def before(root: Path) -> dict[str, int]:
    app = root / "backend" / "social_stats"
    fe = root / "frontend" / "src"
    return {
        "models": classes(app / "bot_models.py", {"Lead", "LeadActivity"}),
        "serializers": classes(
            app / "bot_serializers.py",
            {"LeadActivitySerializer", "LeadListSerializer", "LeadDetailSerializer"},
        ),
        "views / viewsets": count((app / "lead_views.py").read_text(encoding="utf-8")),
        "services (pipeline logic)": 0,  # it lives inside lead_views.py
        "permission code (module-specific)": 0,  # TenantScopedMixin is shared
        "urls": matching(app / "urls.py", r"LeadViewSet|lead_views"),
        "admin": matching(app / "admin.py", r"\bLead\b|LeadActivity"),
        "settings": 0,
        "frontend pages": sum(
            count(p.read_text(encoding="utf-8"))
            for p in sorted((fe / "pages" / "leads").glob("*.jsx"))
        ),
        "frontend components and hooks": js_block(
            fe / "services" / "api.js", "export const leadAPI"
        ),
        "frontend routes and navigation": matching(fe / "App.js", r"LeadsPage|LeadDetailPage")
        + matching(fe / "components" / "shell" / "FeatureSidebar.jsx", r"/admin/leads"),
        "tests (dedicated to the module)": 0,
    }


def after(root: Path, pristine: Path | None) -> dict[str, int]:
    crm = root / "crm"
    fe = root / "frontend" / "src"
    pages = ("leads.tsx", "lead-detail.tsx", "lead-form.tsx")
    return {
        "models": classes(crm / "models.py", {"Lead", "LeadActivity"}),
        "serializers": sum(
            count(p.read_text(encoding="utf-8")) for p in crm.glob("serializers*.py")
        ),
        "views / viewsets": count((crm / "viewsets.py").read_text(encoding="utf-8")),
        "services (pipeline logic)": count((crm / "services.py").read_text(encoding="utf-8")),
        # A custom scope, when the project has one; membership through
        # Karni.owner_field paths is counted with the models.
        "permission code (module-specific)": sum(
            count(p.read_text(encoding="utf-8")) for p in crm.glob("scopes*.py")
        )
        + matching(crm / "apps.py", r"register_scope|def ready"),
        "urls": sum(count(p.read_text(encoding="utf-8")) for p in crm.glob("urls*.py")),
        "admin": sum(count(p.read_text(encoding="utf-8")) for p in crm.glob("admin*.py")),
        "settings": added(root / "config" / "settings.py", pristine, "config/settings.py"),
        "frontend pages": sum(
            count((fe / "pages" / name).read_text(encoding="utf-8")) for name in pages
        ),
        "frontend components and hooks": sum(
            count(p.read_text(encoding="utf-8")) for p in sorted((fe / "components").glob("*.ts*"))
        ),
        "frontend routes and navigation": added(
            fe / "routes.tsx", pristine, "frontend/src/routes.tsx"
        )
        - added_for(fe / "routes.tsx", pristine, "login"),
        "tests (dedicated to the module)": sum(
            count(p.read_text(encoding="utf-8")) for p in sorted((crm / "tests").glob("test_*.py"))
        ),
    }


def added_for(path: Path, pristine: Path | None, needle: str) -> int:
    """Added routes.tsx lines that belong to another page (the app-wide login)."""
    ours = code_lines(path.read_text(encoding="utf-8"))
    theirs = (
        code_lines((pristine / "frontend/src/routes.tsx").read_text(encoding="utf-8"))
        if pristine
        else []
    )
    return sum(
        1
        for line in difflib.ndiff(theirs, ours)
        if line.startswith("+ ") and needle in line.lower()
    )


def stand_ins(root: Path) -> int:
    """Workspace and Contact: models the original has elsewhere (Client, WhatsAppContact)."""
    return classes(root / "crm" / "models.py", {"Workspace", "Contact"})


BEFORE_FILES = (
    "backend/social_stats/bot_models.py",
    "backend/social_stats/bot_serializers.py",
    "backend/social_stats/lead_views.py",
    "backend/social_stats/urls.py",
    "backend/social_stats/admin.py",
    "frontend/src/pages/leads/LeadsPage.jsx",
    "frontend/src/pages/leads/LeadDetailPage.jsx",
    "frontend/src/services/api.js",
    "frontend/src/App.js",
    "frontend/src/components/shell/FeatureSidebar.jsx",
)
AFTER_GLOBS = ("crm/*.py", "crm/tests/*.py", "config/settings.py", "frontend/src/**/*.ts*")
PRISTINE_FILES = ("config/settings.py", "frontend/src/routes.tsx")


def _copy(root: Path, names: list[str], into: Path) -> None:
    for name in names:
        source = root / name
        if source.is_file():
            (into / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, into / name)


def normalised(root: Path, names: list[str]) -> Path:
    """A copy of ``names`` under ``root``, formatted by ruff and Prettier with their defaults."""
    into = Path(tempfile.mkdtemp(prefix="measure-"))
    _copy(root, names, into)
    python = [str(p) for p in into.rglob("*.py")]
    if python:
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--isolated", "--quiet", *python], check=True
        )
    scripts = [str(p) for p in into.rglob("*") if p.suffix in {".js", ".jsx", ".ts", ".tsx"}]
    if scripts:
        prettier = os.environ.get("PRETTIER")
        command = [prettier] if prettier else ["npx", "--yes", "prettier"]
        subprocess.run(
            [*command, "--no-config", "--log-level", "warn", "--write", *scripts], check=True
        )
    return into


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--pristine", type=Path)
    parser.add_argument("--normalise", action="store_true", help="format both sides alike first")
    args = parser.parse_args()
    before_root, after_root, pristine = args.before, HERE, args.pristine
    if args.normalise:
        before_root = normalised(args.before, list(BEFORE_FILES))
        after_names = sorted(
            {str(p.relative_to(HERE)) for pattern in AFTER_GLOBS for p in HERE.glob(pattern)}
        )
        after_root = normalised(HERE, after_names)
        if pristine is not None:
            pristine = normalised(pristine, list(PRISTINE_FILES))
    old, new = before(before_root), after(after_root, pristine)
    width = max(map(len, old))
    print(f"{'category':<{width}}  {'before':>7}  {'after':>6}")
    for key in old:
        print(f"{key:<{width}}  {old[key]:>7}  {new[key]:>6}")
    print(f"{'total':<{width}}  {sum(old.values()):>7}  {sum(new.values()):>6}")
    print(
        f"\nnot in the totals: Workspace + Contact stand-in models, {stand_ins(after_root)} lines"
    )


if __name__ == "__main__":
    main()
