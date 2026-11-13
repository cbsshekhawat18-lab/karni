"""Experimental. Several recipes in one project: a part's karni.yaml merged into the project's.

A recipe in a project is a **part**: one Django app whose app label is its
**prefix**. ``app.recipes`` lists the parts. :func:`merge` copies a part's
spec fragment (the recipe's ``karni.yaml``) into the project's spec once, by
the rules below, and the project owns the result. :func:`unmerge` takes a
part out again. Both work on the spec's data (a mapping read from YAML) and
write nothing: :mod:`karni_cli.commands.recipes` writes karni.yaml and the
record, then runs ``karni build``.

Key by key:

- ``version``: must be equal (``C214``).
- ``app``: the project's name and kind stay. ``currency``: the project's, or
  the part's when the project has none. A part's ``money:XYZ`` fields are
  written as ``money`` (they read ``app.currency``), and the payments
  module's ``currency`` follows ``app.currency``.
- ``modules``: union. An option the project set itself keeps its value. Two
  parts asking for different values of an option are refused (``C445``).
- ``features``: union. ``terms`` keeps the project's version.
- ``roles``: the family roles ``admin`` and ``customer`` add up their grants
  and keep the project's name. Every other slug is new to the project, and,
  once the project holds another part, starts with the part's prefix
  (``bookings-staff``), holds no ``"*"`` and is not a default role
  (``C443``). The first part keeps its roles as the recipe wrote them. With the people contract on, ``admin``
  gets its explicit grants (``people.*:merge``, ``people.person:erase``).
- ``apps``: the part's app label is new (``C442``), and its pages live under
  ``apps.<label>.route`` (``/<label>`` by default), which must be its own and
  not a family route (``C444``).
- ``pages``: appended. The home page is the family's: a part that lists
  ``home`` when the project has one, or a page at another family route, is
  refused (``C444``). The project always gets ``home: dashboard``.
- ``navigation``: a part's list becomes one group, labelled with the
  recipe's title, in the project's menu. With one part installed its entries
  stay flat.
- ``seed``: counts are added per entity.

A recipe's ``requires`` (``people>=1``, ``events>=1``, a module) must be
met (``C446``): a core contract is switched on (``features.people``,
``features.events``) and a module is listed under ``modules``. Its
``conflicts`` names recipes and modules it cannot share a project with
(``C447``). Every refusal names both parts, the key and the change that
resolves it, and nothing is written.

Override / escape hatch: :func:`merge` and :func:`unmerge` take and return
data, so a tool can merge a recipe of its own, check the result with
:func:`karni_cli.spec.validate.validate_text` and write it when it wants to.
:data:`CONTRACTS` lists the core contracts a recipe may require.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from karni_cli.project import CliError
from karni_cli.spec.catalog import contracts_with_needs

__all__ = [
    "ADMIN_CONTRACT_GRANTS",
    "CONTRACTS",
    "FAMILY_PAGES",
    "FAMILY_ROLES",
    "FAMILY_ROUTES",
    "Merged",
    "Requirement",
    "merge",
    "parse_requirement",
    "part_route",
    "unmerge",
]

#: Experimental. The core contracts a recipe may require, and the version this release has.
#: ``features.<name>`` switches each one on.
CONTRACTS: Final[dict[str, int]] = {"people": 1, "events": 1, "timeline": 1}
#: Experimental. The roles every part shares. Every other role is ``<prefix>-<role>``.
FAMILY_ROLES: Final = ("admin", "customer")
#: Experimental. Pages that belong to the family (core and commerce), never to a part.
FAMILY_PAGES: Final[dict[str, str]] = {
    "home": "/",
    "signin": "/signin",
    "account": "/account",
    "search": "/search",
    "inbox": "/inbox",
    "settings": "/settings",
    "people": "/people",
    "cart": "/cart",
    "checkout": "/checkout",
    "orders": "/orders",
}
#: Experimental. The routes of :data:`FAMILY_PAGES`: no part's base may take one.
FAMILY_ROUTES: Final = frozenset(FAMILY_PAGES.values())
#: Experimental. The grants ``admin`` gets when a contract is on: the explicit actions ``"*"``
#: does not reach.
ADMIN_CONTRACT_GRANTS: Final[dict[str, dict[str, str]]] = {
    "people": {"people.*:merge": "all", "people.person:erase": "all"},
}
#: The module option that follows ``app.currency``.
_CURRENCY_OPTIONS: Final = {"payments": "currency"}
_REQUIREMENT: Final = re.compile(
    r"^\s*(?P<name>[a-z][a-z0-9_-]*)\s*(?P<rest>(?:(?:>=|<=|==|!=|>|<)\s*\d+(?:\.\d+)*\s*,?\s*)*)$"
)
_CONSTRAINT: Final = re.compile(r"(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+)*)")
_MONEY: Final = re.compile(r"^money:([A-Za-z]{3})(?=$|[:?])")


@dataclass(frozen=True)
class Requirement:
    """Experimental. One entry of recipe.toml's ``requires``: a name and its version range."""

    name: str
    constraints: tuple[tuple[str, tuple[int, ...]], ...] = ()
    text: str = ""

    def allows(self, version: int | tuple[int, ...] | None) -> bool:
        """Whether ``version`` is in the range (an unknown version passes no constraint)."""
        if not self.constraints:
            return True
        if version is None:
            return False
        have = (version,) if isinstance(version, int) else version
        width = max(len(have), *(len(v) for _op, v in self.constraints))

        def pad(v: tuple[int, ...]) -> tuple[int, ...]:
            return v + (0,) * (width - len(v))

        checks = {
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
        }
        return all(checks[op](pad(have), pad(v)) for op, v in self.constraints)


