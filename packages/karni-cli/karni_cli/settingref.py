"""Settings for ``karni explain KARNI_SITE_HIGHLIGHT``: Karni's own and every module's, offline.

The source is the one docs/settings.md is generated from,
:mod:`karni.conf.reference`, which is stdlib only and loaded by path under a
private name, so no Django and no project are needed. It is found in this
order:

- the monorepo's ``packages/karni/karni/conf/reference.py``;
- the karni installed next to karni-cli (located, not imported);
- the copy bundled into this wheel (``karni_cli/_settings``).

A module's settings come from its ``conf.py``: the checkout's ``modules/``,
else the modules installed next to karni-cli (``karni.settings`` entry
points). A setting none of them knows is asked of the project interpreter
(``python -m karni.conf.reference --explain NAME --json``), which has the
project's modules installed.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import Any, Final

__all__ = ["SETTING", "lookup", "reference_module", "render"]

#: What a setting's name looks like (``KARNI_SITE_HIGHLIGHT``, ``STRIPE_SECRET_KEY``). An
#: error code has no underscore (``E104``, ``PAY004``).
SETTING: Final = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

_MODULE_NAME = "karni_cli._bundled_karni_reference"


def _reference_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni" / "karni" / "conf" / "reference.py"
        if candidate.is_file():
            return candidate
    try:
        spec = importlib.util.find_spec("karni")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        installed = Path(spec.origin).parent / "conf" / "reference.py"
        if installed.is_file() and installed.with_name("base.py").is_file():
            return installed
    packaged = resources.files("karni_cli") / "_settings"
    with resources.as_file(packaged) as path:
        if (path / "reference.py").is_file():
            return path / "reference.py"
    return None


def reference_module() -> ModuleType | None:
    """``karni.conf.reference`` loaded by path (it reads ``base.py`` beside it)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    path = _reference_file()
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        return None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = loaded  # dataclasses look their module up there
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        del sys.modules[_MODULE_NAME]
        raise
    return loaded


def docs_url(anchor: str) -> str:
    """The setting's row on the settings page."""
    from karni_cli.errorcodes import _FALLBACK_BASE, core_module

    core = core_module()
    base = str(getattr(core, "DOCS_BASE_URL", "") or _FALLBACK_BASE)
    return f"{base}settings/#{anchor}"


def _from_project(name: str) -> dict[str, Any] | None:
    from karni_cli import project as project_mod

    root = project_mod.find_project()
    python = project_mod.venv_python(root) if root is not None else None
    if python is None:
        return None
    try:
        proc = subprocess.run(
            [str(python), "-m", "karni.conf.reference", "--explain", name, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("name") else None


def lookup(name: str) -> dict[str, Any] | None:
    """The setting ``name`` as a dict (name, section, module, default, env, description, url)."""
    wanted = name.strip().upper()
    reference = reference_module()
    if reference is not None:
        found = reference.lookup(wanted)
        if found is not None:
            data = dict(found.to_dict())
            data["url"] = docs_url(str(data["anchor"]))
            return data
    return _from_project(wanted)


def render(entry: dict[str, Any]) -> str:
    """The text ``karni explain`` prints for a setting."""
    module = str(entry.get("module") or "")
    where = f"a setting of {module}" if module else f"a setting, {entry.get('section')}"
    env = entry.get("env")
    default = str(entry.get("default") or "")
    if not default or default == "—":
        default = "none"
    if env:
        set_it = f"in .env or the environment as {env}=..., or in config/settings.py"
    else:
        set_it = "in config/settings.py (no environment variable reads it)"
    return "\n".join(
        [
            f"{entry['name']}  ({where})",
            "",
            f"What:     {entry.get('description') or 'no description'}",
            f"Default:  {default}",
            f"Set it:   {set_it}",
            f"Docs:     {entry.get('url') or docs_url(str(entry['name']).lower())}",
        ]
    )
