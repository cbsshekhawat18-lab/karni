"""Experimental. The module catalog: a manifest per module and per built-in feature.

A **module manifest** is ``karni.module.toml`` inside the module's Python
package (package data), found through the ``karni.modules`` entry point
group, whose value is the package::

    [project.entry-points."karni.modules"]
    payments = "karni_payments"

A **feature manifest** describes an option Karni itself ships (two-factor
sign-in, sign-in with a code, terms acceptance): ``features/<name>.toml``
next to this file. Both say what the thing is for, what it provides, the
questions worth asking before turning it on (each mapped to a setting), what
it requires or conflicts with, the services it needs, and, for a module, the
wiring ``karni add`` performs and ``karni remove`` reverses.

:func:`parse` checks a manifest against :data:`KEYS` and returns a
:class:`Manifest`, raising :class:`ManifestError` with every problem.
:func:`features` reads Karni's feature manifests, :func:`installed` the
manifests of the modules installed in this environment, and
:func:`check_catalog` the references between manifests. docs/modules.md
lists every key.

Import-light by contract: stdlib only, no Django and no settings. karni-cli
loads this module by path (the copy it bundles, ``karni_cli/_catalog``) when
karni is not importable, and ``python -m karni.catalog`` prints the installed
modules' manifests for a CLI that runs outside the project's environment.

Override / escape hatch: a module without a manifest is still added with
``karni add <name>`` by convention (``karni_<name>``, ``karni-<name>``).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ENTRY_POINT_GROUP",
    "KEYS",
    "MANIFEST_FILE",
    "Ask",
    "Entry",
    "Manifest",
    "ManifestError",
    "Provides",
    "Wiring",
    "check_catalog",
    "features",
    "installed",
    "parse",
    "parse_text",
]

#: Experimental. The file a module ships inside its package.
MANIFEST_FILE: Final = "karni.module.toml"
#: Experimental. The entry point group that names each module's package.
ENTRY_POINT_GROUP: Final = "karni.modules"
#: Where Karni's own feature manifests live.
FEATURES_DIR: Final = Path(__file__).resolve().parent / "features"

KINDS: Final = ("module", "feature")
STATUSES: Final = ("stable", "experimental")
#: The JSON types a setting may take (``karni.yaml`` checks a module option against them).
TYPES: Final = ("string", "integer", "boolean", "array", "object", "null")
#: The longest ``purpose``: one line in ``karni context`` per entry.
PURPOSE_MAX: Final = 80

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SETTING = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_OBJECT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_EXTRA = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Experimental. Every key a manifest takes: ``(where, key) -> (kinds, required, what it holds)``.
#: ``where`` is ``""`` for the top level, else the table (``provides``, ``wiring``,
#: ``asks``, ``wiring.middleware``). docs/modules.md documents each one.
KEYS: Final[dict[tuple[str, str], tuple[tuple[str, ...], bool, str]]] = {
    ("", "name"): (KINDS, True, "the name karni add takes, or the feature's key in karni.yaml"),
    ("", "kind"): (KINDS, True, "module or feature"),
    ("", "title"): (KINDS, True, "a short human name"),
    ("", "purpose"): (KINDS, True, f"one line, at most {PURPOSE_MAX} characters"),
    ("", "status"): (KINDS, True, "stable or experimental"),
    ("", "use_when"): (KINDS, True, "plain phrases of what someone asks for"),
    ("", "requires"): (KINDS, False, "modules or features that must be there too"),
    ("", "conflicts"): (KINDS, False, "modules or features that cannot be there too"),
    ("", "services"): (KINDS, False, "what it needs to run: a worker, Redis, a provider account"),
    ("", "docs"): (KINDS, False, "the page that documents it"),
    ("", "distribution"): (("module",), False, "the PyPI name (default karni-<name>)"),
    ("", "switch"): (("feature",), True, "the setting that turns the feature on"),
    ("", "extra"): (("feature",), False, "the karni extra it needs, e.g. karni[2fa]"),
    ("", "in_spec"): (("feature",), False, "false when karni.yaml has no key for it yet"),
    ("", "provides"): (KINDS, False, "what it adds"),
    ("", "asks"): (KINDS, False, "the questions to ask before adding it"),
    ("", "wiring"): (("module",), True, "what karni add writes and karni remove takes out"),
    ("provides", "models"): (KINDS, False, "model names"),
    ("provides", "endpoints"): (KINDS, False, "URL paths"),
    ("provides", "pages"): (KINDS, False, "admin pages, templates or screens"),
    ("provides", "settings"): (KINDS, False, "setting -> JSON type (or a list of types)"),
    ("provides", "ui"): (KINDS, False, "the npm package of its React components"),
    ("asks", "question"): (KINDS, True, "the question, in plain words"),
    ("asks", "setting"): (KINDS, True, "the setting the answer goes to (SETTING or SETTING.key)"),
    ("asks", "options"): (KINDS, False, "the answers to choose from (none: a free value)"),
    ("asks", "default"): (KINDS, False, "the answer when nobody says otherwise"),
    ("asks", "multiple"): (KINDS, False, "true when the answer is a list of options"),
    ("wiring", "apps"): (("module",), True, "entries of the # karni:apps block"),
    ("wiring", "settings"): (("module",), False, "its settings fragment, module:DEFAULTS"),
    ("wiring", "middleware"): (("module",), False, "entries of the # karni:middleware block"),
    ("wiring", "context_processors"): (("module",), False, "template context processors"),
    ("wiring", "urls"): (("module",), False, "the include line for config/urls.py"),
    ("wiring", "kind"): (("module",), False, '"site": the project kind gains a site'),
    ("wiring", "extras"): (("module",), False, "extra -> what it is for"),
    ("wiring.middleware", "path"): (("module",), True, "the dotted path"),
    ("wiring.middleware", "why"): (("module",), False, "what it does, in a few words"),
    ("wiring.middleware", "manual"): (("module",), False, "true: karni add prints it instead"),
}


class ManifestError(ValueError):
    """Experimental. A manifest that does not follow :data:`KEYS`: every problem, one per line."""

    def __init__(self, source: str, problems: list[str]) -> None:
        super().__init__(f"{source}: " + "; ".join(problems))
        self.source = source
        self.problems = problems


@dataclass(frozen=True)
class Ask:
    """Experimental. One question to ask before adding a module or turning a feature on."""

    question: str
    setting: str
    options: tuple[Any, ...] = ()
    default: Any = None
    has_default: bool = False
    multiple: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"question": self.question, "setting": self.setting}
        data["options"] = list(self.options)
        if self.has_default:
            data["default"] = self.default
        data["multiple"] = self.multiple
        return data


@dataclass(frozen=True)
class Entry:
    """Experimental. A middleware or context processor the module wires."""

    path: str
    why: str = ""
    manual: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "why": self.why, "manual": self.manual}


@dataclass(frozen=True)
class Provides:
    """Experimental. What a module or feature adds."""

    models: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()
    settings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ui: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "models": list(self.models),
            "endpoints": list(self.endpoints),
            "pages": list(self.pages),
            "settings": {name: list(types) for name, types in self.settings.items()},
            "ui": self.ui,
        }


@dataclass(frozen=True)
class Wiring:
    """Experimental. What ``karni add`` writes for a module, and ``karni remove`` takes out."""

    apps: tuple[str, ...] = ()
    settings: str = ""
    middleware: tuple[Entry, ...] = ()
    context_processors: tuple[Entry, ...] = ()
    urls: str = ""
    kind: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "apps": list(self.apps),
            "settings": self.settings,
            "middleware": [entry.to_dict() for entry in self.middleware],
            "context_processors": [entry.to_dict() for entry in self.context_processors],
            "urls": self.urls,
            "kind": self.kind,
            "extras": dict(self.extras),
        }


@dataclass(frozen=True)
class Manifest:
    """Experimental. One module or built-in feature, as its manifest describes it."""

    name: str
    kind: str
    title: str
    purpose: str
    status: str
    use_when: tuple[str, ...]
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    docs: str = ""
    distribution: str = ""
    switch: str = ""
    extra: str = ""
    in_spec: bool = True
    provides: Provides = field(default_factory=Provides)
    asks: tuple[Ask, ...] = ()
    wiring: Wiring = field(default_factory=Wiring)
    #: Where it was read from (a path, or ``entry point <name>``).
    source: str = ""

    @property
    def app(self) -> str:
        """The module's app (the first entry of ``wiring.apps``), ``""`` for a feature."""
        return self.wiring.apps[0] if self.wiring.apps else ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "purpose": self.purpose,
            "status": self.status,
            "use_when": list(self.use_when),
            "requires": list(self.requires),
            "conflicts": list(self.conflicts),
            "services": list(self.services),
            "docs": self.docs,
            "provides": self.provides.to_dict(),
            "asks": [ask.to_dict() for ask in self.asks],
        }
        if self.kind == "module":
            data["distribution"] = self.distribution
            data["wiring"] = self.wiring.to_dict()
        else:
            data |= {"switch": self.switch, "extra": self.extra, "in_spec": self.in_spec}
        return data


