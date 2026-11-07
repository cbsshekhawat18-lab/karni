"""Experimental. What a spec may name besides its own entities: modules, features, models.

Everything here comes from the module catalog (:mod:`karni_cli.catalog`),
so there is one source. :data:`MODULES` holds each module's models and
options. A module's options in a spec are its settings: the option
``provider`` of ``payments`` is ``KARNI_PAYMENTS_PROVIDER``, and the option
names are the ``KARNI_<MODULE>_*`` settings its manifest lists, lowercased,
without the prefix, with the JSON types the manifest gives them.
Credentials (``STRIPE_SECRET_KEY`` and the like) are never options: they
stay in the environment. :data:`FEATURES` holds the built-in features
``features:`` takes, :data:`SOCIAL_PROVIDERS` the providers the
``social_login`` manifest offers, and :data:`DEFAULT_CACHE_TTL` the
lifetime the ``api_cache`` manifest gives a cached response.

Override / escape hatch: a module of your own joins the spec by shipping a
manifest (docs/modules.md#the-module-catalog). One without is added with
``karni add <name>`` by hand and stays out of the spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from karni_cli.catalog import load

if TYPE_CHECKING:
    from karni.catalog import Ask, Manifest

__all__ = [
    "DEFAULT_CACHE_TTL",
    "FEATURES",
    "MODULES",
    "OTHER_MODELS",
    "SOCIAL_PROVIDERS",
    "USER_MODEL",
    "KnownFeature",
    "KnownModule",
    "known_feature",
    "known_module",
    "module_setting",
]

#: Experimental. The user model every project has (``AUTH_USER_MODEL``).
USER_MODEL: Final = "karni_accounts.User"
#: Experimental. Models a relation may target that are neither entities nor a module's.
OTHER_MODELS: Final = frozenset({"auth.Group", "contenttypes.ContentType"})


@dataclass(frozen=True)
class KnownModule:
    """Experimental. One module a spec may list: its app, its models, its options and their types.

    ``options`` maps an option to the JSON types its value may have
    (``string``, ``integer``, ``boolean``, ``array``, ``object``, ``null``).
    ``asks`` are the manifest's questions, in its order (``karni plan --questions``).
    """

    name: str
    models: tuple[str, ...]
    options: dict[str, tuple[str, ...]]
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    title: str = ""
    asks: tuple[Ask, ...] = ()

    @property
    def app(self) -> str:
        return f"karni_{self.name}"

    @property
    def distribution(self) -> str:
        return f"karni-{self.name}"

    def setting(self, option: str) -> str:
        return module_setting(self.name, option)


def module_setting(module: str, option: str) -> str:
    """Experimental. The setting behind a module option: ``KARNI_PAYMENTS_PROVIDER``."""
    return f"KARNI_{module.upper()}_{option.upper()}"


def known_module(manifest: Manifest) -> KnownModule:
    """Experimental. A module manifest as the spec sees it: its models and options."""
    prefix = f"KARNI_{manifest.name.upper()}_"
    return KnownModule(
        manifest.name,
        manifest.provides.models,
        {
            setting[len(prefix) :].lower(): types
            for setting, types in manifest.provides.settings.items()
            if setting.startswith(prefix)
        },
        manifest.requires,
        manifest.conflicts,
        manifest.title,
        manifest.asks,
    )


@dataclass(frozen=True)
class KnownFeature:
    """Experimental. One key of ``features:``: the setting that switches it, its extra, its asks."""

    name: str
    switch: str
    extra: str
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    title: str = ""
    asks: tuple[Ask, ...] = ()


def known_feature(manifest: Manifest) -> KnownFeature:
    """Experimental. A feature manifest as the spec sees it."""
    return KnownFeature(
        manifest.name,
        manifest.switch,
        manifest.extra,
        manifest.requires,
        manifest.conflicts,
        manifest.title,
        manifest.asks,
    )


_CATALOG = load()

#: Experimental. The modules ``karni add`` installs, by name: the module catalog's.
MODULES: Final[dict[str, KnownModule]] = {m.name: known_module(m) for m in _CATALOG.modules}
#: Experimental. The keys of ``features:``: the catalog's features that karni.yaml takes.
FEATURES: Final[dict[str, KnownFeature]] = {
    m.name: known_feature(m) for m in _CATALOG.features if m.in_spec
}


def _providers() -> tuple[str, ...]:
    social = _CATALOG.get("social_login")
    for ask in social.asks if social is not None else ():
        if ask.setting == "KARNI_SOCIAL_TOKEN_PROVIDERS":
            return tuple(str(option) for option in ask.options)
    return ()


#: Experimental. ``karni.accounts.social_token.BUILTIN_PROVIDERS``: the names ``social_login`` takes.
SOCIAL_PROVIDERS: Final = _providers()


def _cache_ttl() -> int:
    feature = _CATALOG.get("api_cache")
    for ask in feature.asks if feature is not None else ():
        if ask.setting == "KARNI_API_CACHE_TTL" and isinstance(ask.default, int):
            return ask.default
    return 300


#: Experimental. ``KARNI_API_CACHE_TTL``'s default: the lifetime ``api_cache: true`` means.
DEFAULT_CACHE_TTL: Final = _cache_ttl()
