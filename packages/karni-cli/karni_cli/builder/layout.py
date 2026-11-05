"""Experimental. Where ``karni build`` puts Karni's code and where the project's code lives.

Karni's code and the project's code live in separate files. Karni rewrites
its own files on every build and creates the project's files only once:

=================================  =============================  ==============================
What                               Karni owns (rewritten)          The project owns (created once)
=================================  =============================  ==============================
models                             ``<app>/karni/models.py``      ``<app>/models.py``
API                                ``<app>/karni/api.py``         ``<app>/viewsets.py``
seed counts                        ``<app>/karni/seeds.py``       ``<app>/seeds.py``
tests                              ``<app>/tests/karni/``         every other test
settings                           the ``# karni:spec`` block     the rest of config/settings.py
pages                              ``frontend/src/pages/karni/``  every other page
routes                             the ``// karni:spec`` blocks   the rest of routes.tsx
=================================  =============================  ==============================

:mod:`karni_cli.spec.plan` and :mod:`karni_cli.builder` both read the paths
from here, so the plan names the files the build writes.
"""

from __future__ import annotations

from typing import Final

from karni_cli.generators.naming import default_route, kebab, snake

__all__ = [
    "RECORD",
    "ROUTES",
    "ROUTES_BLOCKS",
    "SETTINGS",
    "SETTINGS_BLOCK",
    "api_file",
    "models_file",
    "page_file",
    "page_names",
    "seeds_file",
    "test_file",
]

#: Experimental. The ownership record: a sha256 of every Karni-owned file and block.
RECORD: Final = ".karni/build.json"
SETTINGS: Final = "config/settings.py"
ROUTES: Final = "frontend/src/routes.tsx"
#: Experimental. The settings block's name in the record, and its markers.
SETTINGS_BLOCK: Final = "config/settings.py"
#: Experimental. The two routes blocks (the imports, the route entries) by their names in the record.
ROUTES_BLOCKS: Final = ("frontend/src/routes.tsx imports", "frontend/src/routes.tsx routes")


def models_file(app: str) -> str:
    """Experimental. Karni's abstract model classes of ``app``."""
    return f"{app}/karni/models.py"


def api_file(app: str) -> str:
    """Experimental. Karni's viewset base classes of ``app``."""
    return f"{app}/karni/api.py"


def seeds_file(app: str) -> str:
    """Experimental. Karni's seeders of ``app`` (one per entity with a seed count)."""
    return f"{app}/karni/seeds.py"


def test_file(app: str, entity: str) -> str:
    """Experimental. Karni's API test of one entity."""
    return f"{app}/tests/karni/test_{snake(entity)}.py"


def page_names(entity: str) -> dict[str, str]:
    """Experimental. kind -> page name of an entity's pages (``karni make model -a``'s names)."""
    return {
        "list": default_route(entity),
        "detail": f"{kebab(entity)}-detail",
        "form": f"{kebab(entity)}-form",
    }


def page_file(name: str) -> str:
    """Experimental. A page Karni writes."""
    return f"frontend/src/pages/karni/{name}.tsx"