# parsing ----------------------------------------------------------------------


class _Reader:
    """Reads one table of a manifest, collecting every problem instead of stopping."""

    def __init__(self, kind: str, problems: list[str]) -> None:
        self.kind = kind
        self.problems = problems

    def keys(self, data: dict[str, Any], where: str, label: str) -> None:
        for key in data:
            entry = KEYS.get((where, key))
            if entry is None:
                known = sorted(k for (w, k), spec in KEYS.items() if w == where)
                self.problems.append(f"{label}: unknown key {key!r} (keys: {', '.join(known)})")
            elif self.kind in KINDS and self.kind not in entry[0]:
                self.problems.append(f"{label}: {key!r} is for a {entry[0][0]}, not a {self.kind}")
        for (w, key), (kinds, required, _what) in KEYS.items():
            if w == where and required and self.kind in kinds and key not in data:
                self.problems.append(f"{label}: needs the key {key!r}")

    def text(self, data: dict[str, Any], key: str, label: str, pattern: re.Pattern[str]) -> str:
        value = data.get(key, "")
        if not isinstance(value, str):
            self.problems.append(f"{label}.{key} must be text, got {type(value).__name__}")
            return ""
        if value and not pattern.match(value):
            self.problems.append(f"{label}.{key} {value!r} is not valid")
        return value

    def texts(
        self, data: dict[str, Any], key: str, label: str, pattern: re.Pattern[str] | None = None
    ) -> tuple[str, ...]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            self.problems.append(f"{label}.{key} must be a list of non-empty texts")
            return ()
        for item in value:
            if pattern is not None and not pattern.match(item):
                self.problems.append(f"{label}.{key} has {item!r}, which is not valid")
        if len(set(value)) != len(value):
            self.problems.append(f"{label}.{key} names something twice")
        return tuple(value)

    def table(self, data: dict[str, Any], key: str, label: str) -> dict[str, Any]:
        value = data.get(key, {})
        if not isinstance(value, dict):
            self.problems.append(f"{label}.{key} must be a table")
            return {}
        return value