def parse_requirement(text: str) -> Requirement:
    """Experimental. ``"events>=1"``, ``"people>=1,<2"`` or ``"storage"`` as a :class:`Requirement`.

    :raises ValueError: for anything else.
    """
    found = _REQUIREMENT.match(text)
    if found is None:
        raise ValueError(
            f"{text!r} is not a requirement: write a name with an optional version range, "
            'e.g. "people>=1", "events>=1,<2" or "storage".'
        )
    constraints = tuple(
        (op, tuple(int(part) for part in number.split(".")))
        for op, number in _CONSTRAINT.findall(found.group("rest"))
    )
    return Requirement(found.group("name"), constraints, text.strip())


@dataclass
class Merged:
    """Experimental. The project's spec data after a merge, and what the merge did."""

    data: dict[str, Any]
    #: One line per thing the merge did that a person should know (a value kept, a grant added).
    notes: list[str] = field(default_factory=list)
    #: The keys of the spec the merge changed, as paths (for an edit that keeps the file's layout).
    changed: list[tuple[str, ...]] = field(default_factory=list)


@dataclass(frozen=True)
class _Part:
    """What the merge needs to know about a recipe."""

    name: str
    title: str
    requires: tuple[str, ...]
    conflicts: tuple[str, ...]


def _part(recipe: Any) -> _Part:
    return _Part(
        str(recipe.name),
        str(getattr(recipe, "title", recipe.name)),
        tuple(getattr(recipe, "requires", ()) or ()),
        tuple(getattr(recipe, "conflicts", ()) or ()),
    )


def installed(data: Mapping[str, Any]) -> list[str]:
    """Experimental. The parts a spec's data lists: ``app.recipes``, or the old ``app.recipe``."""
    app = data.get("app") or {}
    listed = app.get("recipes")
    if isinstance(listed, list):
        return [str(name) for name in listed]
    single = app.get("recipe")
    return [str(single)] if isinstance(single, str) and single else []


def part_route(label: str, app: Mapping[str, Any] | None = None) -> str:
    """Experimental. The base a part's pages are mounted under: its ``route``, else ``/<label>``."""
    route = (app or {}).get("route") if isinstance(app, Mapping) else None
    return str(route) if route else f"/{label}"


def _fixed(message: str, fix: str) -> str:
    """A refusal's text: what is wrong, then the one change that resolves it."""
    return f"{message} Fix: {fix}"


def _labels(fragment: Mapping[str, Any]) -> list[str]:
    return [str(label) for label in (fragment.get("apps") or {})]


