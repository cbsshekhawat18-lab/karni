"""``karni make``: the universal generator behaviour and each generator's contract.

The quality gate (every generator's output is lint- and rules-clean, and the
generated backend really runs) lives in ``test_make_gate.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from karni_cli import project as project_mod
from karni_cli.main import app

from .conftest import TEMPLATE

GENERATORS = {
    "app",
    "model",
    "viewset",
    "serializer",
    "migration",
    "test",
    "factory",
    "seeder",
    "task",
    "schedule",
    "event",
    "listener",
    "command",
    "service",
    "middleware",
    "page",
    "component",
    "site",
    "view",
    "deploy",
    "form",
    "module",
}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh ``karni new`` project; the cwd is inside it."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Make Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "make_check"
    monkeypatch.chdir(root)
    return root


def run(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def ok(*args: str) -> Result:
    result = run(*args)
    assert result.exit_code == 0, f"{args}: {result.output}\n{result.exception!r}"
    return result


def fails(*args: str, match: str) -> str:
    result = run(*args)
    assert result.exit_code != 0, result.output
    message = str(result.exception) if result.exception else result.output
    assert match in message, message
    return message


def snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and "node_modules" not in p.parts
    }


# discovery


def test_list_prints_every_generator_and_only_those() -> None:
    result = ok("make", "--list")
    names = {line.split()[0] for line in result.output.strip().splitlines()}
    assert names == GENERATORS


def test_make_without_a_type_prints_help() -> None:
    result = ok("make")
    assert "--list" in result.output and "model" in result.output


def test_aliases_are_hidden_but_work(project: Path) -> None:
    assert "make:model" not in ok("--help").output
    ok("make:app", "events")
    ok("make:task", "via_alias")
    ok("make", "task", "via_group")
    tasks = (project / "events" / "tasks.py").read_text()
    assert "def via_alias() -> None:" in tasks and "def via_group() -> None:" in tasks


# universal behaviour


def test_app_wires_settings_and_writes_only_the_contract_files(project: Path) -> None:
    result = ok("make", "app", "events")
    created = sorted(p.relative_to(project).as_posix() for p in (project / "events").rglob("*"))
    assert created == [
        "events/__init__.py",
        "events/apps.py",
        "events/migrations",
        "events/migrations/__init__.py",
        "events/models.py",
        "events/tests",
        "events/tests/__init__.py",
        "events/viewsets.py",
    ]
    assert '    "events",\n]  # karni:apps' in (project / "config" / "settings.py").read_text()
    assert "created  events/apps.py" in result.output
    assert "modified config/settings.py" in result.output


def test_never_overwrites_without_force(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "task", "digest")
    before = (project / "events" / "tasks.py").read_text()
    fails("make", "task", "digest", match="--force")
    assert (project / "events" / "tasks.py").read_text() == before
    ok("make", "task", "digest", "--retry", "2", "--force")
    after = (project / "events" / "tasks.py").read_text()
    assert after.count("def digest(") == 1 and "max_retries=2" in after
    fails("make", "app", "events", match="Pass --force to create only the missing files")
    # --force on a skeleton fills in missing files and never truncates existing ones.
    models = project / "events" / "models.py"
    (project / "events" / "apps.py").unlink()
    models.write_text(models.read_text() + "# user code\n")
    result = ok("make", "app", "events", "--force")
    assert (project / "events" / "apps.py").is_file()
    assert models.read_text().endswith("# user code\n")
    assert "kept     events/models.py (exists)" in result.output


def test_dry_run_writes_nothing_and_shows_the_diff(project: Path) -> None:
    ok("make", "app", "events")
    before = snapshot(project)
    result = ok("make", "model", "Event", "title:str", "--with", "viewset", "--dry-run")
    assert snapshot(project) == before
    assert "would modify events/models.py" in result.output
    assert "+class Event(BaseModel):" in result.output
    assert "(dry run: nothing written)" in result.output


def test_failed_step_writes_nothing(project: Path) -> None:
    ok("make", "app", "events")
    before = snapshot(project)
    fails("make", "model", "Event", "title:str", "tags:m2m:Missing", "-a", match="Missing")
    assert snapshot(project) == before


def test_app_resolution(project: Path) -> None:
    fails("make", "task", "digest", match="no local app yet")
    ok("make", "app", "events")
    ok("make", "task", "digest")  # the only local app is the default
    ok("make", "app", "shop")
    fails("make", "task", "other", match="Several local apps (events, shop)")
    fails("make", "task", "other", "--app", "nope", match="local apps: events, shop")
    ok("make", "task", "other", "--app", "shop")
    assert "def other()" in (project / "shop" / "tasks.py").read_text()


def test_app_name_rules(project: Path) -> None:
    fails("make", "app", "Events", match="snake_case")
    fails("make", "app", "json", match="shadow")
    fails("make", "app", "karni_x", match="karni make module")


# model / viewset / serializer


def test_model_chain_and_access_default_is_announced(project: Path) -> None:
    ok("make", "app", "events")
    result = ok("make", "model", "Event", "title:str:200", "--with", "viewset", "--search", "title")
    assert "access: Granted() (the default: what KARNI_ROLES grants for Event" in result.output
    assert "next: karni make migration --app events" in result.output
    viewsets = (project / "events" / "viewsets.py").read_text()
    assert "access = Granted()" in viewsets
    assert "from karni.api import BaseViewSet, Granted" in viewsets
    assert 'search_fields = ("title",)' in viewsets


@pytest.mark.parametrize(
    ("access", "declaration"),
    [
        ("granted", "Granted()"),
        ("authenticated", "Access(read=Authenticated(), write=Authenticated())"),
        ("public-read", 'Access(read=Public(), write=HasRole("staff"))'),
        ("public-read:editor", 'Access(read=Public(), write=HasRole("editor"))'),
        (
            "public-create",
            'Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())',
        ),
        (
            "public-create:editor",
            'Access(read=HasRole("editor"), write=HasRole("editor"), create=Public())',
        ),
        ("owned:owner", 'Access(read=Owned("owner"), write=Owned("owner"))'),
        ("staff", 'Access(read=HasRole("staff"), write=HasRole("staff"))'),
        ("role:editor", 'Access(read=HasRole("editor"), write=HasRole("editor"))'),
    ],
)
def test_viewset_access_choices(project: Path, access: str, declaration: str) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "owner:fk:User")
    ok("make", "viewset", "Event", "--access", access)
    assert f"access = {declaration}" in (project / "events" / "viewsets.py").read_text()


def test_viewset_validation(project: Path) -> None:
    ok("make", "app", "events")
    fails("make", "viewset", "Event", match="Create it first: karni make model Event")
    ok("make", "model", "Event", "title:str")
    fails("make", "viewset", "Event", "--access", "owned:title", match="not a relation")
    fails("make", "viewset", "Event", "--access", "everyone", match="choose one of")
    for bad in ("public-read:", "public-read:bad role", "public-read:-x"):
        message = fails("make", "viewset", "Event", "--access", bad, match="public-read:<role>")
        assert message.startswith("C106: ") and "e.g. public-read:editor" in message
    message = fails(
        "make", "viewset", "Event", "--access", "public-create:", match="public-create:<role>"
    )
    assert "read and write" in message and "e.g. public-create:editor" in message
    fails("make", "viewset", "Event", "--search", "nope", match="has no field 'nope'")
    fails("make", "model", "Other", "--access", "staff", match="--with viewset")


def test_public_create_is_a_public_form_and_says_how_it_is_protected(project: Path) -> None:
    """A contact form: anyone sends one, only staff read them, and Karni limits the sending."""
    ok("make", "app", "enquiries")
    result = ok(
        "make",
        "model",
        "Enquiry",
        "name:str",
        "message:text",
        "--with",
        "viewset,test",
        "--access",
        "public-create",
    )
    assert (
        'access: Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())'
        in result.output
    )
    assert "who: anyone creates, only role 'staff' reads, changes and deletes" in result.output
    assert "KARNI_PUBLIC_CREATE_RATE" in result.output
    viewsets = (project / "enquiries" / "viewsets.py").read_text()
    assert "from karni.api import Access, BaseViewSet, HasRole, Public" in viewsets
    assert "throttle" not in viewsets  # the default limit needs no declaration
    test = (project / "enquiries" / "tests" / "test_enquiry.py").read_text()
    assert '        self.assert_crud(EnquiryViewSet, "staff")\n' in test


def test_public_read_lets_only_a_role_write_and_says_so(project: Path) -> None:
    """0.4.0 wrote write=Authenticated(): with open registration anyone could write."""
    ok("make", "app", "events")
    result = ok(
        "make", "model", "Venue", "name:str", "--with", "viewset,test", "--access", "public-read"
    )
    assert 'access: Access(read=Public(), write=HasRole("staff"))' in result.output
    assert "who: anyone reads, only role 'staff' writes" in result.output
    viewsets = (project / "events" / "viewsets.py").read_text()
    assert "from karni.api import Access, BaseViewSet, HasRole, Public" in viewsets
    assert "Authenticated" not in viewsets
    test = (project / "events" / "tests" / "test_venue.py").read_text()
    assert '        self.assert_crud(VenueViewSet, "staff")\n' in test
    assert "test: VenueViewSet as role 'staff'" in result.output

    result = ok("make", "viewset", "Venue", "--access", "public-read:editor", "--force")
    assert "who: anyone reads, only role 'editor' writes" in result.output
    ok("make", "test", "Venue", "--force")
    test = (project / "events" / "tests" / "test_venue.py").read_text()
    assert '        self.assert_crud(VenueViewSet, "editor")\n' in test


def test_authenticated_access_warns_that_anyone_signed_in_writes(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    result = ok("make", "viewset", "Venue", "--access", "authenticated")
    assert "warning: every signed-in user may change and delete every row" in result.output
    assert "karni.W102" in result.output


def test_the_generated_test_acts_as_the_role_that_writes(project: Path) -> None:
    """A role named only in read= would make the test confirm refusals, not writes."""
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str", "owner:fk:User")
    (project / "events" / "viewsets.py").write_text(
        "from karni.api import Access, BaseViewSet, HasRole, Owned\n"
        "from events.models import Venue\n\n\n"
        "class VenueViewSet(BaseViewSet):\n"
        "    model = Venue\n"
        "    access = Access(\n"
        '        read=HasRole("viewer") | HasRole("clerk") | HasRole("editor"),\n'
        '        write=Owned("owner") | HasRole("editor"),\n'
        '        create=HasRole("clerk"),\n'
        "    )\n"
    )
    result = ok("make", "test", "Venue")
    test = (project / "events" / "tests" / "test_venue.py").read_text()
    assert '        self.assert_crud(VenueViewSet, "editor")\n' in test
    # reads are by role, so every reader sees every row: nothing isolates, and no check claims it
    assert "test: VenueViewSet as role 'editor'\n" in result.output
    assert "assert_isolated" not in test


def test_the_isolation_check_follows_the_read_rule(project: Path) -> None:
    """Owned(...) in write= alone isolates nothing, and a role the read rule admits sees all."""
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str", "owner:fk:User")
    viewsets = project / "events" / "viewsets.py"
    head = "from karni.api import Access, BaseViewSet, HasRole, Owned, Public\n"
    head += "from events.models import Venue\n\n\nclass VenueViewSet(BaseViewSet):\n"
    head += "    model = Venue\n"
    viewsets.write_text(head + '    access = Access(read=Public(), write=Owned("owner"))\n')
    ok("make", "test", "Venue")
    test = project / "events" / "tests" / "test_venue.py"
    assert "assert_isolated" not in test.read_text()
    viewsets.write_text(
        head
        + '    access = Access(read=Owned("owner") | HasRole("staff"), write=HasRole("staff"))\n'
    )
    ok("make", "test", "Venue", "--force")
    text = test.read_text()
    assert '        self.assert_crud(VenueViewSet, "staff")\n' in text
    assert "        self.assert_isolated(VenueViewSet)\n" in text  # as a user staff does not cover


def test_model_force_replaces_only_that_class(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Event", "title:str", "venue:fk:Venue")
    fails("make", "model", "Event", "title:str", match="--force")
    ok("make", "model", "Event", "name:str", "--force")
    models = (project / "events" / "models.py").read_text()
    assert models.count("class Event(BaseModel):") == 1
    assert "class Venue(BaseModel):" in models and "venue = " not in models


@pytest.fixture
def pillow(monkeypatch: pytest.MonkeyPatch) -> list[bool | None]:
    """What the project's interpreter answers about Pillow: set ``pillow[0]`` (default False)."""
    answer: list[bool | None] = [False]
    monkeypatch.setattr(project_mod, "project_has_module", lambda root, module: answer[0])
    return answer


