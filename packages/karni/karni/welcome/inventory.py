"""What the welcome page knows about the project, read at request time.

Models with their admin and API links, installed modules with a docs link,
the agent adapter files on disk, the live ``karni context`` text, versions
and the project's name. Nothing here reads a setting's value into the page:
links are URL paths, names are names.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

import django
from django.conf import settings
from django.urls import NoReverseMatch, reverse

import karni
from karni import links

__all__ = [
    "ADAPTERS",
    "Adapter",
    "Inventory",
    "ModelLink",
    "Module",
    "collect",
    "project_name",
    "project_root",
]

#: Agent adapter files ``karni new`` writes, with the tool each one speaks to.
ADAPTERS: tuple[tuple[str, str], ...] = (
    ("Any agent", "AGENTS.md"),
    ("Claude Code", "CLAUDE.md"),
    ("Aider", "CONVENTIONS.md"),
    ("Cursor", ".cursor/rules/karni.mdc"),
    ("GitHub Copilot", ".github/copilot-instructions.md"),
    ("Windsurf", ".windsurf/rules/karni.md"),
    ("Cline", ".clinerules/karni.md"),
    ("Junie", ".junie/AGENTS.md"),
)


@dataclass(frozen=True)
class ModelLink:
    name: str
    label: str
    admin_url: str | None
    api_url: str | None


@dataclass(frozen=True)
class Module:
    name: str
    docs_url: str


@dataclass(frozen=True)
class Adapter:
    tool: str
    path: str
    present: bool


@dataclass(frozen=True)
class Inventory:
    project: str
    models: list[ModelLink]
    modules: list[Module]
    adapters: list[Adapter]
    context: str
    versions: dict[str, str]
    links: dict[str, str]


def project_root() -> Path | None:
    """``BASE_DIR`` when the settings define it, else the parent of the URLconf's package."""
    declared = getattr(settings, "BASE_DIR", None)
    if declared:
        return Path(str(declared))
    try:
        module = import_module(settings.ROOT_URLCONF)
    except Exception:  # noqa: BLE001 - no root is a fine answer
        return None
    file = getattr(module, "__file__", None)
    return Path(file).resolve().parent.parent if file else None


def project_name() -> str:
    root = project_root()
    return root.name if root is not None else "your project"


def _api_url(model: type) -> str | None:
    from karni.api.routers import resolve_router

    for _prefix, viewset, basename in getattr(resolve_router(), "registry", ()):
        served = getattr(viewset, "model", None)
        if served is None:
            served = getattr(getattr(viewset, "queryset", None), "model", None)
        if served is model:
            try:
                return reverse(f"{basename}-list")
            except NoReverseMatch:
                return None
    return None


def models() -> list[ModelLink]:
    from karni.introspect import _domain_models

    found: list[ModelLink] = []
    for shown, model in _domain_models():
        opts = model._meta
        try:
            admin_url: str | None = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        except NoReverseMatch:
            admin_url = None
        found.append(ModelLink(shown, opts.label_lower, admin_url, _api_url(model)))
    return found


def _docs_for(distribution: str) -> str:
    try:
        urls = metadata(distribution).get_all("Project-URL") or []
    except PackageNotFoundError:
        urls = []
    for entry in urls:
        label, _, url = str(entry).partition(",")
        if label.strip().lower() == "documentation" and url.strip():
            return url.strip()
    return links.docs_page("modules.md")


def modules() -> list[Module]:
    from django.apps import apps

    from karni.introspect import module_distribution

    found: list[Module] = []
    for cfg in apps.get_app_configs():
        if "." in cfg.name or not cfg.name.startswith("karni_") or cfg.name == "karni_accounts":
            continue
        found.append(
            Module(cfg.name.removeprefix("karni_"), _docs_for(module_distribution(cfg.name)))
        )
    return sorted(found, key=lambda m: m.name)


def adapters() -> list[Adapter]:
    root = project_root()
    return [
        Adapter(tool, path, root is not None and (root / path).is_file()) for tool, path in ADAPTERS
    ]


def context_text() -> str:
    from karni.introspect import build_context

    try:
        return build_context()
    except Exception as exc:  # noqa: BLE001 - the page degrades, it never crashes
        return f"(karni context unavailable: {type(exc).__name__})"


def versions() -> dict[str, str]:
    return {
        "karni": karni.__version__,
        "django": django.get_version(),
        "python": platform.python_version(),
    }


def _path(name: str, fallback: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return fallback


def site_links() -> dict[str, str]:
    admin_path = str(getattr(settings, "KARNI_ADMIN_PATH", "admin/") or "admin/")
    return {
        "admin": "/" + admin_path.lstrip("/"),
        "api_docs": _path("swagger-ui", "/api/docs/"),
        "schema": _path("schema", "/api/schema/"),
        "ready": _path("readiness", "/health/ready/"),
        "frontend": str(getattr(settings, "KARNI_FRONTEND_URL", "") or ""),
        "docs": links.DOCS_BASE_URL,
    }


def collect() -> Inventory:
    """Everything the page renders, gathered once per request."""
    return Inventory(
        project=project_name(),
        models=models(),
        modules=modules(),
        adapters=adapters(),
        context=context_text(),
        versions=versions(),
        links=site_links(),
    )


def python_executable() -> str:
    """Only used in tests to make sure nothing path-like leaks; the page never shows it."""
    return sys.executable
