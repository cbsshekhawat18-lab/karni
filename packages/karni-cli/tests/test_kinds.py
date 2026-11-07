"""Project kinds: ``karni new --kind site|app|site+app``, ``--design``, the record, the agent files.

Every kind scaffolds, records ``kind`` under ``[tool.karni]``, and states it
in ``karni context`` and the agent files. ``--design`` runs the analysis and
the editable import on every generic fixture design and prints the rest of
the site-from-design procedure. ``karni add site`` turns an app into a
site+app. The real runs (each kind's own tests, ruff and ``karni check``)
are at the end.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import kinds
from karni_cli import project as project_mod
from karni_cli.commands import context as context_cmd
from karni_cli.commands import new as new_cmd
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import TEMPLATE, require_modules
from .test_make import ok
from .test_make_gate import _karni_importable, _project_interpreter, _ruff, _ruff_available

DESIGNS = Path(__file__).parent / "fixtures" / "designs"
FIXTURES = sorted(path.name for path in DESIGNS.iterdir() if path.is_dir())
BACKEND = "MODELS: \nVIEWSETS: \nMODULES: \nBASES: BaseModel"


def _new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str, input: str | None = None):
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", *args, "-o", str(tmp_path)], input=input)
    return result


def _made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, *args: str) -> Path:
    result = _new(tmp_path, monkeypatch, name, *args)
    assert result.exit_code == 0, f"{result.output}\n{result.exception!r}"
    return tmp_path / name.lower().replace(" ", "_")


def _agents(project: Path) -> str:
    """AGENTS.md with its lines joined: the kind's paragraph wraps at 88 columns."""
    return " ".join((project / "AGENTS.md").read_text().split())


def _kind(project: Path) -> str:
    data = tomllib.loads((project / "pyproject.toml").read_text())
    return str(data["tool"]["karni"]["kind"])