def _dependencies(project: Path) -> list[str]:
    import tomllib

    return tomllib.loads((project / "pyproject.toml").read_text())["project"]["dependencies"]


def _set_karni(project: Path, requirement: str) -> str:
    path = project / "pyproject.toml"
    path.write_text(path.read_text().replace('    "karni",\n', f'    "{requirement}",\n', 1))
    return path.read_text()


def test_an_image_field_adds_the_images_extra_to_pyproject(
    project: Path, pillow: list[bool | None]
) -> None:
    ok("make", "app", "events")
    before = (project / "pyproject.toml").read_text()
    assert _dependencies(project)[0] == "karni"
    result = ok("make", "model", "Event", "title:str", "photo:image?", "logo:image?")
    after = (project / "pyproject.toml").read_text()
    assert after == before.replace('    "karni",\n', '    "karni[images]",\n', 1)
    assert "modified pyproject.toml" in result.output
    assert (
        'note: pyproject.toml: "karni" -> "karni[images]", because Event.photo, Event.logo '
        "are ImageFields and the images extra installs Pillow" in result.output
    )
    assert "pip install -e ." in result.output
    ok("make", "model", "Poster", "image:image")  # already there now: left alone
    assert (project / "pyproject.toml").read_text() == after


def test_the_extra_merges_with_extras_and_keeps_the_version_spec(
    project: Path, pillow: list[bool | None]
) -> None:
    ok("make", "app", "events")
    _set_karni(project, "karni[s3]>=0.4,<0.5")
    result = ok("make", "model", "Event", "photo:image")
    assert _dependencies(project)[0] == "karni[s3,images]>=0.4,<0.5"
    assert '"karni[s3]>=0.4,<0.5" -> "karni[s3,images]>=0.4,<0.5"' in result.output