def _check_requires(part: _Part, data: Mapping[str, Any], modules: Mapping[str, Any]) -> None:
    for text in part.requires:
        try:
            wanted = parse_requirement(text)
        except ValueError as exc:
            raise CliError(
                _fixed(f"The recipe {part.name}'s requires has {exc}", "Correct recipe.toml."),
                code="C446",
            ) from None
        if wanted.name in CONTRACTS:
            if not wanted.allows(CONTRACTS[wanted.name]):
                raise CliError(
                    _fixed(
                        f"The recipe {part.name} requires {wanted.text}, and this Karni has version "
                        f"{CONTRACTS[wanted.name]} of the {wanted.name} contract.",
                        "Upgrade Karni and karni-cli (karni upgrade), or use a version of the recipe "
                        "made for this one.",
                    ),
                    code="C446",
                )
            continue
        if wanted.name in modules:
            continue
        raise CliError(
            _fixed(
                f"The recipe {part.name} requires {wanted.text}, which is neither a core contract "
                f"({', '.join(CONTRACTS)}) nor a module this karni-cli knows "
                f"({', '.join(sorted(modules)) or 'none'}).",
                f"Install the module (pip install karni-{wanted.name}) so karni-cli knows it, then "
                "add the recipe again.",
            ),
            code="C446",
        )


def _check_conflicts(
    part: _Part, data: Mapping[str, Any], parts: Mapping[str, _Part], labels: Sequence[str]
) -> None:
    present = installed(data)
    listed_modules = set((data.get("modules") or {}).keys())
    for name in part.conflicts:
        if name in present or name in listed_modules:
            what = "recipe" if name in present else "module"
            raise CliError(
                _fixed(
                    f"The recipe {part.name} cannot share a project with the {what} {name} (its "
                    "recipe.toml lists it under conflicts).",
                    f"Remove {name} first (karni recipes remove {name}), or leave {part.name} out.",
                ),
                code="C447",
            )
    for other in present:
        theirs = parts.get(other)
        if theirs is not None and part.name in theirs.conflicts:
            raise CliError(
                _fixed(
                    f"The recipe {other}, already in this project, cannot share it with {part.name} "
                    f"(its recipe.toml lists {part.name} under conflicts).",
                    f"Remove {other} first (karni recipes remove {other}), or leave {part.name} out.",
                ),
                code="C447",
            )


def _base_values(bases: Mapping[str, Mapping[str, Any]], *path: str) -> dict[str, Any]:
    """The value each installed part's base fragment has at ``path``, by part."""
    found: dict[str, Any] = {}
    for name, base in bases.items():
        node: Any = base
        for key in path:
            node = node.get(key) if isinstance(node, Mapping) else None
        if node is not None:
            found[name] = node
    return found


def _currency(value: Any) -> str | None:
    return value.upper() if isinstance(value, str) and len(value) == 3 else None


def _merge_modules(
    out: dict[str, Any],
    part: _Part,
    fragment: Mapping[str, Any],
    bases: Mapping[str, Mapping[str, Any]],
    merged: Merged,
) -> None:
    modules: dict[str, Any] = out.setdefault("modules", {}) or {}
    out["modules"] = modules
    for module, options in (fragment.get("modules") or {}).items():
        mine = dict(modules.get(module) or {})
        added = module not in modules
        for option, value in (options or {}).items():
            if _CURRENCY_OPTIONS.get(module) == option:
                continue  # follows app.currency below
            if option not in mine:
                mine[option] = copy.deepcopy(value)
                continue
            if mine[option] == value:
                continue
            asked = {
                name: theirs
                for name, theirs in _base_values(bases, "modules", module, option).items()
                if theirs == mine[option]
            }
            if asked:
                other = min(asked)
                raise CliError(
                    _fixed(
                        f"modules.{module}.{option}: the recipe {other} sets {mine[option]!r} and the "
                        f"recipe {part.name} sets {value!r}.",
                        f"Choose one value and write it in karni.yaml under modules.{module}.{option} "
                        "(a value the project writes itself wins), then add the recipe again.",
                    ),
                    code="C445",
                )
            merged.notes.append(
                f"modules.{module}.{option}: kept the project's {mine[option]!r} ({part.name} "
                f"asks for {value!r})."
            )
        if added or mine != modules.get(module):
            modules[module] = mine
            merged.changed.append(("modules", module))


