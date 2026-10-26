"""Build-failing checks for ``karni check``: what the site's templates rely on.

SITE001: the template engine passes the request to templates.
SITE002: every URL name a ``{% ifactive %}`` names exists.
SITE020: every form a ``{% karni_form %}`` names exists (:mod:`karni_site.form_checks`).

All are skipped when ``karni_site`` is not in ``INSTALLED_APPS``.
"""

from __future__ import annotations

import re
import sysconfig
from collections.abc import Iterator
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from django.utils.text import smart_split

__all__ = ["run_checks", "template_dirs", "url_names"]

REQUEST_CODE = "SITE001"
NAME_CODE = "SITE002"
REQUEST_PROCESSOR = "django.template.context_processors.request"
DJANGO_BACKEND = "django.template.backends.django.DjangoTemplates"
_IFACTIVE = re.compile(r"\{%-?\s*ifactive\s+(.*?)\s*-?%\}", re.S)
_WILDCARD = re.compile(r"[*?\[]")


def url_names(patterns: list[Any] | None = None, prefix: str = "") -> Iterator[str]:
    """Every ``namespace:name`` the root URLconf defines."""
    from django.urls import URLResolver, get_resolver

    if patterns is None:
        patterns = list(get_resolver().url_patterns)
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            namespace = pattern.namespace
            yield from url_names(
                list(pattern.url_patterns), f"{prefix}{namespace}:" if namespace else prefix
            )
        elif getattr(pattern, "name", None):
            yield f"{prefix}{pattern.name}"


def _installed_elsewhere(path: Path) -> bool:
    roots = {sysconfig.get_paths()[key] for key in ("purelib", "platlib")}
    text = str(path.resolve())
    return any(text.startswith(str(Path(root).resolve())) for root in roots)


def template_dirs() -> list[Path]:
    """The project's own template directories: each engine's DIRS and its apps' templates/."""
    from django.apps import apps
    from django.conf import settings

    found: list[Path] = []
    for engine in getattr(settings, "TEMPLATES", []):
        if engine.get("BACKEND") != DJANGO_BACKEND:
            continue
        found.extend(Path(directory) for directory in engine.get("DIRS", []))
        if engine.get("APP_DIRS"):
            for config in apps.get_app_configs():
                if config.name.split(".")[0] in {"django", "karni", "karni_site"}:
                    continue
                found.append(Path(config.path) / "templates")
    return [path for path in found if path.is_dir() and not _installed_elsewhere(path)]


def _request_processor_missing() -> bool:
    from django.conf import settings

    engines = [
        engine
        for engine in getattr(settings, "TEMPLATES", [])
        if engine.get("BACKEND") == DJANGO_BACKEND
    ]
    return bool(engines) and not any(
        REQUEST_PROCESSOR in (engine.get("OPTIONS", {}).get("context_processors") or [])
        for engine in engines
    )


def _unknown_names(known: set[str]) -> list[str]:
    failures: list[str] = []
    for directory in template_dirs():
        for path in sorted(directory.rglob("*.html")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _IFACTIVE.finditer(text):
                for bit in smart_split(match.group(1)):
                    if bit[:1] not in "\"'" or bit[-1:] != bit[:1]:
                        continue  # a variable: only known when the page renders
                    name = bit[1:-1]
                    if not name or name.startswith("/"):
                        continue
                    if _WILDCARD.search(name):
                        if any(fnmatchcase(candidate, name) for candidate in known):
                            continue
                    elif name in known:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(
                        f"{NAME_CODE}: {path}:{line}: {{% ifactive %}} names {name!r}, which "
                        "no URL pattern has. Use a name `karni routes` lists, or remove it."
                    )
    return failures


def run_checks() -> list[str]:
    from django.apps import apps

    if not apps.is_installed("karni_site"):
        return []  # installed in the environment, not in this project
    failures: list[str] = []
    if _request_processor_missing():
        failures.append(
            f"{REQUEST_CODE}: add {REQUEST_PROCESSOR!r} to the context_processors of TEMPLATES. "
            "{% ifactive %} and the Content-Security-Policy tags read the request."
        )
    try:
        known = set(url_names())
    except Exception as exc:  # noqa: BLE001 - Django's own check reports a broken URLconf
        failures.append(
            f"{NAME_CODE}: the URLconf does not load ({exc}), so names were not checked."
        )
        return failures
    failures.extend(_unknown_names(known))
    from karni_site.form_checks import unknown_forms  # SITE020: each {% karni_form %} name

    failures.extend(unknown_forms())
    return failures