@pytest.mark.parametrize(
    ("has_pillow", "expected"), [(True, None), (False, "Reinstall the project"), (None, None)]
)
def test_a_project_with_the_extra_is_left_unchanged(
    project: Path, pillow: list[bool | None], has_pillow: bool | None, expected: str | None
) -> None:
    pillow[0] = has_pillow
    ok("make", "app", "events")
    text = _set_karni(project, "karni[images]>=0.4")
    result = ok("make", "model", "Event", "photo:image")
    assert (project / "pyproject.toml").read_text() == text
    assert "pyproject.toml:" not in result.output
    if expected is None:
        assert "Pillow" not in result.output
    else:
        assert "pyproject.toml already lists karni[images]" in result.output
        assert expected in result.output


def test_dry_run_shows_the_pyproject_edit_and_writes_nothing(
    project: Path, pillow: list[bool | None]
) -> None:
    ok("make", "app", "events")
    before = (project / "pyproject.toml").read_text()
    result = ok("make", "model", "Event", "photo:image", "--dry-run")
    assert (project / "pyproject.toml").read_text() == before
    assert "would modify pyproject.toml" in result.output
    assert '-    "karni",' in result.output and '+    "karni[images]",' in result.output
    assert "(dry run: nothing written)" in result.output


@pytest.mark.parametrize(
    ("has_pillow", "expected"),
    [(True, None), (False, "has no Pillow"), (None, "so the project needs Pillow")],
)
def test_without_an_editable_karni_dependency_the_note_names_the_step(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    has_pillow: bool | None,
    expected: str | None,
) -> None:
    asked: list[tuple[Path, str]] = []

    def probe(root: Path, module: str) -> bool | None:
        asked.append((root, module))
        return has_pillow

    monkeypatch.setattr(project_mod, "project_has_module", probe)
    ok("make", "app", "events")
    text = _set_karni(project, "django")  # karni is not a direct dependency here
    result = ok("make", "model", "Event", "title:str", "photo:image?", "logo:image?")
    assert asked == [(project.resolve(), "PIL")]  # the project's interpreter, asked once
    assert (project / "pyproject.toml").read_text() == text
    if expected is None:
        assert "Pillow" not in result.output
    else:
        assert expected in result.output
        assert "Event.photo, Event.logo are ImageFields" in result.output
        assert "karni is not in [project].dependencies" in result.output
    ok("make", "model", "Venue", "name:str")
    assert len(asked) == 1  # no image field, no probe