def _merge_features(out: dict[str, Any], fragment: Mapping[str, Any], merged: Merged) -> None:
    theirs = fragment.get("features") or {}
    if not theirs:
        return
    mine: dict[str, Any] = dict(out.get("features") or {})
    before = copy.deepcopy(mine)
    for key, value in theirs.items():
        if key not in mine or mine[key] in (None, False, [], {}):
            mine[key] = copy.deepcopy(value)
        elif key == "social_login":
            have = mine[key] if isinstance(mine[key], list) else [mine[key]]
            add = value if isinstance(value, list) else [value]
            mine[key] = [*have, *[p for p in add if p not in have]]
        elif key == "terms" and isinstance(mine[key], dict) and isinstance(value, dict):
            paths = list(mine[key].get("paths") or [])
            for path in value.get("paths") or []:
                if path not in paths:
                    paths.append(path)
            if paths:
                mine[key] = {**mine[key], "paths": paths}
    if mine != before:
        out["features"] = mine
        merged.changed.append(("features",))


def _merge_roles(
    out: dict[str, Any], part: _Part, fragment: Mapping[str, Any], merged: Merged, *, alone: bool
) -> None:
    prefixes = _labels(fragment)
    roles: dict[str, Any] = dict(out.get("roles") or {})
    for slug, role in (fragment.get("roles") or {}).items():
        role = dict(role or {})
        if slug in FAMILY_ROLES:
            if slug not in roles:
                roles[slug] = copy.deepcopy(role)
            else:
                mine = dict(roles[slug] or {})
                grants = dict(mine.get("grants") or {})
                for pattern, scope in (role.get("grants") or {}).items():
                    grants.setdefault(pattern, scope)
                mine["grants"] = grants
                roles[slug] = mine
            merged.changed.append(("roles", slug))
            continue
        if slug in roles:
            raise CliError(
                _fixed(
                    f"roles.{slug}: the project has a role {slug} already, and the recipe "
                    f"{part.name} declares it too.",
                    f"Rename the project's role, or remove the part that brought it (karni recipes "
                    f"remove), then add {part.name} again.",
                ),
                code="C443",
            )
        if alone:  # the first part keeps its roles as the recipe wrote them
            roles[slug] = copy.deepcopy(role)
            merged.changed.append(("roles", slug))
            continue
        fixed = f"{prefixes[0]}-{slug}" if prefixes else f"<prefix>-{slug}"
        if not any(slug.startswith(f"{prefix}-") for prefix in prefixes):
            raise CliError(
                _fixed(
                    f"roles.{slug}: a role of the recipe {part.name} must be named "
                    f"<prefix>-<role> (its app label {', '.join(prefixes)} first), or be a family "
                    f"role ({', '.join(FAMILY_ROLES)}).",
                    f"Rename it {fixed} in the recipe's karni.yaml (and every role:{slug} and "
                    "client_as/user_with_roles in its files).",
                ),
                code="C443",
            )
        grants = role.get("grants") or {}
        if "*" in grants:
            raise CliError(
                _fixed(
                    f'roles.{slug}: the recipe {part.name}\'s role holds "*". Only admin holds every '
                    "permission.",
                    f"Grant {slug} its own app's patterns ({prefixes[0] if prefixes else 'app'}.*) "
                    "and the contracts it uses.",
                ),
                code="C443",
            )
        if role.get("default"):
            raise CliError(
                _fixed(
                    f"roles.{slug}: the recipe {part.name} makes it a default role. customer is the "
                    "one role every sign-up gets.",
                    f"Move its grants to customer and drop default from {slug}.",
                ),
                code="C443",
            )
        roles[slug] = copy.deepcopy(role)
        merged.changed.append(("roles", slug))
    out["roles"] = roles


def _contract_grants(out: dict[str, Any], merged: Merged) -> None:
    """The explicit grants admin needs on every contract the project has on."""
    features = out.get("features") or {}
    roles = out.get("roles") or {}
    admin = roles.get("admin")
    if not isinstance(admin, dict):
        return
    grants = dict(admin.get("grants") or {})
    added = []
    for contract, extra in ADMIN_CONTRACT_GRANTS.items():
        if not features.get(contract):
            continue
        for pattern, scope in extra.items():
            if pattern not in grants:
                grants[pattern] = scope
                added.append(pattern)
    if added:
        roles["admin"] = {**admin, "grants": grants}
        out["roles"] = roles
        merged.changed.append(("roles", "admin"))
        merged.notes.append(f"roles.admin: added {', '.join(added)} (explicit actions).")