def _context(project: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    return context_cmd.build_context_text(project)


# --- the kinds ------------------------------------------------------------------


def test_nobody_to_ask_makes_an_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a terminal (an agent, a script, CI): app, as `karni new` always made."""
    project = _made(tmp_path, monkeypatch, "Field Notes")
    assert _kind(project) == "app"
    assert (project / "frontend" / "package.json").is_file()
    assert not (project / "website").exists()
    settings = (project / "config" / "settings.py").read_text()
    assert "KARNI_ACCOUNTS_REGISTRATION" not in settings and "KARNI_THEME_CSS" not in settings
    assert "frontend:" in (project / "docker-compose.yml").read_text()
    agents = _agents(project)
    assert "An app (kind `app` in pyproject.toml). The stack is set, so never ask" in agents
    assert "React 18 + TypeScript" in agents and "`karni add site`" in agents
    assert _context(project, monkeypatch).splitlines()[0] == (
        "KIND: app (API + React app in frontend/)"
    )
    assert 'An app (`kind = "app"` in pyproject.toml)' in (project / "README.md").read_text()


def test_a_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _made(tmp_path, monkeypatch, "Crumb Bakery", "--kind", "site")
    assert _kind(project) == "site"
    site = project / "website"
    for rel in ("views.py", "urls.py", "templates/website/base.html", "tests/test_pages.py"):
        assert (site / rel).is_file(), rel
    settings = (project / "config" / "settings.py").read_text()
    assert '"karni_site"' in settings and "karni_site.middleware.RedirectMiddleware" in settings
    assert (
        'env.bool(  # noqa: F821\n    "KARNI_ACCOUNTS_REGISTRATION", default=False\n)' in settings
    )
    assert 'KARNI_ROLES = {"staff": KARNI_ROLES["staff"]}  # noqa: F821' in settings
    assert 'path("", include("website.urls"))' in (project / "config" / "urls.py").read_text()
    assert "karni-site" in (project / "pyproject.toml").read_text()
    # The staff app is there for staff (the requests a form collects), and the stack serves it.
    assert (project / "frontend" / "package.json").is_file()
    assert (
        "The staff app (frontend/), built into the image for /app/."
        in (project / "Caddyfile").read_text()
    )
    agents = _agents(project)
    assert "A public website (kind `site` in pyproject.toml). The stack is set" in agents
    assert "karni-site module" in agents and "Nobody signs up." in agents
    assert "Staff also have the React staff app in `frontend/`" in agents
    assert "site-from-design" in agents
    lines = _context(project, monkeypatch).splitlines()
    assert lines[0] == (
        "KIND: site (public site (Django templates on karni-site, edited in the admin); "
        "staff app in frontend/)"
    )
    assert "SITE: website(/)" in lines
    assert (project / "AGENTS.md").read_text().count("\n") <= 100


def test_a_new_site_says_how_to_make_the_first_admin_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody signs up on a site, so the next steps make the account the admin needs."""
    result = _new(tmp_path, monkeypatch, "Corner Shop", "--kind", "site", "--no-staff-app")
    assert result.exit_code == 0, result.output
    steps = result.output.split("Next steps:")[1]
    assert "  karni migrate\n  karni createsuperuser  # the first admin account: nobody " in steps
    assert "the staff role" in steps
    both = _new(tmp_path, monkeypatch, "Club House", "--kind", "site+app")
    assert both.exit_code == 0, both.output
    assert "  karni createsuperuser  # the first admin account\n" in both.output


def test_a_site_without_the_staff_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _new(tmp_path, monkeypatch, "Quiet Clinic", "--kind", "site", "--no-staff-app")
    assert result.exit_code == 0, result.output
    project = tmp_path / "quiet_clinic"
    assert not (project / "frontend").exists()
    assert "npm install" not in result.output
    assert "No staff app (frontend/): staff work in the admin." in result.output
    compose = (project / "docker-compose.yml").read_text()
    assert "frontend" not in compose and compose.endswith("  app_data:\n")
    assert "The staff app (frontend/)" not in (project / "Caddyfile").read_text()
    settings = (project / "config" / "settings.py").read_text()
    assert '\nKARNI_THEME_CSS = "karni-theme.css"\n' in settings
    agents = _agents(project)
    assert "There is no React staff app: staff work in the admin" in agents
    readme = (project / "README.md").read_text()
    assert "## Frontend" not in readme and "There is no React staff app" in readme
    assert _context(project, monkeypatch).splitlines()[0].endswith("; no staff app)")


def test_a_site_and_an_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _made(tmp_path, monkeypatch, "Bake Club", "--kind", "site+app")
    assert _kind(project) == "site+app"
    assert (project / "website" / "views.py").is_file()
    assert (project / "frontend" / "package.json").is_file()
    settings = (project / "config" / "settings.py").read_text()
    assert "KARNI_ACCOUNTS_REGISTRATION" not in settings  # people sign up for the app
    assert '"karni_site"' in settings
    agents = _agents(project)
    assert "A public website and an app (kind `site+app` in pyproject.toml)" in agents
    assert "Site pages: `karni make view`" in agents and "`karni make page`" in agents
    assert _context(project, monkeypatch).splitlines()[0] == (
        "KIND: site+app (public site (Django templates on karni-site, edited in the admin); "
        "API + React app in frontend/)"
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--kind", "app", "--no-staff-app"], "--no-staff-app leaves frontend/ out"),
        (["--kind", "site+app", "--no-staff-app"], "--no-staff-app leaves frontend/ out"),
        (["--kind", "app", "--design", str(DESIGNS / "bakery")], "--design builds a public"),
        (["--design", str(DESIGNS / "bakery" / "css")], "has no .html page"),
        (["--site-app", "Web-Site"], "Site app name 'Web-Site' must be snake_case"),
    ],
)
def test_choices_that_do_not_fit_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], message: str
) -> None:
    result = _new(tmp_path, monkeypatch, "Odd One", *args)
    assert result.exit_code != 0
    assert isinstance(result.exception, CliError) and message in str(result.exception)
    assert not (tmp_path / "odd_one").exists()  # refused before anything is written


def test_an_unknown_kind_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _new(tmp_path, monkeypatch, "Odd One", "--kind", "blog")
    assert isinstance(result.exception, CliError) and result.exception.code == "C106"
    assert "--kind 'blog' is not a kind. Use one of site, app, site+app" in str(result.exception)
    assert not (tmp_path / "odd_one").exists()


def test_the_question_in_a_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(new_cmd, "interactive", lambda: True)
    result = _new(tmp_path, monkeypatch, "Asked Site", input="site\nn\n")
    assert result.exit_code == 0, result.output
    assert "What kind of project is it?" in result.output
    for kind in kinds.KINDS:
        assert f"  {kind:<9} {kinds.summary(kind)}" in result.output
    assert "Add the staff app too" in result.output
    project = tmp_path / "asked_site"
    assert _kind(project) == "site" and not (project / "frontend").exists()

    # Enter takes the default: an app (no staff app question for an app).
    result = _new(tmp_path, monkeypatch, "Asked App", input="\n")
    assert result.exit_code == 0, result.output
    assert "Add the staff app" not in result.output
    assert _kind(tmp_path / "asked_app") == "app"


