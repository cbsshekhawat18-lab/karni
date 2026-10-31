"""Experimental. One canonical form per meaning, so two specs compare by what they say.

Two specs that build the same project normalise to the same data: defaults
written out, ``own:<field>`` read as ``own``, access rules sorted and their
``create`` dropped when it equals ``write``, field types in one spelling
(``str`` for ``str:255``, ``choice:a|b`` for ``choice:a,b``, a lifecycle as
its explicit moves), a field written as ``{type, was}`` as its type, an
entity's key type written out (``pk``: the project's ``KARNI_PK`` when the
spec does not say, none for an external entity), ``database: default`` as
no database, an entity's pages in list, detail, form order (a detail
page's related tabs each as ``app.Entity.field``), and the site module
listed whenever the kind has a site. What carries meaning in its
order stays in order: fields, pages, search fields and the ordering.

``was`` is dropped: it says how the project gets to the spec (a rename),
not what the spec describes. ``karni plan`` reads it from the
:class:`~karni_cli.spec.schema.Spec` itself.

``karni spec export``'s round-trip test compares through it, and
``karni plan`` compares a spec with a project the same way.

Override / escape hatch: :func:`canonical_field` is the field part on its
own, for a tool that compares single fields.
"""

from __future__ import annotations

from typing import Any

from karni_cli.generators.fields import ALIASES, parse_field
from karni_cli.generators.lifecycle_fields import _states
from karni_cli.generators.naming import default_route
from karni_cli.project import CliError
from karni_cli.spec.schema import Spec

__all__ = ["canonical_field", "normalise", "related_ref", "related_tab", "role_name"]

_ENTITY_PAGES = ("list", "detail", "form")


def role_name(slug: str) -> str:
    """Experimental. Karni's name for a role declared without one (``karni.accounts.roles``)."""
    return slug.replace("_", " ").replace("-", " ").title()


def canonical_field(name: str, token: str) -> str:
    """Experimental. ``token`` in its canonical spelling (unchanged when it does not parse)."""
    try:
        spec = parse_field(f"{name}:{token}")
    except CliError:
        return token
    kind = ALIASES.get(spec.kind, spec.kind)
    args = list(spec.args)
    if kind == "str" and args[:1] == ["255"]:
        args = args[1:]
    elif kind == "decimal" and args[:2] == ["10", "2"]:
        args = args[2:]
    elif kind == "percent":
        args = [
            "" if arg.lstrip("-").isdigit() and int(arg) == default else arg
            for arg, default in zip(args, (0, 100), strict=False)
        ]
    elif kind == "money" and args:
        args = [args[0].upper(), *args[1:]]
    elif kind in ("choice", "state"):
        raw = ":".join(args)
        if kind == "choice":
            values = [v.strip() for v in raw.replace(",", "|").split("|") if v.strip()]
            args = ["|".join(values)]
        else:
            try:
                states, moves, _declared = _states(name, raw)
            except CliError:
                return token
            args = ["|".join(f"{s}>{t}" for s in states for t in moves.get(s, []))]
    while args and args[-1] == "":
        args.pop()
    optional = spec.optional and not (kind == "slug" and args and not args[0].isdigit())
    return ":".join([kind, *args]) + ("?" if optional else "")


def _access(rule: Any) -> Any:
    if rule == "code":
        return "code"
    read = sorted(set(rule["read"]))
    write = sorted(set(rule["write"]))
    out: dict[str, Any] = {"read": read, "write": write}
    create = rule.get("create")
    if create is not None and sorted(set(create)) != write:
        out["create"] = sorted(set(create))
    return out


def _label(name: str, apps: dict[str, Any], app: str | None = None) -> str | None:
    """``app.Name`` for ``Name`` or ``app.Name`` (``app``'s own entity first), else None."""
    if "." in name:
        label, entity = name.split(".", 1)
        return name if entity in apps.get(label, {}).get("entities", {}) else None
    if app is not None and name in apps.get(app, {}).get("entities", {}):
        return f"{app}.{name}"
    found = [f"{label}.{name}" for label, a in apps.items() if name in a.get("entities", {})]
    return found[0] if len(found) == 1 else None