def _routes(apps: Mapping[str, Any]) -> dict[str, str]:
    return {
        part_route(str(label), app): str(label)
        for label, app in apps.items()
        if isinstance(app, Mapping) and app.get("route")
    }


def _money(fields: Mapping[str, Any]) -> dict[str, Any]:
    """A part's fields with ``money:XYZ`` written as ``money`` (the project's currency)."""
    out: dict[str, Any] = {}
    for name, value in fields.items():
        if isinstance(value, str):
            out[name] = _MONEY.sub("money", value)
        elif isinstance(value, Mapping) and isinstance(value.get("type"), str):
            out[name] = {**value, "type": _MONEY.sub("money", value["type"])}
        else:
            out[name] = value
    return out


def _merge_apps(
    out: dict[str, Any], part: _Part, fragment: Mapping[str, Any], merged: Merged
) -> None:
    apps: dict[str, Any] = dict(out.get("apps") or {})
    taken = _routes(apps)
    for label, app in (fragment.get("apps") or {}).items():
        if label in apps:
            raise CliError(
                _fixed(
                    f"apps.{label}: the project has an app {label} already, and the recipe "
                    f"{part.name} is the app {label}.",
                    f"Rename the project's app (apps.<new label> with was: on each entity), or "
                    f"remove the part that brought it, then add {part.name} again.",
                ),
                code="C442",
            )
        app = copy.deepcopy(dict(app or {}))
        route = part_route(label, app)
        if route in FAMILY_ROUTES:
            raise CliError(
                _fixed(
                    f"apps.{label}.route: the recipe {part.name} mounts its pages at {route}, which "
                    "is a family page's route.",
                    f"Give the part its own base, e.g. route: /{label}.",
                ),
                code="C444",
            )
        if route in taken:
            raise CliError(
                _fixed(
                    f"apps.{label}.route: the recipe {part.name} mounts its pages at {route}, where "
                    f"the app {taken[route]} has its pages.",
                    f"Write another route for {label} in karni.yaml (apps.{label}.route), then add "
                    "the recipe again.",
                ),
                code="C444",
            )
        app["route"] = route
        entities = app.get("entities") or {}
        app["entities"] = {
            name: {**dict(entity or {}), "fields": _money((entity or {}).get("fields") or {})}
            if (entity or {}).get("fields")
            else entity
            for name, entity in entities.items()
        }
        apps[label] = app
        taken[route] = label
        merged.changed.append(("apps", label))
    out["apps"] = apps


def _page_name(entry: Any) -> str | None:
    if isinstance(entry, Mapping) and len(entry) == 1:
        return str(next(iter(entry)))
    return None


def _merge_pages(
    out: dict[str, Any], part: _Part, fragment: Mapping[str, Any], merged: Merged
) -> None:
    pages = list(out.get("pages") or [])
    names = {_page_name(entry) for entry in pages}
    counts: dict[str, int] = {}
    for app in (out.get("apps") or {}).values():
        for name in (app or {}).get("entities") or {}:
            counts[str(name)] = counts.get(str(name), 0) + 1
    own = {
        str(name): str(label)
        for label, app in (fragment.get("apps") or {}).items()
        for name in ((app or {}).get("entities") or {})
    }
    for entry in fragment.get("pages") or []:
        name = _page_name(entry)
        if name is None:
            continue
        if name in FAMILY_PAGES:
            if name == "home" and "home" not in names:
                pages.insert(0, copy.deepcopy(entry))
                names.add("home")
                continue
            raise CliError(
                _fixed(
                    f"pages.{name}: the recipe {part.name} lists the family page {name} "
                    f"({FAMILY_PAGES[name]})"
                    + (", and the project has a home page already." if name == "home" else "."),
                    f"Drop {name} from the recipe's pages: family pages come from Karni (the build "
                    "writes home), and a part's own pages live under its route.",
                ),
                code="C444",
            )
        written = name
        if name in own and counts.get(name, 0) > 1:
            written = f"{own[name]}.{name}"
        if written in names:
            raise CliError(
                _fixed(
                    f"pages.{written}: listed by the project and by the recipe {part.name}.",
                    f"Drop it from one of them, or write {own.get(name, 'app')}.{name}.",
                ),
                code="C444",
            )
        pages.append({written: copy.deepcopy(entry[name])})
        names.add(written)
    if "home" not in names:
        pages.insert(0, {"home": "dashboard"})
    if pages != list(out.get("pages") or []):
        out["pages"] = pages
        merged.changed.append(("pages",))


