"""``karni.E971`` / ``karni.W971``: a language Django cannot describe (experimental).

``LANGUAGES`` may name any code that has a ``locale/<code>/`` folder, but
Django describes a language (its name, its own name, its direction) only for
the codes of ``django.conf.locale.LANG_INFO``. A page that lists the
languages (``{% get_language_info_list %}``, ``{% get_language_info %}``)
raises ``KeyError: Unknown language code xx.`` for any other code. The admin
does it on every page: django-unfold's user menu runs
``{% get_language_info_list for LANGUAGES %}`` whether or not
``UNFOLD["SHOW_LANGUAGES"]`` is on, so one such code is a 500 on every admin
page, found by the first person to open one.

The check asks Django itself (``get_language_info``, with its fallback of
``fil-ph`` to ``fil``) for each ``LANGUAGES`` code and names each code it cannot
describe, with the entry that registers it. It is an error when
``django.contrib.admin`` is installed (the pages above break) and a warning
otherwise (only a template of the project can break).

Override / escape hatch: register the language (the message shows the entry),
or add the code to ``SILENCED_SYSTEM_CHECKS``.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.utils.translation import get_language_info

from karni.exceptions import check_error, check_warning

__all__ = ["check_languages", "undescribed_languages"]


def undescribed_languages() -> list[str]:
    """The ``LANGUAGES`` codes ``django.utils.translation.get_language_info`` cannot describe."""
    missing = []
    for code, _name in getattr(settings, "LANGUAGES", ()):
        try:
            get_language_info(code)
        except KeyError:
            missing.append(str(code))
    return missing


def _entry(code: str, name: str) -> str:
    return (
        "LANG_INFO.update({"
        f'"{code}": {{"bidi": False, "code": "{code}", "name": "{name}", "name_local": "{name}"}}'
        "}) (in settings.py, after `from django.conf.locale import LANG_INFO`)"
    )


@checks.register()
def check_languages(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E971 / W971: each LANGUAGES code Django has no LANG_INFO entry for."""
    names = dict(getattr(settings, "LANGUAGES", ()))
    admin = apps.is_installed("django.contrib.admin")
    emit = check_error if admin else check_warning
    code_id = "E971" if admin else "W971"
    messages: list[checks.CheckMessage] = []
    for code in undescribed_languages():
        name = str(names.get(code, code))
        where = (
            "the admin lists the languages on every page, so every admin page answers 500"
            if admin
            else "a template that lists the languages (get_language_info) raises KeyError"
        )
        messages.append(
            emit(
                code_id,
                f"LANGUAGES has {code!r} ({name}), which django.conf.locale.LANG_INFO does not "
                f"describe: {where} with 'Unknown language code {code}.'.",
                hint=(
                    "Register it, with its name, its name in that language, its direction "
                    f"(bidi) and its code: {_entry(code, name)}. Or take {code!r} out of "
                    "LANGUAGES."
                ),
            )
        )
    return messages