def test_project_has_module_asks_the_project_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    assert project_mod.project_has_module(tmp_path, "json") is True
    assert project_mod.project_has_module(tmp_path, "karni_no_such_module") is False
    monkeypatch.setattr(project_mod, "venv_python", lambda root: None)
    assert project_mod.project_has_module(tmp_path, "json") is None


def test_serializer_needs_a_reason_and_wires_the_viewset(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "owner:fk:User")
    fails("make", "serializer", "Event", "--reason", "x", match="No viewset for Event")
    ok("make", "viewset", "Event", "--access", "owned:owner")
    fails("make", "serializer", "Event", match="--reason is required")
    result = ok("make", "serializer", "Event", "--reason", "computed label")
    assert "generates a serializer already" in result.output
    serializers = (project / "events" / "serializers.py").read_text()
    assert "# karni: allow(redundant-serializer): computed label" in serializers
    assert '"owner",\n        )' in serializers  # the owner field is read-only
    viewsets = (project / "events" / "viewsets.py").read_text()
    assert "    model = Event\n    serializer_class = EventSerializer\n" in viewsets
    assert "from events.serializers import EventSerializer" in viewsets


# test / factory / seeder


def test_test_generator_follows_the_viewset(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "organizer:fk:User")
    fails("make", "test", "Event", match="Create it first: karni make viewset Event")
    ok("make", "viewset", "Event", "--access", "owned:organizer")
    result = ok("make", "test", "Event")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert "from events.viewsets import EventViewSet" in text
    assert "        self.assert_crud(EventViewSet)\n" in text
    assert "        self.assert_isolated(EventViewSet)\n" in text
    assert "as any signed-in user + owner isolation" in result.output
    assert "run: karni test events/tests/test_event.py" in result.output
    fails("make", "test", "Event", match="--force")
    ok("make", "test", "Event", "--role", "organizer", "--force")
    assert (
        'self.assert_crud(EventViewSet, "organizer")'
        in (project / "events" / "tests" / "test_event.py").read_text()
    )


def test_test_generator_picks_a_granted_role(project: Path) -> None:
    """A Granted() viewset is tested as the first KARNI_ROLES role with a scoped grant."""
    ok("make", "app", "events")
    result = ok("make", "model", "Event", "title:str", "--with", "viewset,test")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "user")\n' in text  # shipped: user = own
    assert '        self.assert_isolated(EventViewSet, "user")\n' in text
    assert "as role 'user' + grant isolation" in result.output
    settings = project / "config" / "settings.py"
    settings.write_text(
        settings.read_text()
        + '\nKARNI_ROLES = {"ops": {"grants": {"*": "all"}}, "clerk": {"grants": {"events.*": "own"}}}\n'
    )
    result = ok("make", "test", "Event", "--force")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "clerk")\n' in text
    assert "        self.assert_isolated(EventViewSet" in text
    result = ok("make", "test", "Event", "--role", "ops", "--force")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "ops")\n' in text
    assert "assert_isolated" not in text  # an `all` grant partitions nothing
    assert "as role 'ops'" in result.output and "isolation" not in result.output