def _qualified(out: Mapping[str, Any]) -> dict[str, str]:
    """Entity names more than one app defines, to the label each page entry must use."""
    seen: dict[str, list[str]] = {}
    for label, app in (out.get("apps") or {}).items():
        for name in (app or {}).get("entities") or {}:
            seen.setdefault(str(name), []).append(str(label))
    return {name: labels[0] for name, labels in seen.items() if len(labels) > 1}


def _requalify(out: dict[str, Any], merged: Merged) -> None:
    """Page and seed keys of a name two apps define, written ``app.Name``."""
    twice = _qualified(out)
    if not twice:
        return
    owner = {
        str(name): str(label)
        for label, app in (out.get("apps") or {}).items()
        for name in ((app or {}).get("entities") or {})
    }
    pages = []
    changed = False
    for entry in out.get("pages") or []:
        name = _page_name(entry)
        if name in twice:
            # the first app that defined it keeps the entry (before the merge it was its own)
            label = next(
                (
                    str(lbl)
                    for lbl, app in (out.get("apps") or {}).items()
                    if name in ((app or {}).get("entities") or {})
                ),
                owner[name],
            )
            pages.append({f"{label}.{name}": entry[name]})
            changed = True
        else:
            pages.append(entry)
    if changed:
        out["pages"] = pages
        merged.changed.append(("pages",))
    first = {
        name: next(
            str(label)
            for label, app in (out.get("apps") or {}).items()
            if name in ((app or {}).get("entities") or {})
        )
        for name in twice
    }
    seed = out.get("seed")
    if isinstance(seed, dict) and any(name in seed for name in twice):
        out["seed"] = {(f"{first[k]}.{k}" if k in twice else k): n for k, n in seed.items()}
        merged.changed.append(("seed",))
    navigation = out.get("navigation")
    if isinstance(navigation, list):

        def qualify(entry: Any) -> Any:
            if isinstance(entry, str) and entry in twice:
                return f"{first[entry]}.{entry}"
            if isinstance(entry, Mapping) and len(entry) == 1:
                key, value = next(iter(entry.items()))
                if isinstance(value, list):
                    return {key: [qualify(item) for item in value]}
                if key in twice:
                    return {f"{first[key]}.{key}": value}
            return entry

        qualified = [qualify(entry) for entry in navigation]
        if qualified != navigation:
            out["navigation"] = qualified
            merged.changed.append(("navigation",))


def _merge_navigation(
    out: dict[str, Any],
    part: _Part,
    fragment: Mapping[str, Any],
    bases: Mapping[str, Mapping[str, Any]],
    titles: Mapping[str, str],
    merged: Merged,
) -> None:
    theirs = fragment.get("navigation")
    if not isinstance(theirs, list) or not theirs:
        return
    mine = out.get("navigation")
    if mine is True:
        return  # every page, in order: the part's pages are in pages already
    entries = list(mine) if isinstance(mine, list) else []
    # a part installed alone shows its entries flat: group them now that a second one joins
    for other, base in bases.items():
        flat = base.get("navigation")
        if not isinstance(flat, list) or not flat:
            continue
        found = [entry for entry in entries if entry in flat]
        if found and len(found) == len([e for e in flat if _page_name(e) != "home"]):
            group = {titles.get(other, other): [e for e in flat if e in found]}
            first = entries.index(found[0])
            entries = [e for e in entries if e not in found]
            entries.insert(first, group)
    alone = not entries or entries == ["home"]
    own = [entry for entry in theirs if entry != "home" and _page_name(entry) != "home"]
    if "home" not in entries and "home" in theirs:
        entries.insert(0, "home")
    if alone and not bases:
        entries += copy.deepcopy(own)
    else:
        entries.append({part.title: copy.deepcopy(own)})
    out["navigation"] = entries
    merged.changed.append(("navigation",))


