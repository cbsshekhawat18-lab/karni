"""The part rules (K315, K316): a part never names another part, and keeps its roles and routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from karni.testing import _source, architecture, parts


def _project(
    root: Path,
    recipes: dict[str, dict[str, Any]],
    files: dict[str, str],
    *,
    spec: dict[str, object] | None = None,
) -> Path:
    """A project with parts: ``recipes`` is each part's fragment, ``files`` its sources."""
    for name, fragment in recipes.items():
        folder = root / ".karni" / "recipes" / name
        folder.mkdir(parents=True)
        (folder / "karni.yaml").write_text(yaml.safe_dump(fragment), encoding="utf-8")
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    spec = dict(spec or {})
    spec.setdefault("app", {"recipes": list(recipes)})
    (root / "karni.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    _source._file_lines.cache_clear()
    return root


PAIR: dict[str, dict[str, Any]] = {
    "booking": {"apps": {"bookings": {"entities": {"Resource": {}}}}},
    "crm": {"apps": {"crm": {"entities": {"Deal": {}}}}},
}


def test_a_project_without_parts_passes(tmp_path: Path) -> None:
    (tmp_path / "bookings").mkdir()
    (tmp_path / "bookings" / "models.py").write_text("import crm\n")
    assert parts.installed_parts(tmp_path) == []
    assert parts.check_part_imports(tmp_path) == []
    assert parts.check_part_roles(tmp_path) == []
    assert parts.check_part_routes(tmp_path) == []


def test_one_part_alone_may_name_anything(tmp_path: Path) -> None:
    root = _project(
        tmp_path, {"booking": PAIR["booking"]}, {"bookings/models.py": "from crm import x\n"}
    )
    assert parts.check_part_imports(root) == []


@pytest.mark.parametrize(
    ("source", "what"),
    [
        ("import crm\n", "imports crm"),
        ("from crm.models import Deal\n", "imports from crm.models"),
        ("deal = models.ForeignKey('crm.Deal', on_delete=models.CASCADE)\n", "crm.Deal"),
        ("GRANTS = {'crm.deal': 'own'}\n", "crm.deal"),
        ("name = 'crm:deal-list'\n", "crm:deal-list"),
        ("TEMPLATE = 'crm/email/hello.txt'\n", "crm/email/hello.txt"),
        ("model = apps.get_model('crm', 'Deal')\n", "asks for the app 'crm'"),
        ("dependencies = [('crm', '0001_initial')]\n", "migration 0001_initial"),
    ],
)
def test_a_part_naming_another_is_flagged(tmp_path: Path, source: str, what: str) -> None:
    root = _project(tmp_path, PAIR, {"bookings/models.py": source})
    found = parts.check_part_imports(root)
    assert [v.rule for v in found] == ["part-imports-part"]
    assert found[0].location == "bookings/models.py:1"
    assert what in found[0].message and "booking part" in found[0].message
    assert "crm part" in found[0].message and "contract" in found[0].hint


def test_the_contracts_words_and_the_part_itself_are_allowed(tmp_path: Path) -> None:
    source = (
        '"""Mentions crm.Deal in a docstring, which is words and not a reference."""\n'
        "from karni.people import resolve\n"
        "from karni_commerce import cart\n"
        "from bookings.models import Resource\n"
        "label = 'bookings.Resource'\n"
        "perm = 'bookings.resource:own'\n"
        "note = 'Ask the crm.Deal owner about it'\n"
        "email = 'host.example.com'\n"
    )
    root = _project(tmp_path, PAIR, {"bookings/models.py": source})
    assert parts.check_part_imports(root) == []


def test_templates_and_the_frontend_are_read(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        PAIR,
        {
            "bookings/templates/bookings/a.html": "{% include 'crm/card.html' %}\n",
            "bookings/templates/bookings/b.html": "{% url 'crm:deal-list' %}\n",
            "bookings/templates/bookings/ok.html": "{% include 'bookings/card.html' %}\n",
            "frontend/src/bookings/index.ts": (
                'import { x } from "@karni/ui";\n'
                'import { a } from "./local";\n'
                'import { b } from "../crm/deals";\n'
                'import { c } from "@/crm";\n'
            ),
            "frontend/src/crm/index.ts": 'import { z } from "../bookings/index";\n',
        },
    )
    found = {(v.location, v.message.split(" part ")[0]) for v in parts.check_part_imports(root)}
    assert found == {
        ("bookings/templates/bookings/a.html:1", "the booking"),
        ("bookings/templates/bookings/b.html:1", "the booking"),
        ("frontend/src/bookings/index.ts:3", "the booking"),
        ("frontend/src/bookings/index.ts:4", "the booking"),
        ("frontend/src/crm/index.ts:1", "the crm"),
    }


def test_an_opt_out_needs_its_reason(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        PAIR,
        {
            "bookings/a.py": "import crm  # karni: allow(part-imports-part): a bridge file\n",
            "bookings/b.py": "# karni: allow(part-imports-part): a bridge file\nimport crm\n",
            "bookings/c.py": "import crm  # karni: allow(part-imports-part):\n",
            "frontend/src/bookings/i.ts": (
                '// karni: allow(part-imports-part): the demo joins them\nimport "../crm/x";\n'
            ),
            "bookings/templates/bookings/t.html": (
                "{# karni: allow(part-imports-part): joined on purpose #}\n"
                "{% include 'crm/card.html' %}\n"
            ),
        },
    )
    found = parts.check_part_imports(root)
    assert sorted(v.rule for v in found) == ["opt-out-reason", "part-imports-part"]
    assert all("bookings/c.py" in v.location or "c.py" in v.location for v in found)


def test_the_architecture_run_includes_the_part_rules() -> None:
    for check in (parts.check_part_imports, parts.check_part_roles, parts.check_part_routes):
        assert check in architecture.ALL_CHECKS


# roles ---------------------------------------------------------------------------------


def test_a_second_part_with_an_unprefixed_role_is_flagged(tmp_path: Path) -> None:
    recipes = {
        "booking": {**PAIR["booking"], "roles": {"staff": {}}},
        "crm": {**PAIR["crm"], "roles": {"admin": {}, "customer": {}, "rep": {}, "crm-lead": {}}},
    }
    spec = {
        "app": {"recipes": ["booking", "crm"]},
        "roles": {"admin": {}, "staff": {}, "rep": {}, "crm-lead": {}},
    }
    root = _project(tmp_path, recipes, {}, spec=spec)
    found = parts.check_part_roles(root)
    # booking is first and keeps its role as written, crm's rep must be crm-rep
    assert [v.location for v in found] == ["karni.yaml: roles.rep"]
    assert "crm-rep" in found[0].hint and "<prefix>-<role>" in found[0].message
    # renamed in the project: no longer a finding
    spec["roles"] = {"admin": {}, "staff": {}, "crm-rep": {}}
    (root / "karni.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    assert parts.check_part_roles(root) == []


def test_a_role_renamed_away_from_its_prefix_is_found_by_its_grants(tmp_path: Path) -> None:
    spec = {
        "app": {"recipes": ["booking", "crm"]},
        "roles": {
            "admin": {},
            "crm-rep": {"grants": {"crm.deal": "own"}},
            "rep": {"grants": {"crm.deal": "own", "crm.company": "all"}},
            "mixed": {"grants": {"crm.deal": "own", "bookings.booking": "own"}},
            "auditor": {"grants": {"*": "read"}},
        },
    }
    root = _project(tmp_path, PAIR, {}, spec=spec)
    assert [v.location for v in parts.check_part_roles(root)] == ["karni.yaml: roles.rep"]


# routes --------------------------------------------------------------------------------


def test_a_route_that_is_a_family_page_or_taken_is_flagged(tmp_path: Path) -> None:
    spec = {
        "app": {"recipes": ["booking", "crm"]},
        "apps": {
            "bookings": {"route": "/settings"},
            "crm": {"route": "/shared"},
            "other": {"route": "/shared"},
        },
    }
    root = _project(tmp_path, PAIR, {}, spec=spec)
    found = parts.check_part_routes(root)
    assert [v.location for v in found] == [
        "karni.yaml: apps.bookings.route",
        "karni.yaml: apps.crm.route",
    ]
    assert "family page" in found[0].message and "other" in found[1].message


def test_a_page_routed_outside_its_part_is_flagged(tmp_path: Path) -> None:
    routes = (
        '    createRoute({ getParentRoute: () => root, path: "/bookings/resources", '
        "component: ResourcesPage }),\n"
        '    createRoute({ getParentRoute: () => root, path: "/bookings/resources/$id", '
        "component: ResourceDetailPage }),\n"
        '    createRoute({ getParentRoute: () => root, path: "/deals", component: DealsPage }),\n'
        '    createRoute({ getParentRoute: () => root, path: "/crm/deals/new", '
        "component: DealFormPage }),\n"
    )
    spec = {
        "app": {"recipes": ["booking", "crm"]},
        "apps": {
            "bookings": {"route": "/bookings", "entities": {"Resource": {}}},
            "crm": {"entities": {"Deal": {}}},
        },
    }
    root = _project(tmp_path, PAIR, {"frontend/src/routes.tsx": routes}, spec=spec)
    found = parts.check_part_routes(root)
    assert [v.location for v in found] == ["frontend/src/routes.tsx:3"]
    assert "DealsPage" in found[0].message and "/crm" in found[0].message