def test_test_generator_takes_the_declared_role(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str", "--with", "viewset,test", "--access", "staff")
    text = (project / "events" / "tests" / "test_venue.py").read_text()
    assert 'self.assert_crud(VenueViewSet, "staff")' in text
    assert "assert_isolated" not in text  # nothing Owned: no isolation test


def test_factory_and_seeder_generators(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Event", "title:str", "--with", "factory,seeder")
    ok("make", "factory", "Venue")
    ok("make:seeder", "Venue", "--count", "0")
    factories = (project / "events" / "factories.py").read_text()
    assert "from karni.testing.factories import ModelFactory" in factories
    assert "class EventFactory(ModelFactory):" in factories
    assert "class VenueFactory(ModelFactory):" in factories
    assert factories.count("        model = ") == 2
    seeds = (project / "events" / "seeds.py").read_text()
    assert "from karni.seeding import Seeder" in seeds
    assert "class EventSeeder(Seeder):" in seeds
    assert "        model = Venue\n        count = 0\n" in seeds
    fails("make", "factory", "Venue", match="--force")
    fails("make", "seeder", "Nope", match="Create it first")
    fails("make", "seeder", "Venue", "--count", "-1", "--force", match="0 or more")


def test_all_chains_the_test_but_not_the_overrides(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "-a")
    assert (project / "events" / "tests" / "test_event.py").is_file()
    assert not (project / "events" / "factories.py").exists()
    assert not (project / "events" / "seeds.py").exists()
    fails("make", "model", "Other", "--with", "nope", match="available: viewset, page, test")


# tasks, schedules, events, listeners


def test_schedule(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "app", "shop")
    fails("make", "schedule", "nightly", "--app", "events", match="exactly one of")
    fails("make", "schedule", "nightly", "--every", "15x", "--app", "events", match="--every")
    fails("make", "schedule", "x", "--cron", "0 3 *", "--app", "events", match="5 fields")
    ok("make", "schedule", "nightly-report", "--cron", "0 3 * * *", "--app", "events")
    schedules = (project / "events" / "schedules.py").read_text()
    assert 'cron("0 3 * * *", tasks.nightly_report, name="nightly-report")' in schedules
    assert "def nightly_report() -> None:" in (project / "events" / "tasks.py").read_text()
    fails("make", "schedule", "nightly-report", "--every", "1h", "--app", "shop", match="already")
    fails(
        "make", "schedule", "x", "--every", "1h", "--task", "events.tasks.nope", "--app", "events",
        match="No task nope",
    )  # fmt: skip
    ok("make", "schedule", "nightly-report", "--every", "1h", "--app", "events", "--force")
    schedules = (project / "events" / "schedules.py").read_text()
    assert 'every("1h", tasks.nightly_report, name="nightly-report")' in schedules
    assert "cron(" not in schedules.split("import")[-1]


def test_listener_variants(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str")
    fails("make", "listener", "x", "--on", "Event.renamed", match="expected Model.created")
    fails("make", "listener", "x", "--on", "Venue.created", match="no model Venue")
    fails("make", "listener", "x", "--on", "order_shipped", match="karni make event")
    ok("make", "listener", "sync", "--on", "Event.updated", "--queued")
    # An installed app's model, and the user model: the lazy "app_label.Model" form.
    ok("make", "listener", "confirm_paid", "--on", "karni_payments.Payment.updated")
    ok("make", "listener", "welcome", "--on", "User.created")
    ok("make", "event", "order_shipped")
    ok("make", "listener", "notify", "--on", "order_shipped", "--queued")
    listeners = (project / "events" / "listeners.py").read_text()
    assert "@on_updated(Event, queued=True)\ndef sync(event: Event) -> None:" in listeners
    assert '@on_updated("karni_payments.Payment")\ndef confirm_paid(payment: Any)' in listeners
    assert '@on_created("karni_accounts.User")\ndef welcome(user: Any)' in listeners
    assert "from typing import Any" in listeners and "karni_payments" not in listeners.split("@")[0]
    assert "@receiver(order_shipped)" in listeners
    assert "transaction.on_commit(tasks.notify.delay)" in listeners
    assert "def notify() -> None:" in (project / "events" / "tasks.py").read_text()


def test_command_service_middleware(project: Path) -> None:
    ok("make", "app", "events")
    fails("make", "command", "migrate", match="Django/Karni command")
    ok("make", "command", "send_reminders")
    assert (project / "events" / "management" / "commands" / "__init__.py").is_file()
    ok("make", "service", "stripe_client")
    assert (
        "class StripeClientService:"
        in (project / "events" / "services" / "stripe_client.py").read_text()
    )
    result = ok("make", "middleware", "RequestTiming")
    assert "events.middleware.RequestTimingMiddleware" in result.output
    settings = (project / "config" / "settings.py").read_text()
    assert '    "events.middleware.RequestTimingMiddleware",\n]  # karni:middleware' in settings


def test_middleware_without_marker_prints_the_manual_step(project: Path) -> None:
    ok("make", "app", "events")
    settings = project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace("# karni:middleware", "# (removed)"))
    result = ok("make", "middleware", "Audit")
    assert "wire it yourself: add 'events.middleware.AuditMiddleware' to MIDDLEWARE" in (
        result.output
    )


# frontend


def test_pages_link_only_to_routes_that_exist(project: Path) -> None:
    pages = project / "frontend" / "src" / "pages"
    ok("make", "page", "events", "--resource", "events")
    assert "navigate" not in (pages / "events.tsx").read_text()  # no detail/form route yet
    ok("make", "page", "event-detail", "--resource", "events", "--kind", "detail")
    ok("make", "page", "events", "--resource", "events", "--force")
    listing = (pages / "events.tsx").read_text()
    assert 'to: "/events/$id"' in listing and "/events/new" not in listing
    routes = (project / "frontend" / "src" / "routes.tsx").read_text()
    assert routes.count('path: "/events"') == 1  # --force did not duplicate the route
    assert 'import EventDetailPage from "./pages/event-detail";' in routes
    fails("make", "page", "other", "--path", "/events", match="already registered")
    # The sign-in page: @karni/ui's LoginForm, no resource needed.
    result = ok("make", "page", "login", "--kind", "login")
    assert "page: /login -> LoginPage" in result.output
    login = (project / "frontend" / "src" / "pages" / "login.tsx").read_text()
    assert 'import { LoginForm, Page } from "@karni/ui";' in login
    assert '<LoginForm onSuccess={() => void navigate({ to: "/" })} />' in login
    assert '<Page title="Sign in">' in login
    fails("make", "page", "x", "--kind", "list", match="needs --resource")
    fails("make", "page", "Bad_Name", match="kebab-case")
    fails("make", "page", "x", "--title", 'Say "hi"', match="plain text only")


def test_page_without_route_markers(project: Path) -> None:
    (project / "frontend" / "src" / "routes.tsx").write_text("export const routes = [];\n")
    fails("make", "page", "reports", match="--no-route")
    result = ok("make", "page", "reports", "--no-route")
    assert "route not registered (--no-route)" in result.output
    assert (project / "frontend" / "src" / "pages" / "reports.tsx").is_file()


def test_component_roles(project: Path) -> None:
    manifest = project / "frontend" / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"roles": {"data-table": "ResourceTable"}}))
    result = ok("make", "component", "StatusBadge")
    assert (
        'registerComponentRole("status-badge", "StatusBadge");'
        in (project / "frontend" / "src" / "components" / "StatusBadge.tsx").read_text()
    )
    assert "role: status-badge" in result.output
    fails("make", "component", "MyTable", "--role", "data-table", match="@karni/ui's ResourceTable")
    fails("make", "component", "Badge2", "--role", "status-badge", match="StatusBadge (")
    ok("make", "component", "MyTable", "--role", "data-table", "--replace-reason", "virtualised")
    source = (project / "frontend" / "src" / "components" / "MyTable.tsx").read_text()
    assert '{ replace: true, reason: "virtualised" }' in source