def _merge_seed(out: dict[str, Any], fragment: Mapping[str, Any], merged: Merged) -> None:
    theirs = fragment.get("seed") or {}
    if not theirs:
        return
    seed: dict[str, Any] = dict(out.get("seed") or {})
    twice = _qualified(out)
    own = {
        str(name): str(label)
        for label, app in (fragment.get("apps") or {}).items()
        for name in ((app or {}).get("entities") or {})
    }
    for name, count in theirs.items():
        key = f"{own[name]}.{name}" if name in twice and name in own else name
        seed[key] = int(seed.get(key, 0) or 0) + int(count or 0)
    out["seed"] = seed
    merged.changed.append(("seed",))


def _install_requires(out: dict[str, Any], part: _Part, merged: Merged) -> None:
    """Switch on each contract and list each module the part requires."""
    features: dict[str, Any] = dict(out.get("features") or {})
    modules: dict[str, Any] = dict(out.get("modules") or {})
    names = [parse_requirement(text).name for text in part.requires]
    for name in contracts_with_needs(name for name in names if name in CONTRACTS):
        if not features.get(name):
            features[name] = True
            merged.notes.append(f"features.{name}: switched on ({part.name} requires it).")
    for name in names:
        if name in CONTRACTS:
            continue
        if name not in modules:
            modules[name] = {}
            merged.changed.append(("modules", name))
            merged.notes.append(f"modules.{name}: added ({part.name} requires it).")
    if features != (out.get("features") or {}):
        out["features"] = features
        merged.changed.append(("features",))
    if modules:
        out["modules"] = modules


def _follow_currency(out: dict[str, Any], merged: Merged) -> None:
    currency = _currency((out.get("app") or {}).get("currency"))
    if currency is None:
        return
    for module, option in _CURRENCY_OPTIONS.items():
        options = (out.get("modules") or {}).get(module)
        if options is None:
            continue
        options = dict(options or {})
        if options.get(option) != currency.lower():
            options[option] = currency.lower()
            out["modules"][module] = options
            merged.changed.append(("modules", module))


def merge(
    project: Mapping[str, Any],
    recipe: Any,
    fragment: Mapping[str, Any],
    *,
    bases: Mapping[str, Mapping[str, Any]] | None = None,
    parts: Mapping[str, Any] | None = None,
    modules: Mapping[str, Any] | None = None,
) -> Merged:
    """Experimental. ``project``'s spec data with the part ``recipe`` merged in, by the rules above.

    ``fragment`` is the recipe's karni.yaml as data. ``bases`` maps each
    installed part to the fragment it was added with (``.karni/recipes/<name>/
    karni.yaml``), so a value one part asked for is told apart from one the
    project wrote. ``parts`` maps installed recipe names to their recipes (for
    their ``conflicts`` and titles), and ``modules`` the modules this karni-cli
    knows (default: the spec catalog's).

    :raises CliError: ``C214``, ``C440`` and ``C442`` to ``C447``. Nothing is changed.
    """
    if modules is None:
        from karni_cli.spec.catalog import MODULES

        modules = MODULES
    bases = dict(bases or {})
    known = {name: _part(found) for name, found in (parts or {}).items()}
    part = _part(recipe)
    out: dict[str, Any] = copy.deepcopy(dict(project))
    merged = Merged(out)
    present = installed(out)
    if part.name in present:
        raise CliError(
            _fixed(
                f"The recipe {part.name} is in this project already (app.recipes).",
                f"karni recipes upgrade {part.name} brings its newer files, or karni recipes remove "
                f"{part.name} takes it out.",
            ),
            code="C442",
        )
    if fragment.get("version") != out.get("version"):
        raise CliError(
            _fixed(
                f"The recipe {part.name} is karni.yaml version {fragment.get('version')!r} and the "
                f"project's is {out.get('version')!r}.",
                "Upgrade karni-cli, so both are read by the same version.",
            ),
            code="C214",
        )
    app = dict(out.get("app") or {})
    if app.get("kind") == "site" and fragment.get("apps"):
        raise CliError(
            _fixed(
                f"The project is kind site, which has no React app, and the recipe {part.name} is an "
                "app.",
                "Make the project a site+app first (karni add site in an app, or a new project with "
                "--kind site+app).",
            ),
            code="C440",
        )
    _check_requires(part, out, modules)
    _check_conflicts(part, out, known, _labels(fragment))
    theirs = _currency((fragment.get("app") or {}).get("currency"))
    if not app.get("currency"):
        written = _currency(_first_money(fragment)) or theirs
        if written:
            app["currency"] = written
            merged.changed.append(("app", "currency"))
    app.pop("recipe", None)
    app["recipes"] = [*present, part.name]
    out["app"] = app
    merged.changed.append(("app", "recipes"))
    _merge_modules(out, part, fragment, bases, merged)
    _merge_features(out, fragment, merged)
    _install_requires(out, part, merged)
    _merge_roles(out, part, fragment, merged, alone=not present)
    _contract_grants(out, merged)
    _merge_apps(out, part, fragment, merged)
    _merge_pages(out, part, fragment, merged)
    titles = {name: found.title for name, found in known.items()}
    _merge_navigation(out, part, fragment, bases, titles, merged)
    _requalify(out, merged)
    _merge_seed(out, fragment, merged)
    _follow_currency(out, merged)
    if not out.get("modules"):
        out.pop("modules", None)
    merged.changed = list(dict.fromkeys(merged.changed))
    return merged


