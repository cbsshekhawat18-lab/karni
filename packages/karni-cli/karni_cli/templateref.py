"""Template tags for ``karni explain image``: karni-site's own reference, offline.

The source is the one docs/public-site.md's table is rendered from,
:mod:`karni_site.tagref`, which is stdlib only and loaded by path under a
private name, so no Django is needed. It is found in this order:

- the monorepo's ``modules/karni-site/karni_site/tagref.py``;
- the karni-site installed next to karni-cli (located, not imported);
- the project interpreter, which has the project's karni-site installed
  (``python -m karni_site.tagref --explain NAME``).

Content map keys (``karni explain map.items``) are karni-cli's own:
:mod:`karni_cli.design.mapref`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

__all__ = ["TAG", "docs_url", "explain", "tag_reference"]

#: What a template tag or filter looks like on the command line: ``image``,
#: ``karni_seo``, ``{% image %}``, ``{% endeditable %}``, ``|highlight``.
TAG: Final = re.compile(r"^(?:\{%.*%\}|\{\{.*\}\}|\|?[a-z][a-z_]*(?::.*)?)$", re.DOTALL)

_MODULE_NAME = "karni_cli._bundled_karni_site_tagref"


def _tagref_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "modules" / "karni-site" / "karni_site" / "tagref.py"
        if candidate.is_file():
            return candidate
    try:
        spec = importlib.util.find_spec("karni_site")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        installed = Path(spec.origin).parent / "tagref.py"
        if installed.is_file():
            return installed
    return None


def tag_reference() -> ModuleType | None:
    """``karni_site.tagref`` loaded by path, or ``None`` when no karni-site is reachable."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    path = _tagref_file()
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


def _docs_base() -> str:
    from karni_cli.errorcodes import _FALLBACK_BASE, core_module

    return str(getattr(core_module(), "DOCS_BASE_URL", "") or _FALLBACK_BASE)


def docs_url(page: str, anchor: str) -> str:
    """The published docs page ``page`` at ``anchor``."""
    return f"{_docs_base()}{page}/#{anchor}"


def _from_project(name: str, as_json: bool) -> str | None:
    """The project interpreter's answer: it has the project's karni-site installed."""
    from karni_cli import project as project_mod

    root = project_mod.find_project()
    python = project_mod.venv_python(root) if root is not None else None
    if python is None:
        return None
    command = [str(python), "-m", "karni_site.tagref", "--explain", name]
    command += ["--docs-base", _docs_base(), *(["--json"] if as_json else [])]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=30, check=False, cwd=root
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.rstrip("\n") if proc.returncode == 0 and proc.stdout.strip() else None


def explain(name: str, *, as_json: bool = False) -> str | None:
    """What ``karni explain <tag>`` prints, or ``None`` when no karni-site knows ``name``."""
    reference = tag_reference()
    if reference is not None:
        tag = reference.lookup(name)
        if tag is None:
            return None
        url = docs_url(str(reference.DOCS_PAGE), str(tag.anchor))
        if as_json:
            return json.dumps({**tag.to_dict(), "url": url}, indent=2)
        return str(reference.render(tag, url))
    return _from_project(name, as_json)
