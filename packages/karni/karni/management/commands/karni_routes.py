"""``manage.py karni_routes`` — every URL the project serves (``karni routes``).

One row per URL pattern of the root URLconf, in resolution order: path,
HTTP methods, URL name (``namespace:name``), the view, and — for viewset
routes — the action per method, the model and the viewset's ``access``
declaration. ``--json`` prints the same rows as a JSON list for agents.

Conventions: ``HEAD``/``OPTIONS`` are implicit and omitted; a plain function
view (methods not introspectable) shows ``ANY``; DRF format-suffix duplicates
(``/api/events.<format>/``) are omitted — they mirror their base route.

Override / escape hatch: :func:`collect_routes` is importable for custom
reports; pass ``urlconf=`` for a non-root URLconf.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Model
from django.urls import URLPattern, URLResolver, get_resolver

__all__ = ["Command", "collect_routes"]

_IMPLICIT_METHODS = frozenset({"head", "options"})
#: Canonical method order (Django's), so output never depends on set ordering.
_METHOD_ORDER = ("get", "post", "put", "patch", "delete", "trace")
#: DRF ``format_suffix_patterns`` output: regex ``.<format>`` or the route converter.
_FORMAT_SUFFIX_RE = re.compile(r"\.<format>|<drf_format_suffix:format>")
_COLUMNS = ("methods", "path", "name", "view", "model", "access")


def _walk(
    patterns: list[Any], prefix: str = "", namespaces: tuple[str, ...] = ()
) -> Iterator[tuple[str, URLPattern, tuple[str, ...]]]:
    for entry in patterns:
        if isinstance(entry, URLResolver):
            nested = (*namespaces, entry.namespace) if entry.namespace else namespaces
            yield from _walk(entry.url_patterns, prefix + str(entry.pattern), nested)
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry, namespaces


def _dotted(obj: Any) -> str:
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", None)
    return f"{module}.{qualname}" if module and qualname else repr(obj)


def _model_of(view_class: type[Any]) -> type[Model] | None:
    model = getattr(view_class, "model", None)
    if isinstance(model, type) and issubclass(model, Model):
        return model
    queryset = getattr(view_class, "queryset", None)
    model = getattr(queryset, "model", None)
    return model if isinstance(model, type) and issubclass(model, Model) else None


def access_summary(view_class: type[Any]) -> str | None:
    """The viewset's ``access`` declaration as text, or ``None`` when it declares none.

    Read defensively (``getattr``): any object with a readable ``repr`` works.
    """
    access = getattr(view_class, "access", None)
    if access is None:
        return None
    return access if isinstance(access, str) else repr(access)


def _ordered(methods: Any) -> list[str]:
    """Explicit methods in canonical order, implicit HEAD/OPTIONS dropped."""
    explicit = {m.lower() for m in methods} - _IMPLICIT_METHODS
    rank = {m: i for i, m in enumerate(_METHOD_ORDER)}
    return sorted(explicit, key=lambda m: (rank.get(m, len(rank)), m))


def _route(path: str, pattern: URLPattern, namespaces: tuple[str, ...]) -> dict[str, Any]:
    """One row; ``path`` is still the raw pattern text (prettified by the caller)."""
    callback = pattern.callback
    actions: dict[str, str] | None = getattr(callback, "actions", None)
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)

    if actions:
        methods = [m.upper() for m in _ordered(actions)]
        action_map: dict[str, str] | None = {m: actions[m.lower()] for m in methods}
    elif view_class is not None:
        names = getattr(view_class, "http_method_names", ())
        methods = [m.upper() for m in _ordered(n for n in names if hasattr(view_class, n))]
        action_map = None
    else:
        methods = ["ANY"]
        action_map = None

    model = _model_of(view_class) if view_class is not None else None
    name = ":".join((*namespaces, pattern.name)) if pattern.name else None
    return {
        "path": path,
        "methods": methods,
        "name": name,
        "view": _dotted(view_class) if view_class is not None else _dotted(callback),
        "actions": action_map,
        "model": model._meta.label if model is not None else None,
        "access": access_summary(view_class) if view_class is not None and actions else None,
    }


def collect_routes(urlconf: str | None = None) -> list[dict[str, Any]]:
    """Every URL pattern of ``urlconf`` (default: ``ROOT_URLCONF``) as JSON-ready rows.

    Row keys: ``path``, ``methods``, ``name``, ``view``, ``actions``
    (method → viewset action, viewsets only), ``model`` (``app_label.Model``)
    and ``access`` (viewsets only; ``None`` when undeclared).
    """
    # Django's own regex→path prettifier (admindocs need not be installed).
    from django.contrib.admindocs.views import simplify_regex

    rows = []
    for path, pattern, namespaces in _walk(get_resolver(urlconf).url_patterns):
        row = _route(path, pattern, namespaces)
        row["path"] = simplify_regex(path)
        if _FORMAT_SUFFIX_RE.search(row["path"]):
            continue
        rows.append(row)
    return rows


def _cell(row: dict[str, Any], column: str) -> str:
    value = row[column]
    if column == "methods":
        return "|".join(value)
    if column == "view" and row["actions"]:
        return f"{value} ({', '.join(dict.fromkeys(row['actions'].values()))})"
    return "-" if value is None else str(value)


def format_table(rows: list[dict[str, Any]]) -> str:
    """Fixed-width table; the MODEL/ACCESS columns appear only when some row has them."""
    columns = [c for c in _COLUMNS if c not in ("model", "access") or any(r[c] for r in rows)]
    cells = [[_cell(row, c) for c in columns] for row in rows]
    header = [c.upper() for c in columns]
    widths = [max(len(line[i]) for line in [header, *cells]) for i in range(len(columns))]
    return "\n".join(
        "  ".join(text.ljust(width) for text, width in zip(line, widths, strict=True)).rstrip()
        for line in [header, *cells]
    )


class Command(BaseCommand):
    help = "List every URL with its methods, name, view, model and access (--json for agents)."
    # A route listing must print even when system checks fail; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="Print rows as a JSON list.")

    def handle(self, *args: Any, **options: Any) -> None:
        rows = collect_routes()
        if options["json"]:
            self.stdout.write(json.dumps(rows, indent=2))
        else:
            self.stdout.write(format_table(rows))