# public site


INCLUDE = '    path("", include("website.urls")),\n'


def test_site_creates_the_app_and_replaces_the_welcome_route(project: Path) -> None:
    result = ok("make", "site", "website")
    site = project / "website"
    for rel in (
        "apps.py",
        "models.py",
        "viewsets.py",
        "views.py",
        "urls.py",
        "templates/website/base.html",
        "templates/website/home.html",
        "templates/404.html",
        "templates/500.html",
        "static/website/site.css",
        "tests/test_pages.py",
    ):
        assert (site / rel).is_file(), rel
    settings = (project / "config" / "settings.py").read_text()
    assert '    "website",\n    "karni_site",\n]  # karni:apps' in settings
    assert '    "karni_site.middleware.RedirectMiddleware",\n]  # karni:middleware' in settings
    assert settings.endswith(
        'TEMPLATES[0]["OPTIONS"]["context_processors"] += [  # noqa: F821\n'
        '    "karni_site.context_processors.site",\n'
        "]  # karni:context_processors\n"
    )
    # The site's runtime is the karni-site module, wired as `karni add site` does.
    assert '"karni-site"' in (project / "pyproject.toml").read_text()
    assert "karni-site: added to pyproject.toml and INSTALLED_APPS" in result.output
    assert "Run `karni add site` again after installing" in result.output
    views = (site / "views.py").read_text()
    assert "def home(request: HttpRequest) -> HttpResponse:" in views
    assert 'return render(request, "website/home.html")' in views
    urls = (site / "urls.py").read_text()
    assert 'app_name = "website"' in urls
    assert '    path("", views.home, name="home"),\n    # karni:urls\n]' in urls
    config = (project / "config" / "urls.py").read_text()
    # Before the welcome route, so "/" is the site's.
    marker = config.index("    # karni:urls\n")
    assert config.index(INCLUDE) < marker < config.index("    *welcome_urls(),")
    base = (site / "templates" / "website" / "base.html").read_text()
    assert base.startswith("{% load static karni_site %}{# The site's details are `site`")
    assert '{% site_defaults name="Website" %}<!DOCTYPE html>' in base
    assert '<link rel="canonical"' in base and "{% static 'website/site.css' %}" in base
    assert (
        '<a href="{% url \'website:home\' %}"{% ifactive "website:home" %} aria-current="page"'
        "{% endifactive %}>Home</a>"
    ) in base
    assert "<title>{% block title %}{{ site.name }}{% endblock %}</title>" in base
    home = (site / "templates" / "website" / "home.html").read_text()
    assert "<h1>{{ site.name }}</h1>" in home and '{% editable "home.intro" %}' in home
    assert '<meta name="description" content="{% block description %}{% endblock %}">' in base
    assert "<img" not in base
    # The page test runs assert_pages over a list that `karni make view` extends.
    test = (site / "tests" / "test_pages.py").read_text()
    assert "from karni.testing import assert_pages\n" in test
    assert 'PAGES = [\n    "/",\n    # karni:pages\n]\n' in test
    assert "    assert_pages(client, PAGES)\n" in test
    assert '{% extends "website/base.html" %}' in (site / "templates" / "404.html").read_text()
    assert "Something went wrong" in (site / "templates" / "500.html").read_text()
    assert config.endswith(
        "# The site's own error pages (templates/404.html and 500.html), rendered with the\n"
        "# request by karni_site, which falls back to a plain page if one fails.\n"
        'handler404 = "karni_site.views.page_not_found"\n'
        'handler500 = "karni_site.views.server_error"\n'
    )
    assert "modified config/urls.py" in result.output
    assert "site: / -> website.views.home (website:home)" in result.output
    assert "next: karni import design <folder> --app website" in result.output
    assert "karni make view <name> --app website" in result.output
    assert "karni make model" not in result.output


def test_site_is_idempotent_and_never_truncates(project: Path) -> None:
    ok("make", "site", "website")
    views = project / "website" / "views.py"
    views.write_text(views.read_text() + "\n\n# project code\n")
    before = snapshot(project)
    fails("make", "site", "website", match="Pass --force to create only the missing files")
    assert snapshot(project) == before
    (project / "website" / "templates" / "404.html").unlink()
    ok("make", "site", "website", "--force")
    assert (project / "website" / "templates" / "404.html").is_file()
    assert "# project code" in views.read_text()
    assert views.read_text().count("def home(") == 1
    config = (project / "config" / "urls.py").read_text()
    assert config.count(INCLUDE) == 1 and config.count("handler404 = ") == 1
    settings = (project / "config" / "settings.py").read_text()
    assert settings.count('"karni_site"') == 1
    assert settings.count("RedirectMiddleware") == settings.count("context_processors.site") == 1
    urls = (project / "website" / "urls.py").read_text()
    assert urls.count('path("", views.home, name="home")') == 1


def test_site_on_an_existing_app_adds_only_the_site_files(project: Path) -> None:
    ok("make", "app", "content")
    models = project / "content" / "models.py"
    before = models.read_text()
    result = ok("make", "site", "content")
    assert models.read_text() == before
    assert "created  content/apps.py" not in result.output
    assert (project / "content" / "templates" / "content" / "base.html").is_file()
    config = (project / "config" / "urls.py").read_text()
    assert 'path("", include("content.urls")),' in config