def test_the_question_with_a_design_offers_the_kinds_with_a_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(new_cmd, "interactive", lambda: True)
    result = _new(
        tmp_path, monkeypatch, "Asked Bakery", "--design", str(DESIGNS / "bakery"), input="\n\n"
    )
    assert result.exit_code == 0, result.output
    assert "  app " not in result.output.split("Kind")[0]
    assert "Kind [site]" in result.output
    assert _kind(tmp_path / "asked_bakery") == "site"


def test_the_kind_record(tmp_path: Path) -> None:
    text = '[project]\nname = "x"\n\n[tool.karni]\n# made for\nbaseline = "0.4.1"\n'
    updated = kinds.set_kind_text(text, "site")
    assert updated.endswith('baseline = "0.4.1"\nkind = "site"\n') and "# made for" in updated
    assert kinds.recorded_kind(updated) == "site"
    assert kinds.recorded_kind('[project]\nname = "x"\n') is None
    assert kinds.set_kind_text('[project]\nname = "x"\n', "app").endswith(
        '[tool.karni]\nkind = "app"\n'
    )
    with pytest.raises(CliError) as caught:
        kinds.recorded_kind('[tool.karni]\nkind = "blog"\n')
    assert caught.value.code == "C112"


def _project_kind(project: Path) -> kinds.ProjectKind:
    found = kinds.project_kind(project)
    assert found is not None
    return found


def test_a_project_without_a_kind_is_read_from_its_files(generated_project: Path) -> None:
    pyproject = generated_project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('kind = "app"\n', ""))
    found = _project_kind(generated_project)
    assert (found.kind, found.recorded, found.staff_app) == ("app", False, True)
    assert found.context_line() == (
        "KIND: app, inferred: no kind in [tool.karni] (API + React app in frontend/)"
    )
    settings = generated_project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace('    # "myapp",\n', '    "karni_site",\n'))
    assert _project_kind(generated_project).kind == "site+app"
    (generated_project / "frontend" / "package.json").unlink()
    assert _project_kind(generated_project).kind == "site"
    assert "set `kind` under `[tool.karni]`" in " ".join(
        _project_kind(generated_project).agent_lines()
    )
    pyproject.unlink()
    assert kinds.project_kind(generated_project) is None  # not a project Karni made


