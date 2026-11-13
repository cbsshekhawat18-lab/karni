"""The merge of a part's karni.yaml into a project's (experimental): karni_cli.recipes.compose."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from karni_cli.project import CliError
from karni_cli.recipes import apply, compose
from karni_cli.spec.source import load


@dataclass(frozen=True)
class _Recipe:
    name: str
    title: str = ""
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


MODULES = {"payments": object(), "storage": object()}


def _project(**extra: Any) -> dict[str, Any]:
    return {"version": 1, "app": {"name": "Demo", "kind": "app"}, **extra}


def _desk() -> dict[str, Any]:
    return {
        "version": 1,
        "app": {"name": "Desk", "kind": "app", "currency": "EUR"},
        "modules": {"payments": {"provider": "stripe", "currency": "eur"}},
        "features": {"email_code_login": True},
        "roles": {
            "admin": {"name": "Admin", "system": True, "grants": {"*": "all"}},
            "customer": {"name": "Client", "default": True, "grants": {"desk.ticket": "own"}},
            "desk-agent": {"name": "Agent", "grants": {"desk.*": "all"}},
        },
        "apps": {
            "desk": {
                "entities": {
                    "Ticket": {"fields": {"title": "str:200", "fee": "money:EUR"}},
                    "Order": {"fields": {"total": "money:EUR?"}},
                }
            }
        },
        "pages": [{"Ticket": ["list", "detail"]}, {"Order": ["list"]}],
        "navigation": ["Ticket", "Order"],
        "seed": {"Ticket": 10, "Order": 3},
    }


def _club() -> dict[str, Any]:
    return {
        "version": 1,
        "app": {"name": "Club", "kind": "app", "currency": "USD"},
        "modules": {"payments": {"provider": "stripe", "currency": "usd"}},
        "roles": {
            "customer": {"name": "Member", "default": True, "grants": {"club.visit": "own"}},
            "club-staff": {"name": "Staff", "grants": {"club.*": "all"}},
        },
        "apps": {"club": {"entities": {"Visit": {"fields": {"when": "datetime"}}, "Order": {}}}},
        "pages": [{"Visit": ["list"]}, {"Order": ["list"]}],
        "navigation": ["Visit"],
        "seed": {"Visit": 5, "Order": 2},
    }


def _both() -> tuple[compose.Merged, compose.Merged]:
    first = compose.merge(_project(), _Recipe("desk", "Help desk"), _desk(), modules=MODULES)
    second = compose.merge(
        first.data,
        _Recipe("club", "Club"),
        _club(),
        bases={"desk": _desk()},
        parts={"desk": _Recipe("desk", "Help desk")},
        modules=MODULES,
    )
    return first, second


def test_two_parts_make_one_spec() -> None:
    first, second = _both()
    data = second.data
    assert data["app"]["recipes"] == ["desk", "club"]
    assert "recipe" not in data["app"]
    # one currency: the first part's, and every money field reads it
    assert data["app"]["currency"] == "EUR"
    assert data["apps"]["desk"]["entities"]["Ticket"]["fields"]["fee"] == "money"
    assert data["apps"]["desk"]["entities"]["Order"]["fields"]["total"] == "money?"
    assert data["modules"]["payments"] == {"provider": "stripe", "currency": "eur"}
    # each part under its own route
    assert data["apps"]["desk"]["route"] == "/desk"
    assert data["apps"]["club"]["route"] == "/club"
    # family roles add up, the project's name stays; part roles keep their prefix
    assert data["roles"]["customer"]["name"] == "Client"
    assert data["roles"]["customer"]["grants"] == {"desk.ticket": "own", "club.visit": "own"}
    assert set(data["roles"]) == {"admin", "customer", "desk-agent", "club-staff"}
    # pages appended, the family home added once, a name two apps define written app.Name
    names = [next(iter(entry)) for entry in data["pages"]]
    assert names == ["home", "Ticket", "desk.Order", "Visit", "club.Order"]
    assert data["seed"] == {"desk.Order": 3, "Ticket": 10, "Visit": 5, "club.Order": 2}
    # the first part was flat alone, and each part is a group now
    assert first.data["navigation"] == ["Ticket", "Order"]
    assert data["navigation"] == [{"Help desk": ["Ticket", "desk.Order"]}, {"Club": ["Visit"]}]


def test_unmerge_takes_the_part_out() -> None:
    _first, second = _both()
    out = compose.unmerge(second.data, "club", _club()).data
    assert out["app"]["recipes"] == ["desk"]
    assert set(out["apps"]) == {"desk"}
    assert set(out["roles"]) == {"admin", "customer", "desk-agent"}
    assert out["roles"]["customer"]["grants"] == {"desk.ticket": "own"}
    assert [next(iter(entry)) for entry in out["pages"]] == ["home", "Ticket", "desk.Order"]
    assert out["seed"] == {"desk.Order": 3, "Ticket": 10}
    assert out["navigation"] == [{"Help desk": ["Ticket", "desk.Order"]}]
    with pytest.raises(CliError) as caught:
        compose.unmerge(out, "club", _club())
    assert caught.value.code == "C448"


def _refused(project: dict[str, Any], fragment: dict[str, Any], **kwargs: Any) -> CliError:
    recipe = kwargs.pop("recipe", _Recipe("club", "Club"))
    with pytest.raises(CliError) as caught:
        compose.merge(project, recipe, fragment, modules=MODULES, **kwargs)
    return caught.value


def test_an_app_label_the_project_has_is_refused() -> None:
    project = compose.merge(_project(), _Recipe("desk"), _desk(), modules=MODULES).data
    clash = _club()
    clash["apps"] = {"desk": clash["apps"]["club"]}
    clash["roles"] = {}
    error = _refused(project, clash)
    assert error.code == "C442"
    assert "apps.desk" in error.message and "club" in error.message


def test_role_slugs_follow_the_family_rules() -> None:
    project = compose.merge(_project(), _Recipe("desk"), _desk(), modules=MODULES).data
    # the first part keeps its roles as written
    alone = compose.merge(_project(), _Recipe("club"), {**_club(), "roles": {"staff": {}}})
    assert "staff" in alone.data["roles"]
    for role, words in (
        ({"staff": {"grants": {"club.*": "all"}}}, "<prefix>-<role>"),
        ({"club-boss": {"grants": {"*": "all"}}}, 'holds "*"'),
        ({"club-guest": {"default": True}}, "default role"),
    ):
        fragment = _club()
        fragment["roles"] = role
        error = _refused(project, fragment)
        assert error.code == "C443", role
        assert words in error.message
    project["roles"]["club-staff"] = {}
    error = _refused(project, _club())
    assert error.code == "C443" and "has a role club-staff already" in error.message


def test_routes_and_family_pages_are_refused() -> None:
    project = compose.merge(_project(), _Recipe("desk"), _desk(), modules=MODULES).data
    fragment = _club()
    fragment["apps"]["club"]["route"] = "/desk"
    assert _refused(project, fragment).code == "C444"
    fragment["apps"]["club"]["route"] = "/cart"
    assert "family page" in _refused(project, fragment).message
    fragment = _club()
    fragment["pages"].insert(0, {"home": "dashboard"})
    error = _refused(project, fragment)
    assert error.code == "C444" and "home page already" in error.message
    fragment["pages"][0] = {"checkout": "code"}
    assert _refused(project, fragment).code == "C444"


def test_module_options_two_parts_disagree_on_are_refused() -> None:
    desk = _desk()
    project = compose.merge(_project(), _Recipe("desk"), desk, modules=MODULES).data
    fragment = _club()
    fragment["modules"]["payments"]["provider"] = "paddle"
    error = _refused(project, fragment, bases={"desk": desk})
    assert error.code == "C445"
    assert "desk" in error.message and "club" in error.message
    # a value the project wrote itself wins, with a note
    project["modules"]["payments"]["provider"] = "manual"
    merged = compose.merge(
        project, _Recipe("club"), fragment, bases={"desk": desk}, modules=MODULES
    )
    assert merged.data["modules"]["payments"]["provider"] == "manual"
    assert any("kept the project's 'manual'" in note for note in merged.notes)


def test_requires_switches_contracts_on_and_lists_modules() -> None:
    recipe = _Recipe("club", "Club", requires=("people>=1", "events>=1", "storage"))
    merged = compose.merge(
        _project(roles={"admin": {"grants": {"*": "all"}}}), recipe, _club(), modules=MODULES
    )
    data = merged.data
    assert data["features"]["people"] is True and data["features"]["events"] is True
    assert data["modules"]["storage"] == {}
    assert data["roles"]["admin"]["grants"] == {
        "*": "all",
        "people.*:merge": "all",
        "people.person:erase": "all",
    }
    for requires, words in (
        (("people>=2",), "version 1 of the people contract"),
        (("commerce>=1",), "neither a core contract"),
        (("people>",), "is not a requirement"),
    ):
        error = _refused(_project(), _club(), recipe=_Recipe("club", requires=requires))
        assert error.code == "C446", requires
        assert words in error.message


def test_conflicts_are_refused_both_ways() -> None:
    project = compose.merge(_project(), _Recipe("desk"), _desk(), modules=MODULES).data
    error = _refused(project, _club(), recipe=_Recipe("club", conflicts=("desk",)))
    assert error.code == "C447"
    error = _refused(project, _club(), parts={"desk": _Recipe("desk", conflicts=("club",))})
    assert error.code == "C447" and "already in this project" in error.message


def test_a_part_twice_or_another_version_is_refused() -> None:
    project = compose.merge(_project(), _Recipe("desk"), _desk(), modules=MODULES).data
    assert _refused(project, _desk(), recipe=_Recipe("desk")).code == "C442"
    newer = copy.deepcopy(_club())
    newer["version"] = 2
    assert _refused(project, newer).code == "C214"
    site = _project()
    site["app"]["kind"] = "site"
    assert _refused(site, _club()).code == "C440"


@pytest.mark.parametrize(
    ("text", "version", "allowed"),
    [
        ("people", 1, True),
        ("people>=1", 1, True),
        ("people>=2", 1, False),
        ("events>=1,<2", 1, True),
        ("events>=1,<2", 2, False),
        ("commerce==1.2", (1, 2, 0), True),
    ],
)
def test_requirements_read_a_version_range(text: str, version: Any, allowed: bool) -> None:
    assert compose.parse_requirement(text).allows(version) is allowed


# the parts of a project: karni_cli.recipes.parts ------------------------------------


def _folder_recipe(tmp_path: Path, version: str, files: dict[str, str], spec: str) -> Any:
    from karni_cli import recipes as recipes_mod

    folder = tmp_path / f"desk-{version}"
    (folder / "files").mkdir(parents=True)
    (folder / "recipe.toml").write_text(
        f'name = "desk"\ntitle = "Help desk"\nversion = "{version}"\n'
        'purpose = "Tickets."\nuse_when = ["help desk"]\nrequires = ["people>=1"]\n'
    )
    (folder / "karni.yaml").write_text(spec)
    for rel, text in files.items():
        (folder / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / "files" / rel).write_text(text)
    return recipes_mod.read_folder(folder, name="desk", source="test")


DESK_SPEC = """\
version: 1
app: {name: Desk}
roles:
  desk-agent: {name: Agent, grants: {"desk.*": all}}
