"""Experimental. One canonical form per meaning, so two specs compare by what they say.

Two specs that build the same project normalise to the same data: defaults
written out, ``own:<field>`` read as ``own``, access rules sorted and their
``create`` dropped when it equals ``write``, field types in one spelling
(``str`` for ``str:255``, ``choice:a|b`` for ``choice:a,b``, a lifecycle as
its explicit moves), a field written as ``{type, was}`` as its type, an
entity's key type written out (``pk``: the project's ``KARNI_PK`` when the
spec does not say, none for an external entity), ``database: default`` as
no database, an entity's pages in list, detail, form order, a taxonomy's
tree entity as ``app.Name`` (experimental), the site module listed whenever
the kind has a site, ``navigation`` as the ``KARNI_NAVIGATION`` list it
gives (``None`` without it), an ``aggregate`` with every metric written out
when it lists none, ``global_search`` as its full mapping (fields from
``search``, the title, the subtitle, the weight) or none, and ``api_cache``
either ``false`` or ``{ttl: <seconds>}`` (``true`` is ``{ttl: 300}``, the
default lifetime). What carries meaning in its order stays in order: fields,
pages, the menu, search fields, the ordering and an aggregate's groups (the
first is what the query-scaling check groups by).

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
from karni_cli.project import CliError
from karni_cli.spec import navigation
from karni_cli.spec.catalog import DEFAULT_CACHE_TTL
from karni_cli.spec.schema import AGGREGATE_METRICS, Spec

__all__ = ["canonical_field", "global_search", "normalise", "role_name"]

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


def _entity_label(name: str, app: str, apps: dict[str, Any]) -> str:
    """``Name`` as ``app.Name``: the entity of ``app``, else the one app that has it."""
    if "." in name:
        return name
    if name in apps.get(app, {}).get("entities", {}):
        return f"{app}.{name}"
    owners = [label for label, other in apps.items() if name in other.get("entities", {})]
    return f"{owners[0]}.{name}" if len(owners) == 1 else name


def _aggregate(declared: dict[str, Any]) -> dict[str, Any]:
    """``aggregate:`` with its defaults written out: every metric when none is listed."""
    return {
        "group_by": list(dict.fromkeys(declared["group_by"])),
        "values": list(dict.fromkeys(declared["values"])),
        "metrics": sorted(set(declared["metrics"] or AGGREGATE_METRICS)),
    }


def global_search(value: Any, search: list[str]) -> dict[str, Any] | None:
    """Experimental. ``global_search`` with every default written out, or ``None`` when off.

    ``value`` is the dumped key (``False``, ``True`` or its mapping) and
    ``search`` the entity's ``search`` list, where the fields default to.
    """
    if value is False or value is None:
        return None
    mapping: dict[str, Any] = value if isinstance(value, dict) else {}
    fields = list(mapping.get("fields") or search)
    return {
        "fields": fields,
        "title": mapping.get("title") or (fields[0] if fields else None),
        "subtitle": mapping.get("subtitle"),
        "weight": float(mapping.get("weight", 1)),
    }


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
    for label, app in data["apps"].items():
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
            entity["taxonomies"] = {
                key: _entity_label(target, label, data["apps"])
                for key, target in sorted(entity["taxonomies"].items())
            }
            if entity["aggregate"] is not None:
                entity["aggregate"] = _aggregate(entity["aggregate"])
            entity["global_search"] = global_search(entity["global_search"], entity["search"])
        app["entities"] = dict(sorted(app["entities"].items()))
    data["apps"] = dict(sorted(data["apps"].items()))
    pages = []
    for item in data["pages"]:
        ((name, kinds),) = item.items()
        if name[:1].isupper():
            kinds = [kind for kind in _ENTITY_PAGES if kind in kinds]
        pages.append({name: kinds})
    data["pages"] = pages
    data["seed"] = dict(sorted(data["seed"].items()))
    # The menu as KARNI_NAVIGATION gets it: `true` and the list it means compare equal.
    data["navigation"] = navigation.menu(spec)
    social = data["features"]["social_login"]
    data["features"]["social_login"] = sorted(set(social))
    if data["features"]["api_cache"] is True:
        data["features"]["api_cache"] = {"ttl": DEFAULT_CACHE_TTL}
    return data