def _first_money(fragment: Mapping[str, Any]) -> str | None:
    """The currency of the fragment's first ``money:XYZ`` field (what an old recipe wrote)."""
    for app in (fragment.get("apps") or {}).values():
        for entity in ((app or {}).get("entities") or {}).values():
            for value in ((entity or {}).get("fields") or {}).values():
                token = value.get("type") if isinstance(value, Mapping) else value
                found = _MONEY.match(token) if isinstance(token, str) else None
                if found:
                    return found.group(1)
    return None


def unmerge(project: Mapping[str, Any], name: str, base: Mapping[str, Any]) -> Merged:
    """Experimental. ``project``'s spec data with the part ``name`` taken out.

    Its apps, its roles (a family role loses the grants only it added), its
    pages, navigation group and seed counts go. Modules, features and the
    currency stay: another part, or the project, may use them.

    :raises CliError: ``C448`` when the part is not in the project.
    """
    out: dict[str, Any] = copy.deepcopy(dict(project))
    merged = Merged(out)
    present = installed(out)
    if name not in present:
        raise CliError(
            _fixed(
                f"The recipe {name} is not in this project (app.recipes lists "
                f"{', '.join(present) or 'none'}).",
                "Name a recipe app.recipes lists.",
            ),
            code="C448",
        )
    app = dict(out.get("app") or {})
    app.pop("recipe", None)
    app["recipes"] = [other for other in present if other != name]
    out["app"] = app
    merged.changed.append(("app", "recipes"))
    labels = _labels(base)
    apps = dict(out.get("apps") or {})
    entity_names: set[str] = set()
    for label in labels:
        for entity in (apps.get(label) or {}).get("entities") or {}:
            entity_names |= {str(entity), f"{label}.{entity}"}
        apps.pop(label, None)
    out["apps"] = apps
    roles = dict(out.get("roles") or {})
    for slug, role in (base.get("roles") or {}).items():
        if slug in FAMILY_ROLES and slug in roles:
            grants = dict((roles[slug] or {}).get("grants") or {})
            for pattern in (role or {}).get("grants") or {}:
                if pattern.split(".", 1)[0] in labels:
                    grants.pop(pattern, None)
            roles[slug] = {**dict(roles[slug] or {}), "grants": grants}
        elif slug not in FAMILY_ROLES:
            roles.pop(slug, None)
    out["roles"] = roles
    still = {
        str(entity)
        for app_data in apps.values()
        for entity in ((app_data or {}).get("entities") or {})
    }

    def gone(key: Any) -> bool:
        if not isinstance(key, str) or key not in entity_names:
            return False
        return "." in key or key not in still

    out["pages"] = [entry for entry in out.get("pages") or [] if not gone(_page_name(entry))]
    navigation = out.get("navigation")
    if isinstance(navigation, list):
        kept: list[Any] = []
        for entry in navigation:
            if gone(entry) or gone(_page_name(entry)):
                continue
            values = next(iter(entry.values())) if isinstance(entry, Mapping) else None
            if isinstance(values, list):
                left = [v for v in values if not (gone(v) or gone(_page_name(v)))]
                if not left:
                    continue
                entry = {next(iter(entry)): left}
            kept.append(entry)
        out["navigation"] = kept
    out["seed"] = {key: n for key, n in (out.get("seed") or {}).items() if not gone(key)}
    for key in ("roles", "apps", "pages", "navigation", "seed"):
        merged.changed.append((key,))
    return merged