_ANY: Final = re.compile(r"(?s).+")
_LINE: Final = re.compile(r"^[^\n]+$")


def _types(value: Any) -> tuple[str, ...] | None:
    found = (value,) if isinstance(value, str) else value
    if not isinstance(found, list | tuple) or not found:
        return None
    if not all(isinstance(t, str) and t in TYPES for t in found):
        return None
    return tuple(found)


def _provides(reader: _Reader, data: dict[str, Any]) -> Provides:
    raw = reader.table(data, "provides", "provides")
    reader.keys(raw, "provides", "provides")
    settings: dict[str, tuple[str, ...]] = {}
    for name, value in reader.table(raw, "settings", "provides").items():
        types = _types(value)
        if not _SETTING.match(name):
            reader.problems.append(f"provides.settings: {name!r} is not a setting name")
        if types is None:
            reader.problems.append(
                f"provides.settings.{name} must be one of {', '.join(TYPES)}, or a list of them"
            )
        else:
            settings[name] = types
    return Provides(
        models=reader.texts(raw, "models", "provides", re.compile(r"^[A-Z][A-Za-z0-9]*$")),
        endpoints=reader.texts(raw, "endpoints", "provides"),
        pages=reader.texts(raw, "pages", "provides"),
        settings=settings,
        ui=reader.text(raw, "ui", "provides", _ANY),
    )


