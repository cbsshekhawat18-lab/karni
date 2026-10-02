"""``karni make module <name>`` — a reusable Karni module skeleton (docs/modules.md).

Writes ``modules/karni-<name>/``: the ``karni-<name>`` distribution with the
``karni_<name>`` app (label ``karni_<name>``), a range-pinned karni
dependency, the ``karni.settings`` fragment entry point, ``AGENTS.fragment.md``
pinned as package data, and a standalone test suite. Projects install it
with ``karni add <name>``.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import typer

from karni_cli import __version__
from karni_cli.generators.core import DRY_RUN_OPTION, Workspace
from karni_cli.generators.naming import humanize, pascal
from karni_cli.project import CliError, find_project

NAME = "module"
SUMMARY = "Create a reusable module skeleton: modules/karni-<name>/ (docs/modules.md)."

_NAME = re.compile(r"^[a-z][a-z0-9]*([_-][a-z0-9]+)*$")


def karni_pin() -> str:
    """``karni>=X.Y,<…`` for the karni this CLI sees (0.x: pin the minor)."""
    try:
        version = metadata.version("karni")
    except metadata.PackageNotFoundError:
        version = __version__
    parts = [int(p) for p in re.findall(r"\d+", version)[:2]] + [0, 0]
    major, minor = parts[0], parts[1]
    upper = f"0.{minor + 1}" if major == 0 else str(major + 1)
    return f"karni>={major}.{minor},<{upper}"


def files(name: str) -> dict[str, str]:
    """Relative path → content for the module ``name`` (``payments`` / ``live-chat``)."""
    dist = f"karni-{name.replace('_', '-')}"
    app = f"karni_{name.replace('-', '_')}"
    entry = name.replace("-", "_")
    title = humanize(name)
    config = f"Karni{pascal(name)}Config"
    upper = entry.upper()
    return {
        "pyproject.toml": f"""[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{dist}"
version = "0.1.0"
description = "{title} module for Karni."
readme = "README.md"
requires-python = ">=3.12"
# Range-pinned per the module contract (docs/modules.md): karni 0.x minors may break.
dependencies = ["{karni_pin()}"]

# The settings fragment: karni_settings() merges DEFAULTS into every project
# that installs this module (new top-level names only).
[project.entry-points."karni.settings"]
{entry} = "{app}.conf:DEFAULTS"

[dependency-groups]
dev = ["pytest>=8.2", "pytest-django>=4.8", "ruff>=0.5"]

[tool.hatch.build.targets.wheel]
packages = ["{app}"]
# `karni add` reads the agent guidance through importlib.resources after install.
artifacts = ["{app}/AGENTS.fragment.md"]

[tool.hatch.build.targets.sdist]
artifacts = ["{app}/AGENTS.fragment.md"]

[tool.ruff]
target-version = "py312"
line-length = 100
extend-exclude = ["{app}/migrations"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "tests.settings"
# Inside a project checkout, never pick up the project's manage.py / tests package.
django_find_project = false
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-ra"
""",
        "README.md": f"""# {dist}

{title} for Karni projects.

## Install

```sh
pip install {dist}
karni add {name}
```

`karni add {name}` adds the dependency, wires `{app}` into the `# karni:apps`
block and records this module's agent guidance. Then `karni migrate`.

## Settings

Every setting arrives through the module's settings fragment
(`{app}.conf.DEFAULTS`) and is overridable in the project's settings.py or
by its environment variable.

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| | | | |

## Escape hatches

Document every override point here (settings-driven dotted paths,
overridable methods, swappable classes).
""",
        f"{app}/__init__.py": "",
        f"{app}/AGENTS.fragment.md": f"""## {title} ({dist})
- What the module provides, and the one `config/urls.py` include line if it ships URLs.
- Env vars it reads (prefix {upper}_).
- Configure it only through its documented settings; never patch its internals.
""",
        f"{app}/apps.py": f'''"""Django app configuration for ``{app}``."""

from django.apps import AppConfig


class {config}(AppConfig):
    """App config for the {title} module (label ``{app}``).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass; keep the label ``{app}`` so the
    shipped migrations keep applying.
    """

    name = "{app}"
    label = "{app}"
    verbose_name = "Karni {title.lower()}"
    default_auto_field = "django.db.models.BigAutoField"
''',
        f"{app}/conf.py": f'''"""Settings vocabulary for {dist}: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Override / escape hatch: define any of these names in the project's
settings.py, or set the environment variable.
"""

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {{
    # "{upper}_ENABLED": env.bool("{upper}_ENABLED", default=True),
}}


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])
''',
        f"{app}/models.py": f'"""{title} models, each on karni.models.BaseModel."""\n',
        f"{app}/viewsets.py": (
            f'"""{title} API: BaseViewSet subclasses (auto-routed), each with `access`."""\n'
        ),
        f"{app}/migrations/__init__.py": "",
        "tests/__init__.py": "",
        "tests/settings.py": f'''"""Settings for {dist}'s standalone test suite (sqlite, eager Celery)."""

from karni.conf import karni_settings

SECRET_KEY = "{dist}-tests-secret-key-not-for-production"
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}}}
CACHES = {{"default": {{"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["{app}"]  # type: ignore[name-defined]  # noqa: F821
''',
        "tests/urls.py": """from django.urls import include, path

urlpatterns = [path("api/", include("karni.api.urls"))]
""",
        "tests/test_app.py": f'''from django.apps import apps

from {app} import conf


def test_app_is_installed() -> None:
    assert apps.get_app_config("{app}").name == "{app}"


def test_settings_fragment_is_a_dict() -> None:
    assert isinstance(conf.DEFAULTS, dict)
''',
    }


def plan(ws: Workspace, name: str, parent: Path) -> Path:
    if not _NAME.match(name):
        raise CliError(
            f"Module name {name!r}: lowercase letters and digits, words joined by - or _ "
            "(e.g. payments, live-chat)."
        )
    if name == "karni" or name.startswith(("karni-", "karni_")):
        raise CliError(f"Module name {name!r}: drop the karni prefix — it is added for you.")
    target = parent / f"karni-{name.replace('_', '-')}"
    ws.create_skeleton({target / rel: content for rel, content in files(name).items()})
    ws.note(f"next: cd {ws.rel(target)} && python -m pytest   ·   in a project: karni add {name}")
    return target


def command(
    name: str = typer.Argument(..., help="Module short name (e.g. payments, live-chat)."),
    directory: Path | None = typer.Option(
        None, "--dir", help="Parent directory (default: modules/ in the project, else the cwd)."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Create only the missing files of an existing module (keeps the rest).",
    ),
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Create modules/karni-NAME/ — a reusable module per docs/modules.md.

    The karni-NAME distribution with the karni_NAME app, a range-pinned
    karni dependency, the karni.settings fragment, AGENTS.fragment.md and a
    standalone test suite. Works outside a project too.
    """
    root = find_project() or Path.cwd()
    ws = Workspace(root, force=force)
    parent = (Path.cwd() / directory) if directory is not None else ws.root / "modules"
    plan(ws, name, parent.resolve())
    ws.commit(dry_run=dry_run)
