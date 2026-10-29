"""Experimental. One canonical form per meaning, so two specs compare by what they say.

Two specs that build the same project normalise to the same data: defaults
written out, ``own:<field>`` read as ``own``, access rules sorted and their
``create`` dropped when it equals ``write``, field types in one spelling
(``str`` for ``str:255``, ``choice:a|b`` for ``choice:a,b``, a lifecycle as
its explicit moves), an entity's pages in list, detail, form order, and the
site module listed whenever the kind has a site. What carries meaning in its
order stays in order: fields, pages, search fields and the ordering.

``karni spec export``'s round-trip test compares through it, and
``karni plan`` (app-builder item A2) will compare a spec with a project the
same way.

Override / escape hatch: :func:`canonical_field` is the field part on its
own, for a tool that compares single fields.
"""

from __future__ import annotations

from typing import Any

from karni_cli.generators.fields import ALIASES, parse_field
from karni_cli.generators.lifecycle_fields import _states
from karni_cli.project import CliError
from karni_cli.spec.schema import Spec

__all__ = ["canonical_field", "normalise", "role_name"]

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


def normalise(spec: Spec) -> dict[str, Any]:
    """Experimental. The canonical data of ``spec`` (see the module docstring)."""
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
                name: canonical_field(name, token) for name, token in entity["fields"].items()
            }
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
            kinds = [kind for kind in _ENTITY_PAGES if kind in kinds]
        pages.append({name: kinds})
    data["pages"] = pages
    data["seed"] = dict(sorted(data["seed"].items()))
    social = data["features"]["social_login"]
    data["features"]["social_login"] = sorted(set(social))
    return data