def test_a_kind_karni_does_not_know_stops_context_and_sync(
    runner: CliRunner, generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = generated_project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('kind = "app"', 'kind = "webiste"'))
    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["rules", "sync"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C112"
    assert "kind = 'webiste'" in str(result.exception)
    assert runner.invoke(app, ["context"]).exit_code == 1


# --- karni add site: an app gets a site --------------------------------------------


def test_add_site_turns_an_app_into_a_site_and_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _made(tmp_path, monkeypatch, "Field Notes")
    monkeypatch.chdir(project)
    result = ok("add", "site")
    assert _kind(project) == "site+app"
    assert "kind: app -> site+app (kind under [tool.karni] in pyproject.toml)" in result.output
    assert 'To go back, set kind = "app" under [tool.karni] again' in result.output
    assert "Next, the site app: karni make site website" in result.output
    agents = _agents(project)
    assert "A public website and an app (kind `site+app`" in agents
    assert "kind: " not in ok("add", "site").output  # once is enough
    ok("make", "site", "website")
    assert _kind(project) == "site+app"
    assert "Next, the site app" not in ok("add", "site").output


def test_make_site_gives_an_app_its_site_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _made(tmp_path, monkeypatch, "Field Notes")
    monkeypatch.chdir(project)
    result = ok("make", "site", "website")
    assert "kind: app -> site+app" in result.output and _kind(project) == "site+app"


# --- --design ------------------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES)
def test_design_builds_the_site_from_each_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    design = tmp_path / "design"
    shutil.copytree(DESIGNS / fixture, design)
    result = _new(tmp_path, monkeypatch, "Made From Design", "--design", str(design))
    assert result.exit_code == 0, f"{result.output}\n{result.exception!r}"
    out = result.output
    project = tmp_path / "made_from_design"
    assert _kind(project) == "site"  # --design implies a kind with a site
    assert "$ karni design analyze ../design --app website --map content/design-map.json" in out
    assert (
        "$ karni import design ../design --app website --editable --map "
        "content/design-map.json" in out
    )
    record = json.loads((project / ".karni" / "design.json").read_text())
    assert record["source"] == "../design" and record["app"] == "website"
    assert record["editable"]["enabled"] is True
    assert record["editable"]["map"] == "content/design-map.json"
    content_map = json.loads((project / "content" / "design-map.json").read_text())
    assert content_map["design"] == "../../design" and content_map["app"] == "website"
    assert (project / "website" / "templates" / "website" / "base.html").is_file()
    assert "proposed from the markup" in out and "wrote the draft map" in out
    # The next steps: set up, then the procedure from step 4 with the project's own paths.
    steps = out.split("Next steps:")[1]
    assert "  cd made_from_design\n" in steps and "karni migrate && karni test" in steps
    assert "\n  karni createsuperuser  # the first admin account: " in steps
    assert "it goes on at step 4:\n  4. Answer every decision in the map." in steps
    assert "  2. " not in steps and "  3. " not in steps
    assert "`karni design extract ../design --map content/design-map.json -o" in steps
    assert "<design folder>" not in steps and "<site app>" not in steps
    assert "  8. Turn the repeated markup into loops." in steps
    assert "`karni make form <name> <field:type> ...`" in steps
    assert "Then `karni check`." in steps and "`karni createsuperuser`" in steps
    # The staff app and the admin wear the design's brand.
    assert "staff app theme: " in out
    # karni context says where the site from the design stands.
    pages = len(record["pages"])
    assert (
        f"DESIGN: ../design in website ({pages} page(s), editable, content map "
        "content/design-map.json)"
    ) in _context(project, monkeypatch).splitlines()


def test_design_without_a_staff_app_themes_the_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _new(
        tmp_path, monkeypatch, "Plain Bakery", "--no-staff-app", "--design", str(DESIGNS / "bakery")
    )
    assert result.exit_code == 0, result.output
    theme = tmp_path / "plain_bakery" / "karni-theme.css"
    assert "admin theme: wrote karni-theme.css" in result.output
    assert "karni-theme.css: this project's values for Karni's design tokens" in theme.read_text()


def test_design_leaves_the_content_that_becomes_rows_without_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _made(tmp_path, monkeypatch, "Hill School", "--design", str(DESIGNS / "school"))
    templates = project / "website" / "templates" / "website"
    courses = (templates / "courses.html").read_text()
    # The page's own heading is a block. Its list of courses is rows: no block in an item.
    assert '{% editable "courses.main.courses" %}Courses{% endeditable %}' in courses
    items = courses.split('<ol class="course-list">')[1].split("</ol>")[0]
    assert "editable" not in items and "Wheel pottery" in items
    # A model's detail pages share the blocks of their own copy, keyed after the model.
    shared = '{% editable "course.course.from_past_classes" %}From past classes{% endeditable %}'
    for page in ("courses_pottery", "courses_drawing", "courses_weaving", "courses_printing"):
        detail = (templates / f"{page}.html").read_text()
        assert shared in detail, page
        assert '<h1 class="course__title">' in detail and "{% editable_image" not in detail
    teachers = (templates / "teachers.html").read_text()
    assert (
        "teacher__name" in teachers and '"teachers.' not in teachers.split("teacher__name")[1][:80]
    )


# --- the real runs: each kind passes its own tests, ruff and karni check -------------


def _run(project: Path, python: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run in the new project as its developer would, outside CI.

    In CI the project's first test run may not write its OpenAPI snapshot (E607),
    and a project fresh from ``karni new`` has none yet.
    """
    from karni_cli.environment import CI_ENV_VARS

    env = {k: v for k, v in os.environ.items() if k not in CI_ENV_VARS}
    return subprocess.run(
        [str(python), *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        env={**env, "PYTHONPATH": str(project)},
    )


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
@pytest.mark.parametrize(
    "args",
    [
        ["--kind", "app"],
        ["--kind", "site"],
        ["--kind", "site", "--no-staff-app"],
        ["--kind", "site+app"],
        ["--kind", "site", "--design", str(DESIGNS / "school")],
        ["--kind", "site+app", "--design", str(DESIGNS / "bakery")],
    ],
    ids=["app", "site", "site-no-staff-app", "site+app", "site-design", "site+app-design"],
)
def test_each_kind_passes_its_own_tests_lint_and_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    require_modules("karni-site")
    project = _made(tmp_path, monkeypatch, "Kind Check", *args)
    monkeypatch.chdir(project)
    python = _project_interpreter(project, tmp_path, monkeypatch)
    ok("migrate")
    checked = _run(project, python, "manage.py", "karni_check")
    assert checked.returncode == 0, checked.stdout[-3000:] + checked.stderr[-3000:]
    tests = _run(project, python, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    assert tests.returncode == 0, tests.stdout[-3000:] + tests.stderr[-3000:]
    if not _ruff_available():
        pytest.skip("ruff is not installed in this interpreter")
    # The whole project for what breaks code (an undefined name), and what the kind wrote
    # (the site app, the settings and urls it edits) under a strict selection and the format.
    written = [str(p) for p in ("website", "config/settings.py", "config/urls.py")]
    written = [rel for rel in written if (project / rel).exists()]
    for ruff_args in (
        ["check", "--isolated", "--target-version", "py312", "--select", "E4,E7,E9,F", "."],
        ["check", "--isolated", "--target-version", "py312", "--extend-select",
         "E,W,F,I,UP,B,RUF", *written],
        ["format", "--isolated", "--check", *written],
    ):  # fmt: skip
        proc = _ruff(project, *ruff_args)
        assert proc.returncode == 0, f"ruff {ruff_args[0]}:\n{proc.stdout}{proc.stderr}"


# --- karni import design --map --------------------------------------------------


def test_import_follows_the_content_map_and_remembers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _made(tmp_path, monkeypatch, "Hill School", "--kind", "site")
    monkeypatch.chdir(project)
    school = str(DESIGNS / "school")
    analysis = ok("design", "analyze", school, "--map", "content/design-map.json").output
    # A relation to its own model goes in the model's own command (make model reads it as self).
    assert (
        "hand-picked: add `related:m2m:website.Course?` to the Course command and remove the "
        "decide from the map"
    ) in analysis
    result = ok("import", "design", school, "--editable", "--map", "content/design-map.json")
    assert "rows: " in result.output and "are content the map reads into rows" in result.output
    record = json.loads((project / ".karni" / "design.json").read_text())
    assert record["editable"]["map"] == "content/design-map.json"
    courses = project / "website" / "templates" / "website" / "courses.html"
    assert "editable" not in courses.read_text().split('<ol class="course-list">')[1]

    # A later import follows the recorded map, until the map is gone.
    assert "are content the map reads into rows" in ok("import", "design", school).output
    (project / "content" / "design-map.json").unlink()
    result = ok("import", "design", school)
    assert "content/design-map.json: the content map the last import followed is gone" in (
        result.output
    )
    assert '{% editable "courses.main.wheel_pottery" %}' in courses.read_text()
    assert "map" not in json.loads((project / ".karni" / "design.json").read_text())["editable"]


def test_import_map_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _made(tmp_path, monkeypatch, "Hill School", "--kind", "site")
    monkeypatch.chdir(project)
    school = str(DESIGNS / "school")
    result = CliRunner().invoke(app, ["import", "design", school, "--editable", "--map", "x.json"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C121"
    assert "karni design analyze <design folder> --map x.json" in str(result.exception)
    (project / "bad.json").write_text('{"models": {}}')
    result = CliRunner().invoke(
        app, ["import", "design", school, "--editable", "--map", "bad.json"]
    )
    assert isinstance(result.exception, CliError) and result.exception.code == "C121"
    ok("design", "analyze", school, "--map", "content/design-map.json")
    result = ok("import", "design", school, "--no-editable", "--map", "content/design-map.json")
    assert "--map changes only an editable import" in result.output


def test_the_admin_theme_file_a_project_without_a_staff_app_names(tmp_path: Path) -> None:
    from karni_cli.commands.ui import admin_theme_file

    assert admin_theme_file(tmp_path) is None
    settings = tmp_path / "config" / "settings.py"
    settings.parent.mkdir()
    settings.write_text('# KARNI_THEME_CSS = "nope.css"\nX = 1\n')
    assert admin_theme_file(tmp_path) is None
    settings.write_text('KARNI_THEME_CSS = "a.css"\nKARNI_THEME_CSS = "brand/theme.css"  # ours\n')
    assert admin_theme_file(tmp_path) == tmp_path / "brand" / "theme.css"
