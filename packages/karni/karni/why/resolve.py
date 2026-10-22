"""What ``karni why`` is asked about: the resource, the user, the action, the request record.

Resources are the routes of the ``KARNI_API_ROUTER`` router — named by their
prefix (``events``), router basename (``events-event``) or model label
(``events.Event``). Users are found by primary key, login field, email or
username, or ``anonymous``. Actions are the viewset actions the router routes
(``retrieve``, ``partial_update``, ``destroy``, ``create``, ``list`` and every
``@action``), with the plain words ``view``/``update``/``delete`` accepted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.urls import NoReverseMatch, reverse

from karni.exceptions import KarniValueError

__all__ = [
    "ACTION_WORDS",
    "RECORD_DIR",
    "ActionSpec",
    "Resource",
    "WhyError",
    "load_record",
    "record_path",
    "resolve_action",
    "resolve_resource",
    "resolve_user",
    "resources",
]

#: Where the capture layer writes one JSON file per request (DEBUG only).
RECORD_DIR: Final = Path(".karni") / "requests"

#: Plain words for the standard actions → the viewset action they mean.
ACTION_WORDS: Final[dict[str, str]] = {
    "view": "retrieve",
    "read": "retrieve",
    "get": "retrieve",
    "retrieve": "retrieve",
    "update": "partial_update",
    "put": "update",
    "partial_update": "partial_update",
    "patch": "partial_update",
    "change": "partial_update",
    "edit": "partial_update",
    "write": "partial_update",
    "delete": "destroy",
    "destroy": "destroy",
    "remove": "destroy",
    "create": "create",
    "add": "create",
    "post": "create",
    "list": "list",
}


class WhyError(KarniValueError):
    """``karni why`` cannot answer as asked; the message names the fix (codes E901–E908)."""


@dataclass(frozen=True)
class Resource:
    """One routed viewset: its prefix, basename and class, on the router that routes it."""

    prefix: str
    basename: str
    viewset: type[Any]
    router: Any

    @property
    def model(self) -> type[Model]:
        model = getattr(self.viewset, "model", None)
        if model is None:
            model = self.viewset.queryset.model
        return model  # type: ignore[no-any-return]

    def describe(self) -> str:
        return f"{self.prefix} ({self.model._meta.label})"


@dataclass(frozen=True)
class ActionSpec:
    """A routed action: its name, HTTP method, route and the initkwargs the router passes."""

    name: str
    method: str
    detail: bool
    mapping: dict[str, str]
    initkwargs: dict[str, Any]
    url_name: str
    lookup: str = "pk"
    methods: tuple[str, ...] = field(default=())

    def path(self, resource: Resource, pk: Any = None) -> str:
        """The URL the action answers at (reversed when the router is mounted)."""
        kwargs = {self.lookup: pk} if self.detail and pk is not None else {}
        try:
            return reverse(self.url_name, kwargs=kwargs)
        except NoReverseMatch:
            suffix = f"{pk}/" if self.detail and pk is not None else ""
            extra = self.initkwargs.get("url_path")
            tail = f"{extra}/" if extra else ""
            return f"/{resource.prefix}/{suffix}{tail}"


def resources() -> list[Resource]:
    """Every route of the ``KARNI_API_ROUTER`` router, in registration order."""
    from karni.api.routers import resolve_router

    router = resolve_router()
    registry = getattr(router, "registry", None) or []
    return [Resource(prefix, basename, viewset, router) for prefix, viewset, basename in registry]


def _model_of(viewset: type[Any]) -> type[Model] | None:
    model = getattr(viewset, "model", None)
    if model is None:
        model = getattr(getattr(viewset, "queryset", None), "model", None)
    return model


def resolve_resource(name: str) -> Resource:
    """The routed resource ``name`` names: prefix, router basename or model label."""
    from karni.api.viewsets import BaseViewSet

    wanted = name.strip().strip("/")
    routed = resources()
    found = next((r for r in routed if wanted in (r.prefix, r.basename)), None)
    if found is None:
        lowered = wanted.lower()
        for resource in routed:
            model = _model_of(resource.viewset)
            if model is not None and lowered in (
                model._meta.label_lower,
                f"{model._meta.app_label}.{model._meta.model_name}",
            ):
                found = resource
                break
    if found is None:
        listing = ", ".join(
            f"{r.prefix} ({m._meta.label})" if (m := _model_of(r.viewset)) else r.prefix
            for r in routed
        )
        raise WhyError(
            f"No API resource named {name!r}. Name it as the API does: the route prefix, the "
            f"router basename or the model label. Routed resources: {listing or 'none'}. "
            "`karni routes` lists every URL.",
            code="E901",
        )
    if not issubclass(found.viewset, BaseViewSet):
        raise WhyError(
            f"{found.prefix} is served by {found.viewset.__name__}, which is not a Karni "
            "BaseViewSet: its own permission_classes decide, and karni why explains the "
            "decisions of Karni's access layer only. Read that class's permission_classes "
            "and get_queryset().",
            code="E907",
        )
    return found


def resolve_user(spec: str) -> Any:
    """The user ``spec`` names: ``anonymous``, a primary key, the login field, email or username."""
    text = spec.strip()
    if text.lower() in {"anonymous", "anon", "anonymoususer", "-"}:
        return AnonymousUser()
    user_model = get_user_model()
    manager = user_model._default_manager
    try:
        pk = user_model._meta.pk.to_python(text)
    except (ValidationError, ValueError, TypeError):
        pk = None
    if pk is not None:
        try:
            found = manager.filter(pk=pk).first()
        except (ValidationError, ValueError, TypeError):
            found = None
        if found is not None:
            return found
    names = {field.name for field in user_model._meta.concrete_fields}
    tried = ["primary key"]
    for name in dict.fromkeys([user_model.USERNAME_FIELD, "email", "username"]):
        if name not in names:
            continue
        tried.append(name)
        matches = list(manager.filter(**{f"{name}__iexact": text})[:2])
        if len(matches) == 1:
            return matches[0]
    count = manager.count()
    raise WhyError(
        f"No user matches {spec!r} (tried {', '.join(tried)}; {count} user(s) exist). Pass "
        "--as with an email, username or primary key from your data, or --as anonymous for "
        "a request that is not signed in.",
        code="E902",
    )


def resolve_action(
    resource: Resource, word: str | None, *, method: str | None = None
) -> ActionSpec:
    """The routed action ``word`` names on ``resource`` (default: ``retrieve``)."""
    router = resource.router
    viewset = resource.viewset
    name = ACTION_WORDS.get((word or "retrieve").lower(), word or "retrieve")
    lookup = getattr(viewset, "lookup_url_kwarg", None) or getattr(viewset, "lookup_field", "pk")
    available: list[str] = []
    for route in router.get_routes(viewset):
        mapping = router.get_method_map(viewset, route.mapping)
        available.extend(action for action in mapping.values() if action not in available)
        methods = tuple(m for m, action in mapping.items() if action == name)
        if not methods:
            continue
        chosen = methods[0]
        if method:
            wanted = method.lower()
            if wanted not in methods:
                raise WhyError(
                    f"{resource.prefix}: the {name} action answers "
                    f"{', '.join(m.upper() for m in methods)}, not {method.upper()}. Drop "
                    "--method or pass one of those.",
                    code="E906",
                )
            chosen = wanted
        initkwargs = dict(route.initkwargs)
        initkwargs.update({"basename": resource.basename, "detail": route.detail})
        url_name = route.name.format(basename=resource.basename)
        return ActionSpec(
            name=name,
            method=chosen.upper(),
            detail=bool(route.detail),
            mapping=dict(mapping),
            initkwargs=initkwargs,
            url_name=url_name,
            lookup=str(lookup),
            methods=tuple(m.upper() for m in methods),
        )
    words = ", ".join(sorted({w for w, a in ACTION_WORDS.items() if a in available}))
    raise WhyError(
        f"{resource.prefix} has no action {word!r}. Actions it routes: {', '.join(available)}"
        f" (plain words: {words}).",
        code="E906",
    )


# request records (written by the capture layer, read here)


def record_path(request_id: str) -> Path:
    """``<project root>/.karni/requests/<request_id>.json`` (a ``.json`` path works too)."""
    from karni.testing._source import project_root

    given = Path(request_id)
    if given.suffix == ".json" and given.is_file():
        return given
    return project_root() / RECORD_DIR / f"{request_id}.json"


#: The record fields ``karni why`` reads, and the types it needs.
_RECORD_FIELDS: Final[dict[str, type | tuple[type, ...]]] = {
    "request_id": str,
    "method": str,
    "path": str,
    "status": int,
}


def load_record(request_id: str) -> dict[str, Any]:
    """The request record the capture layer wrote for ``request_id`` (plain JSON, read only)."""
    path = record_path(request_id)
    if not path.is_file():
        raise WhyError(
            f"No request record for {request_id!r}: {path} does not exist. Records are written "
            "only while DEBUG is on, by the dev server that handled the request. Reproduce the "
            "request with the dev server running (`karni serve`) and use the request id it "
            "reports for that request, or ask about the row directly: "
            "karni why <resource>/<id> --as <user> [--action ...].",
            code="E903",
        )
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise WhyError(
            f"The request record {path} is not readable JSON ({exc}). Delete it and reproduce "
            "the request with the dev server running.",
            code="E904",
        ) from exc
    problems = []
    if not isinstance(data, dict):
        problems.append("it is not a JSON object")
    else:
        if data.get("version") != 1:
            problems.append(f"version is {data.get('version')!r}, karni why reads version 1")
        for name, kind in _RECORD_FIELDS.items():
            if not isinstance(data.get(name), kind):
                problems.append(f"{name!r} is missing or not a {getattr(kind, '__name__', kind)}")
    if problems:
        raise WhyError(
            f"The request record {path} cannot be read: {'; '.join(problems)}. Upgrade karni so "
            "the writer and the reader agree, then reproduce the request.",
            code="E904",
        )
    return data  # type: ignore[no-any-return]