def _fks(label: str, target: str, apps: dict[str, Any]) -> list[str]:
    """The fk fields of the entity ``label`` that point at the entity ``target``."""
    app, entity = label.split(".", 1)
    fields = apps[app]["entities"][entity].get("fields", {})
    found = []
    for name, token in fields.items():
        raw = (token if isinstance(token, str) else token.get("type", "")).rstrip("?")
        kind, _, to = raw.partition(":")
        if kind == "fk" and _label(to, apps, app) == target:
            found.append(name)
    return found


def related_tab(ref: str, page: str, apps: dict[str, Any]) -> str:
    """Experimental. What ResourceDetail's ``related`` takes for ``ref``.

    The related entity's resource (``deals``), or ``resource.field``
    (``deals.partner``) when that entity has more than one fk to ``page``.
    """
    canonical = related_ref(ref, page, apps)
    label, _, field = canonical.rpartition(".")
    target = _label(page, apps)
    if not label or target is None or _label(label, apps) is None:
        return ref
    resource = default_route(label.split(".", 1)[1])
    return resource if len(_fks(label, target, apps)) == 1 else f"{resource}.{field}"


def related_ref(ref: str, page: str, apps: dict[str, Any]) -> str:
    """Experimental. A related tab as ``app.Entity.field`` (unchanged when it names none).

    ``page`` is the detail page's entity (``Name`` or ``app.Name``). A tab that names an
    entity alone takes its one fk to that entity.
    """
    parts = ref.split(".")
    field = parts[-1] if len(parts) > 1 and parts[-1][:1].islower() else None
    label = _label(".".join(parts[:-1]) if field is not None else ref, apps)
    target = _label(page, apps)
    if label is None or target is None:
        return ref
    if field is None:
        fks = _fks(label, target, apps)
        if len(fks) != 1:
            return ref
        field = fks[0]
    return f"{label}.{field}"


def _entity_page(kind: str, kinds: list[Any], page: str, apps: dict[str, Any]) -> Any:
    """``kind`` as the entry writes it (``detail`` with its related tabs), or None when absent."""
    for written in kinds:
        if written == kind:
            return kind
        if isinstance(written, dict) and kind in written:
            related = written[kind].get("related") or []
            if not related:
                return kind
            return {kind: {"related": [related_ref(ref, page, apps) for ref in related]}}
    return None


def normalise(spec: Spec, *, pk: str = "uuid") -> dict[str, Any]:
    """Experimental. The canonical data of ``spec`` (see the module docstring).

    ``pk``: the key type of an entity that does not say (the project's ``KARNI_PK``).
    """
    data = spec.model_dump(mode="json")
    if data["app"].get("recipe") is None:
        data["app"].pop("recipe", None)
    modules = {name: dict(options or {}) for name, options in data["modules"].items()}
    if data["app"]["kind"] in ("site", "site+app"):
        modules.setdefault("site", {})
    data["modules"] = dict(sorted(modules.items()))
    for slug, role in data["roles"].items():
        role["name"] = role["name"] or role_name(slug)
        role["grants"] = {
            pattern: ("own" if scope.startswith("own:") else scope)
            for pattern, scope in sorted(role["grants"].items())
        }
    data["roles"] = dict(sorted(data["roles"].items()))
    for app in data["apps"].values():
        for entity in app["entities"].values():
            entity["fields"] = {
                name: canonical_field(name, value if isinstance(value, str) else value["type"])
                for name, value in entity["fields"].items()
            }
            entity.pop("was", None)
            entity["pk"] = None if entity["external"] else (entity["pk"] or pk)
            if entity["database"] == "default":
                entity["database"] = None
            entity["access"] = _access(entity["access"])
            if isinstance(entity["audit"], list):
                entity["audit"] = sorted(entity["audit"])
            entity["scope_paths"] = dict(sorted(entity["scope_paths"].items()))
        app["entities"] = dict(sorted(app["entities"].items()))
    data["apps"] = dict(sorted(data["apps"].items()))
    pages = []
    for item in data["pages"]:
        ((name, kinds),) = item.items()
        if name[:1].isupper():
            kinds = [_entity_page(kind, kinds, name, data["apps"]) for kind in _ENTITY_PAGES]
            kinds = [kind for kind in kinds if kind is not None]
        pages.append({name: kinds})
    data["pages"] = pages
    data["seed"] = dict(sorted(data["seed"].items()))
    social = data["features"]["social_login"]
    data["features"]["social_login"] = sorted(set(social))
    return data