apps:
  desk:
    entities:
      Ticket:
        fields: {title: "str:200"}
pages:
  - Ticket: [list]
"""


def test_a_part_is_recorded_and_upgraded_where_the_project_left_it(tmp_path: Path) -> None:
    from karni_cli.recipes import parts

    root = tmp_path / "project"
    root.mkdir()
    spec = root / "karni.yaml"
    old = _folder_recipe(
        tmp_path, "1.0.0", {"desk/a.py": "A = 1\n", "desk/b.py": "B = 1\n"}, DESK_SPEC
    )
    parts.start(root, spec, old, name="Demo", kind="app")
    data = load(spec.read_text()).data
    assert data["app"] == {"name": "Demo", "kind": "app", "recipes": ["desk"]}
    assert data["features"] == {"people": True}
    assert data["apps"]["desk"]["route"] == "/desk"
    # the build writes the files and records them; the project then changes b.py
    for rel in ("desk/a.py", "desk/b.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(apply.contents(old)[rel])
    parts.record_files(root, old, {rel: (root / rel).read_text() for rel in old.files})
    (root / "desk/b.py").write_text("B = 2  # the project's\n")
    new_spec = DESK_SPEC.replace('"str:200"', '"str:300"').replace("Agent", "Desk agent")
    new = _folder_recipe(
        tmp_path,
        "1.1.0",
        {"desk/a.py": "A = 10\n", "desk/b.py": "B = 10\n", "desk/c.py": "C = 1\n"},
        new_spec,
    )
    # the project changed the role; the entity is as added
    spec.write_text(spec.read_text().replace("name: Agent", "name: Helper"))
    report = parts.upgrade(root, spec, new)
    assert (report.old, report.new) == ("1.0.0", "1.1.0")
    assert report.replaced == ["desk/a.py"] and report.added == ["desk/c.py"]
    assert report.kept == ["desk/b.py"]
    assert (root / "desk/a.py").read_text() == "A = 10\n"
    assert (root / "desk/b.py").read_text() == "B = 2  # the project's\n"
    assert (root / "desk/b.py.recipe-1.1.0").read_text() == "B = 10\n"
    assert report.spec_updated == ["apps.desk.entities.Ticket"]
    assert report.spec_kept == ["roles.desk-agent"]
    data = load(spec.read_text()).data
    assert data["apps"]["desk"]["entities"]["Ticket"]["fields"]["title"] == "str:300"
    assert data["roles"]["desk-agent"]["name"] == "Helper"
    kept = parts.load_record(root, "desk")
    assert kept is not None and kept.recipe_version == "1.1.0"


def test_remove_takes_the_part_out_and_lists_its_files(tmp_path: Path) -> None:
    from karni_cli.recipes import parts

    root = tmp_path / "project"
    root.mkdir()
    spec = root / "karni.yaml"
    recipe = _folder_recipe(tmp_path, "1.0.0", {"desk/a.py": "A = 1\n"}, DESK_SPEC)
    parts.start(root, spec, recipe, name="Demo", kind="app")
    (root / "desk").mkdir()
    (root / "desk/a.py").write_text("A = 1\n")
    parts.record_files(root, recipe, {"desk/a.py": "A = 1\n"})
    _merged, left = parts.remove(root, spec, "desk")
    assert left == ["desk/a.py"]
    data = load(spec.read_text()).data
    assert data["app"]["recipes"] == [] and "desk" not in data.get("apps", {})
    assert not (root / ".karni/recipes/desk").exists()
    with pytest.raises(CliError) as caught:
        parts.upgrade(root, spec, recipe)
    assert caught.value.code == "C449"


def test_spec_text_keeps_the_comments_it_does_not_change() -> None:
    from karni_cli.recipes import parts

    text = "# header\nversion: 1\napp:\n  name: Demo  # the name\nseed:\n  A: 1\n"
    data = {"version": 1, "app": {"name": "Demo", "recipes": ["x"]}, "seed": {"A": 3}}
    out = parts.spec_text(text, data, [])
    assert "# the name" in out and out.startswith("# header")
    assert load(out).data == data


def test_the_codemod_writes_app_recipes() -> None:
    from karni_cli.upgrades.v0_5.recipe_list import recipes_key

    text = "version: 1\napp:\n  name: Shop  # mine\n  recipe: shop\n"
    assert recipes_key(text) == "version: 1\napp:\n  name: Shop  # mine\n  recipes: [shop]\n"
    assert recipes_key("version: 1\napp: {name: Shop, recipe: shop}\n") == (
        "version: 1\napp: {name: Shop, recipes: [shop]}\n"
    )
    assert recipes_key("version: 1\napp: {name: Shop}\n") is None