def test_site_dry_run_writes_nothing(project: Path) -> None:
    before = snapshot(project)
    result = ok("make", "site", "website", "--dry-run")
    assert snapshot(project) == before
    assert "would modify config/urls.py" in result.output
    assert '+    path("", include("website.urls")),' in result.output
    assert "would create website/templates/website/base.html" in result.output
    assert "(dry run: nothing written)" in result.output


def test_site_without_the_urls_marker_names_the_manual_step(project: Path) -> None:
    config = project / "config" / "urls.py"
    config.write_text(config.read_text().replace("    # karni:urls\n", ""))
    before = snapshot(project)
    message = fails("make", "site", "website", match="No `# karni:urls` marker in config/urls.py")
    assert 'path("", include("website.urls")),' in message
    assert "before `*welcome_urls()`" in message and "karni upgrade" in message
    assert snapshot(project) == before  # a failed step writes nothing
    result = ok("make", "site", "website", "--no-route")
    assert "route not registered (--no-route)" in result.output
    assert "website.urls" not in config.read_text()


def test_site_refuses_a_second_root_include(project: Path) -> None:
    ok("make", "site", "website")
    fails("make", "site", "landing", match="already includes 'website.urls'")


def test_view_adds_the_view_its_template_and_the_url(project: Path) -> None:
    ok("make", "site", "website")
    result = ok("make", "view", "about")
    site = project / "website"
    assert "def about(request: HttpRequest) -> HttpResponse:" in (site / "views.py").read_text()
    template = (site / "templates" / "website" / "about.html").read_text()
    assert template.startswith('{% extends "website/base.html" %}')
    assert "{% block title %}About{% endblock %}" in template
    urls = (site / "urls.py").read_text()
    assert '    path("about/", views.about, name="about"),\n    # karni:urls\n' in urls
    assert "view: /about/ -> website.views.about (website:about)" in result.output
    pages = site / "tests" / "test_pages.py"
    assert 'PAGES = [\n    "/",\n    "/about/",\n    # karni:pages\n]\n' in pages.read_text()
    assert "modified website/tests/test_pages.py" in result.output

    ok("make", "view", "service", "--path", "/services/<slug:slug>/")
    ok("make:view", "invoice", "--app", "website", "--path", "/invoices/<int:number>")
    views = (site / "views.py").read_text()
    assert "def service(request: HttpRequest, slug: str) -> HttpResponse:" in views
    assert 'return render(request, "website/service.html", {"slug": slug})' in views
    assert "def invoice(request: HttpRequest, number: int) -> HttpResponse:" in views
    assert "{{ slug }}" in (site / "templates" / "website" / "service.html").read_text()
    urls = (site / "urls.py").read_text()
    assert 'path("services/<slug:slug>/", views.service, name="service"),' in urls
    assert 'path("invoices/<int:number>/", views.invoice, name="invoice"),' in urls
    # A path with a capture needs a real URL, which only the project knows.
    assert 'PAGES = [\n    "/",\n    "/about/",\n    # karni:pages\n]\n' in pages.read_text()
    service = ok("make", "view", "service", "--path", "/services/<slug:slug>/", "--force")
    assert "page test: /services/<slug:slug>/ has a capture, so it is not in " in service.output
    # --force rewrites the view and leaves one entry per URL in the test.
    ok("make", "view", "about", "--force")
    assert pages.read_text().count('"/about/",') == 1
    # The include in config/urls.py is not touched again.
    assert (project / "config" / "urls.py").read_text().count(INCLUDE) == 1


def test_view_validation(project: Path) -> None:
    ok("make", "app", "events")
    fails("make", "view", "about", "--app", "events", match="karni make site events")
    ok("make", "site", "website")
    ok("make", "view", "about", "--app", "website")
    fails("make", "view", "about", "--app", "website", match="--force")
    fails("make", "view", "team", "--app", "website", "--path", "/about/", match="already routes")
    fails("make", "view", "x", "--app", "website", "--path", "about", match="must look like")
    fails("make", "view", "render", "--app", "website", match="taken in views.py")
    fails("make", "view", "About", "--app", "website", match="snake_case")
    before = snapshot(project)
    ok("make", "view", "team", "--app", "website", "--dry-run")
    assert snapshot(project) == before


def test_view_without_the_site_urls_marker(project: Path) -> None:
    ok("make", "site", "website")
    urls = project / "website" / "urls.py"
    urls.write_text(urls.read_text().replace("    # karni:urls\n", ""))
    fails("make", "view", "about", match="No `# karni:urls` marker in website/urls.py")
    result = ok("make", "view", "about", "--no-route")
    assert "add path('about/', views.about, name='about')" in result.output
    assert "and its URL to PAGES in website/tests/test_pages.py" in result.output


def test_view_without_the_page_test_marker_or_file_names_the_manual_step(project: Path) -> None:
    ok("make", "site", "website")
    pages = project / "website" / "tests" / "test_pages.py"
    pages.write_text(pages.read_text().replace("    # karni:pages\n", ""))
    before = pages.read_text()
    result = ok("make", "view", "about")
    assert pages.read_text() == before
    assert (
        'page test: website/tests/test_pages.py has no `# karni:pages` marker. Add "/about/" '
        "to the URLs that website/tests/test_pages.py passes to assert_pages yourself."
    ) in result.output
    pages.unlink()
    result = ok("make", "view", "team")
    assert 'page test: website/tests/test_pages.py not found. Add "/team/"' in result.output
    assert not pages.exists()


# module


