"""Count the leads/CRM module before (Social Stats) and after (this Karni rebuild).

    python scripts/measure.py --before <social-stats checkout> [--pristine <karni new output>]

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
"""

from __future__ import annotations

import argparse
import ast
import difflib
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
COMMENT = ("#", "//", "/*", "*", '"""')


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.strip().startswith(COMMENT)]


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
    return sum(1 for line in code_lines(path.read_text(encoding="utf-8")) if re.search(pattern, line))


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
        "frontend pages": sum(count(p.read_text(encoding="utf-8")) for p in sorted((fe / "pages" / "leads").glob("*.jsx"))),
        "frontend components and hooks": js_block(fe / "services" / "api.js", "export const leadAPI"),
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
        "serializers": sum(count(p.read_text(encoding="utf-8")) for p in crm.glob("serializers*.py")),
        "views / viewsets": count((crm / "viewsets.py").read_text(encoding="utf-8")),
        "services (pipeline logic)": count((crm / "services.py").read_text(encoding="utf-8")),
        "permission code (module-specific)": count((crm / "scopes.py").read_text(encoding="utf-8"))
        + matching(crm / "apps.py", r"register_scope|workspace_rows|def ready"),
        "urls": sum(count(p.read_text(encoding="utf-8")) for p in crm.glob("urls*.py")),
        "admin": sum(count(p.read_text(encoding="utf-8")) for p in crm.glob("admin*.py")),
        "settings": added(root / "config" / "settings.py", pristine, "config/settings.py"),
        "frontend pages": sum(count((fe / "pages" / name).read_text(encoding="utf-8")) for name in pages),
        "frontend components and hooks": sum(
            count(p.read_text(encoding="utf-8")) for p in sorted((fe / "components").glob("*.ts*"))
        ),
        "frontend routes and navigation": added(fe / "routes.tsx", pristine, "frontend/src/routes.tsx")
        - added_for(fe / "routes.tsx", pristine, "login"),
        "tests (dedicated to the module)": count((crm / "tests" / "test_leads.py").read_text(encoding="utf-8")),
    }


def added_for(path: Path, pristine: Path | None, needle: str) -> int:
    """Added routes.tsx lines that belong to another page (the app-wide login)."""
    ours = code_lines(path.read_text(encoding="utf-8"))
    theirs = code_lines((pristine / "frontend/src/routes.tsx").read_text(encoding="utf-8")) if pristine else []
    return sum(
        1 for line in difflib.ndiff(theirs, ours) if line.startswith("+ ") and needle in line.lower()
    )


def stand_ins(root: Path) -> int:
    """Workspace and Contact: models the original has elsewhere (Client, WhatsAppContact)."""
    return classes(root / "crm" / "models.py", {"Workspace", "Contact"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--pristine", type=Path)
    args = parser.parse_args()
    old, new = before(args.before), after(HERE, args.pristine)
    width = max(map(len, old))
    print(f"{'category':<{width}}  {'before':>7}  {'after':>6}")
    for key in old:
        print(f"{key:<{width}}  {old[key]:>7}  {new[key]:>6}")
    print(f"{'total':<{width}}  {sum(old.values()):>7}  {sum(new.values()):>6}")
    print(f"\nnot in the totals: Workspace + Contact stand-in models, {stand_ins(HERE)} lines")


if __name__ == "__main__":
    main()