def _asks(reader: _Reader, data: dict[str, Any], known: set[str]) -> tuple[Ask, ...]:
    raw = data.get("asks", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        reader.problems.append("asks must be an array of tables ([[asks]])")
        return ()
    asks: list[Ask] = []
    for index, item in enumerate(raw):
        label = f"asks[{index}]"
        reader.keys(item, "asks", label)
        question = reader.text(item, "question", label, _LINE)
        setting = reader.text(item, "setting", label, re.compile(r"^[A-Z][A-Z0-9_]*(\.[a-z_]+)?$"))
        if setting and setting.split(".", 1)[0] not in known:
            reader.problems.append(
                f"{label}.setting {setting!r} is not one of provides.settings"
                + (" or the switch" if reader.kind == "feature" else "")
            )
        options = item.get("options", [])
        if not isinstance(options, list) or not all(
            isinstance(o, str | int | bool) for o in options
        ):
            reader.problems.append(f"{label}.options must be a list of texts, numbers or booleans")
            options = []
        multiple = item.get("multiple", False)
        if not isinstance(multiple, bool):
            reader.problems.append(f"{label}.multiple must be true or false")
            multiple = False
        has_default = "default" in item
        default = item.get("default")
        if has_default and options:
            chosen = default if multiple and isinstance(default, list) else [default]
            if multiple and not isinstance(default, list):
                reader.problems.append(f"{label}.default must be a list (multiple = true)")
            elif any(choice not in options for choice in chosen):
                reader.problems.append(f"{label}.default {default!r} is not one of its options")
        asks.append(Ask(question, setting, tuple(options), default, has_default, multiple))
    return tuple(asks)


def _entries(reader: _Reader, raw: dict[str, Any], key: str) -> tuple[Entry, ...]:
    items = raw.get(key, [])
    if not isinstance(items, list):
        reader.problems.append(f"wiring.{key} must be a list")
        return ()
    entries: list[Entry] = []
    for index, item in enumerate(items):
        label = f"wiring.{key}[{index}]"
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            reader.problems.append(f"{label} must be a dotted path or a table with path")
            continue
        reader.keys(item, "wiring.middleware", label)
        manual = item.get("manual", False)
        if not isinstance(manual, bool):
            reader.problems.append(f"{label}.manual must be true or false")
            manual = False
        entries.append(
            Entry(
                reader.text(item, "path", label, _DOTTED),
                reader.text(item, "why", label, _LINE),
                manual,
            )
        )
    return tuple(entries)


def _wiring(reader: _Reader, data: dict[str, Any]) -> Wiring:
    raw = reader.table(data, "wiring", "wiring")
    reader.keys(raw, "wiring", "wiring")
    apps = reader.texts(raw, "apps", "wiring", _DOTTED)
    if "apps" in raw and not apps:
        reader.problems.append("wiring.apps must name the module's app")
    kind = reader.text(raw, "kind", "wiring", re.compile(r"^site$"))
    extras: dict[str, str] = {}
    for extra, why in reader.table(raw, "extras", "wiring").items():
        if not _EXTRA.match(extra) or not isinstance(why, str) or not why:
            reader.problems.append(f"wiring.extras.{extra} must be a text saying what it is for")
        else:
            extras[extra] = why
    urls = reader.text(raw, "urls", "wiring", re.compile(r"^path\(.*include\(.*\)\)$"))
    return Wiring(
        apps=apps,
        settings=reader.text(raw, "settings", "wiring", _OBJECT),
        middleware=_entries(reader, raw, "middleware"),
        context_processors=_entries(reader, raw, "context_processors"),
        urls=urls,
        kind=kind,
        extras=extras,
    )


def parse(data: dict[str, Any], source: str) -> Manifest:
    """Experimental. The :class:`Manifest` in ``data`` (a parsed TOML table).

    :raises ManifestError: listing every problem, each with the key it is about.
    """
    problems: list[str] = []
    kind = data.get("kind")
    if kind not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
    reader = _Reader(str(kind), problems)
    reader.keys(data, "", "manifest")
    name = reader.text(data, "name", "manifest", _NAME)
    status = reader.text(data, "status", "manifest", re.compile(r"^(stable|experimental)$"))
    purpose = reader.text(data, "purpose", "manifest", _LINE)
    if len(purpose) > PURPOSE_MAX:
        problems.append(f"manifest.purpose is {len(purpose)} characters (at most {PURPOSE_MAX})")
    use_when = reader.texts(data, "use_when", "manifest")
    if "use_when" in data and not use_when:
        problems.append("manifest.use_when must name at least one phrase")
    provides = _provides(reader, data)
    switch = reader.text(data, "switch", "manifest", _SETTING)
    if switch and switch not in provides.settings:
        problems.append(f"manifest.switch {switch!r} is not one of provides.settings")
    in_spec = data.get("in_spec", True)
    if not isinstance(in_spec, bool):
        problems.append("manifest.in_spec must be true or false")
        in_spec = True
    distribution = reader.text(
        data, "distribution", "manifest", re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    )
    if not distribution and kind == "module":
        distribution = f"karni-{name.replace('_', '-')}"
    manifest = Manifest(
        name=name,
        kind=str(kind),
        title=reader.text(data, "title", "manifest", _LINE),
        purpose=purpose,
        status=status,
        use_when=use_when,
        requires=reader.texts(data, "requires", "manifest", _NAME),
        conflicts=reader.texts(data, "conflicts", "manifest", _NAME),
        services=reader.texts(data, "services", "manifest"),
        docs=reader.text(data, "docs", "manifest", _LINE),
        distribution=distribution,
        switch=switch,
        extra=reader.text(data, "extra", "manifest", re.compile(r"^karni\[[a-z0-9-]+\]$")),
        in_spec=in_spec,
        provides=provides,
        asks=_asks(reader, data, set(provides.settings)),
        wiring=_wiring(reader, data) if kind == "module" else Wiring(),
        source=source,
    )
    if name and name in manifest.requires + manifest.conflicts:
        problems.append("manifest names itself in requires or conflicts")
    if problems:
        raise ManifestError(source, problems)
    return manifest


def parse_text(text: str, source: str) -> Manifest:
    """Experimental. :func:`parse` for TOML text, with a TOML error as a :class:`ManifestError`."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(source, [f"not valid TOML: {exc}"]) from None
    return parse(data, source)


# discovery --------------------------------------------------------------------


def features(directory: Path | None = None) -> list[Manifest]:
    """Experimental. Karni's feature manifests, by name."""
    folder = directory or FEATURES_DIR
    found = [
        parse_text(path.read_text(encoding="utf-8"), str(path))
        for path in sorted(folder.glob("*.toml"))
    ]
    for manifest in found:
        if manifest.kind != "feature":
            raise ManifestError(manifest.source, ["a file in features/ must have kind feature"])
    return found


def installed_texts() -> dict[str, tuple[str, str]]:
    """Experimental. ``name -> (source, TOML text)`` for each ``karni.modules`` entry point here."""
    found: dict[str, tuple[str, str]] = {}
    for point in entry_points(group=ENTRY_POINT_GROUP):
        package = point.value.split(":", 1)[0]
        source = f"entry point {point.name} ({package}/{MANIFEST_FILE})"
        try:
            text = resources.files(package).joinpath(MANIFEST_FILE).read_text(encoding="utf-8")
        except (ImportError, OSError) as exc:
            raise ManifestError(source, [f"cannot be read: {exc}"]) from None
        found[point.name] = (source, text)
    return found


def installed() -> list[Manifest]:
    """Experimental. The manifests of the modules installed in this environment.

    :raises ManifestError: for a manifest that cannot be read, is invalid, or whose
        name is not its entry point's.
    """
    manifests: list[Manifest] = []
    for name, (source, text) in sorted(installed_texts().items()):
        manifest = parse_text(text, source)
        if manifest.kind != "module" or manifest.name != name:
            raise ManifestError(
                source, [f"the entry point {name!r} must name a module manifest named {name!r}"]
            )
        manifests.append(manifest)
    return manifests


def check_catalog(manifests: list[Manifest]) -> list[str]:
    """Experimental. Problems between manifests: unknown names, a feature that needs a module.

    Karni's core never depends on an optional module, so a feature's
    ``requires`` names features only.
    """
    by_name: dict[str, Manifest] = {}
    problems: list[str] = []
    for manifest in manifests:
        if manifest.name in by_name:
            problems.append(f"{manifest.source}: the name {manifest.name!r} is taken")
        by_name[manifest.name] = manifest
    for manifest in manifests:
        for key in ("requires", "conflicts"):
            for other in getattr(manifest, key):
                target = by_name.get(other)
                if target is None:
                    problems.append(f"{manifest.source}: {key} names {other!r}, not in the catalog")
                elif key == "requires" and manifest.kind == "feature" and target.kind == "module":
                    problems.append(f"{manifest.source}: a feature cannot require a module")
    return problems