def test_module_outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = ok("make", "module", "live-chat")
    root = tmp_path / "modules" / "karni-live-chat"
    assert "created  modules/karni-live-chat/karni_live_chat/apps.py" in result.output
    pyproject = (root / "pyproject.toml").read_text()
    assert 'name = "karni-live-chat"' in pyproject
    assert 'live_chat = "karni_live_chat.conf:DEFAULTS"' in pyproject
    assert 'dependencies = ["karni>=0.' in pyproject
    assert (root / "karni_live_chat" / "AGENTS.fragment.md").is_file()
    assert 'label = "karni_live_chat"' in (root / "karni_live_chat" / "apps.py").read_text()
    fails("make", "module", "karni-chat", match="prefix")


# migration (through the project interpreter)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.fixture
def recorder(project: Path, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    rec = Recorder()
    monkeypatch.setattr(project_mod, "run_process", rec)
    return rec


def test_migration_wraps_makemigrations(project: Path, recorder: Recorder) -> None:
    ok("make", "app", "events")
    python = str(project / ".venv" / "bin" / "python")
    ok("make", "migration")
    ok("make", "migration", "add_capacity", "--app", "events", "--dry-run")
    ok("make", "migration", "backfill", "--empty")
    ok("make:migration")
    assert recorder.calls == [
        [python, "manage.py", "makemigrations"],
        [python, "manage.py", "makemigrations", "events", "--name", "add_capacity", "--dry-run"],
        [python, "manage.py", "makemigrations", "events", "--name", "backfill", "--empty"],
        [python, "manage.py", "makemigrations"],
    ]


def test_model_migrate_flag_runs_makemigrations(project: Path, recorder: Recorder) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "--migrate")
    assert recorder.calls == [
        [str(project / ".venv" / "bin" / "python"), "manage.py", "makemigrations", "events"]
    ]


def test_detail_pages_expand_the_model_relations(project: Path) -> None:
    """Relations render as labels, not raw ids (audit item 16); user FKs stay ids."""
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Show", "title:str", "venue:fk:Venue", "organizer:fk:User", "-a")
    page = (project / "frontend" / "src" / "pages" / "show-detail.tsx").read_text()
    assert 'expand={["venue"]}' in page


def test_a_detail_page_takes_related_tabs(project: Path) -> None:
    """Experimental: --related writes ResourceDetail's related tabs."""
    ok("make", "page", "company-detail", "--resource", "companies", "--kind", "detail",
       "--related", "deals", "--related", "people.company")  # fmt: skip
    page = (project / "frontend" / "src" / "pages" / "company-detail.tsx").read_text()
    assert 'related={["deals", "people.company"]}' in page
    assert page.count("\n") <= 50
    fails(
        "make",
        "page",
        "companies",
        "--resource",
        "companies",
        "--related",
        "deals",
        match="--related takes a detail page",
    )
    fails(
        "make", "page", "c", "--resource", "companies", "--kind", "detail", "--related", "Deal",
        match="resource.field for a related tab",
    )  # fmt: skip


def test_a_dashboard_page_counts_the_routed_resources(project: Path) -> None:
    """Experimental: --kind dashboard composes DashboardGrid and ChartCard with useResourceCounts."""
    ok("make", "app", "shop")
    ok("make", "model", "Product", "name:str", "--with", "viewset")
    ok("make", "model", "Supplier", "name:str", "--with", "viewset")
    ok("make", "page", "overview", "--kind", "dashboard")
    page = (project / "frontend" / "src" / "pages" / "overview.tsx").read_text()
    assert 'import { ChartCard, DashboardGrid, Page, useResourceCounts } from "@karni/ui";' in page
    assert '    "products", "suppliers",\n' in page
    assert "<ChartCard" in page and "<DashboardGrid>" in page and page.count("\n") <= 50
    routes = (project / "frontend" / "src" / "routes.tsx").read_text()
    assert 'path: "/overview", component: OverviewPage' in routes
    ok("make", "page", "stock", "--kind", "dashboard", "--count", "products")
    assert '    "products",\n' in (project / "frontend" / "src" / "pages" / "stock.tsx").read_text()
    fails(
        "make", "page", "x", "--kind", "dashboard", "--resource", "products",
        match="--count instead of --resource",
    )  # fmt: skip


def test_test_generator_never_drops_isolation_silently(project: Path) -> None:
    """A custom scope, or no partitioning grant at all, is named in the output and the file."""
    ok("make", "app", "events")
    settings = project / "config" / "settings.py"
    settings.write_text(
        settings.read_text()
        + '\nKARNI_ROLES = {"staff": {"system": True, "grants": {"*": "all"}}, '
        + '"member": {"grants": {"events.*": "custom:workspace"}}}\n'
    )
    result = ok("make", "model", "Event", "title:str", "--with", "viewset,test")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert "assert_isolated" not in text.split("# No assert_isolated", 1)[0]
    assert "# No assert_isolated: 'member' (custom:workspace)" in text
    assert "isolation: NOT generated" in result.output and "owner_field" in result.output


def test_a_model_names_itself_in_its_own_command(project: Path) -> None:
    """karni design analyze proposes `related:m2m:website.Course?` in Course's own command."""
    ok("make", "app", "website")
    ok("make", "model", "Course", "title:str:80", "related:m2m:website.Course?", "--app", "website")
    ok("make", "model", "Step", "title:str:80", "next:fk:Step?", "--app", "website")
    models = (project / "website" / "models.py").read_text()
    # A hand-picked list of its own kind goes one way, so a load sets each row's own list.
    assert 'related = models.ManyToManyField("self", symmetrical=False, blank=True)' in models
    assert 'next = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)' in (
        models
    )
