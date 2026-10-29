"""Experimental. What a spec may name besides its own entities: modules, providers, models.

:data:`MODULES` lists the first-party modules ``karni add`` installs. A
module's options in a spec are its settings: the option ``provider`` of
``payments`` is ``KARNI_PAYMENTS_PROVIDER``, and the option names are the
module's own ``KARNI_<MODULE>_*`` settings, lowercased, without the prefix.
Credentials (``STRIPE_SECRET_KEY`` and the like) are never options: they
stay in the environment. ``tests/test_spec.py`` checks this table against
each installed module's ``conf.DEFAULTS`` and models, so it cannot drift.
The module catalog (app-builder item A4) will replace it with a manifest per
module.

Override / escape hatch: a module that is not listed is added with
``karni add <name>`` by hand and stays out of the spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "MODULES",
    "OTHER_MODELS",
    "SOCIAL_PROVIDERS",
    "USER_MODEL",
    "KnownModule",
    "module_setting",
]

#: Experimental. ``karni.accounts.social_token.BUILTIN_PROVIDERS``: the names ``social_login`` takes.
SOCIAL_PROVIDERS: Final = ("google", "microsoft", "apple")
#: Experimental. The user model every project has (``AUTH_USER_MODEL``).
USER_MODEL: Final = "karni_accounts.User"
#: Experimental. Models a relation may target that are neither entities nor a module's.
OTHER_MODELS: Final = frozenset({"auth.Group", "contenttypes.ContentType"})


@dataclass(frozen=True)
class KnownModule:
    """Experimental. One module a spec may list: its app, its models, its options and their types.

    ``options`` maps an option to the JSON types its value may have
    (``string``, ``integer``, ``boolean``, ``array``, ``object``, ``null``).
    """

    name: str
    models: tuple[str, ...]
    options: dict[str, tuple[str, ...]]

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


_S, _I, _B, _A, _O = ("string",), ("integer",), ("boolean",), ("array",), ("object",)

#: Experimental. The first-party modules, by the name ``karni add`` takes.
MODULES: Final[dict[str, KnownModule]] = {
    module.name: module
    for module in (
        KnownModule(
            "approvals",
            ("PendingChange", "Decision"),
            {
                "required": _I,
                "approver_roles": _A,
                "timeout_hours": _I,
                "on_timeout": _S,
                "escalation_roles": _A,
                "notify": _S,
                "from_email": _S,
            },
        ),
        KnownModule(
            "impersonation",
            ("ImpersonationSession",),
            {
                "max_minutes": _I,
                "blocked": _A,
                "require_reason": _B,
                "notify_target": _B,
                "from_email": _S,
                "banner": _B,
                "landing": _S,
            },
        ),
        KnownModule(
            "payments",
            ("Payment", "Refund", "WebhookEvent"),
            {
                "provider": _S,
                "currency": _S,
                "checkout_validator": _S,
                "event_handler": _S,
                "allowed_redirects": _A,
            },
        ),
        KnownModule(
            "site",
            (
                "SiteSettings",
                "OpeningHours",
                "SocialLink",
                "Block",
                "Menu",
                "MenuItem",
                "Redirect",
                "PageSeo",
            ),
            {
                "is_active": _S,
                "server_error_templates": _A,
                "not_found_templates": _A,
                "settings_model": _S,
                "highlight": _O,
                "inline_tags": _O,
                "link_schemes": _A,
                "sanitizer": _S,
                "image_types": _A,
                "cache": _S,
                "cache_timeout": _I,
                "seed_on_render": _B,
                "menu_rows": _S,
                "menu_rows_limit": _I,
                "redirects_before_views": _B,
                "editor_role": ("string", "null"),
                "forms": _O,
                "form_class": _S,
                "form_template": _S,
                "form_classes": _O,
                "form_presets": _O,
                "form_messages": _O,
                "form_required_mark": _S,
                "form_script": _B,
                "form_sent_param": _S,
                "form_page_template": _S,
                "notify_from": _S,
            },
        ),
    )
}
