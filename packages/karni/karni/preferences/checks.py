"""System checks of the preferences: the deployment's locks and defaults.

* ``karni.E320``: ``KARNI_PREFERENCES_LOCKED`` or ``KARNI_PREFERENCES_DEFAULTS``
  is not ``{group: {name: value}}``, names a section, field, connection or email
  kind nobody declared, or gives a value the field refuses.

A malformed section (``E321``) or connection (``E322``) is refused when its
module is imported, so the project does not start with it.

Registered when ``karni.preferences`` is installed (its ``ready()``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.apps import apps
from django.core import checks

from karni.exceptions import check_error

__all__ = ["check_preferences", "setting_problems"]

_SETTINGS = ("KARNI_PREFERENCES_LOCKED", "KARNI_PREFERENCES_DEFAULTS")


@checks.register()
def check_preferences(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E320 (see the module docstring)."""
    from django.conf import settings

    if not apps.is_installed("karni.preferences"):
        return []
    messages: list[checks.CheckMessage] = []
    for name in _SETTINGS:
        for problem in setting_problems(getattr(settings, name, None) or {}):
            messages.append(
                check_error(
                    "E320",
                    f"{name}: {problem}",
                    hint=f"Correct {name} in settings: {{'details': {{'name': ...}}, "
                    "'<section>': {'<field>': ...}, 'connections': {'<name>': True}, "
                    "'emails': {'<kind>': False}}.",
                    obj=f"settings.{name}",
                )
            )
    return messages


def setting_problems(found: Any) -> list[str]:
    """What is wrong with a locks or defaults mapping, one line each."""
    from karni.preferences.models import DETAIL_FIELDS
    from karni.preferences.registry import (
        find_connection,
        find_section,
        sections,
    )

    if not isinstance(found, Mapping):
        return [f"{found!r} is not a mapping of groups."]
    problems: list[str] = []
    for group, values in found.items():
        if not isinstance(values, Mapping):
            problems.append(f"{group!r} holds {values!r}, not a mapping of names to values.")
            continue
        if group == "details":
            problems += _details_problems(values, DETAIL_FIELDS)
        elif group == "connections":
            for name, value in values.items():
                if find_connection(str(name)) is None:
                    problems.append(f"no connection {name!r} is declared.")
                elif not isinstance(value, bool):
                    problems.append(f"connections.{name} is {value!r}, not True or False.")
        elif group == "emails":
            for name, value in values.items():
                if not isinstance(value, bool):
                    problems.append(f"emails.{name} is {value!r}, not True or False.")
        else:
            spec = find_section(str(group))
            if spec is None:
                known = ", ".join(s.key for s in sections()) or "none"
                problems.append(
                    f"no section {group!r} is registered (details, connections, emails, "
                    f"or a section: {known})."
                )
                continue
            fields = spec.model.model_fields
            unknown = [name for name in values if name not in fields]
            if unknown:
                problems.append(
                    f"the section {group!r} has no field {', '.join(map(repr, unknown))}."
                )
                continue
            from pydantic import ValidationError

            try:
                spec.model.model_validate({**spec.defaults(), **dict(values)})
            except ValidationError as exc:
                for error in exc.errors():
                    where = ".".join(str(part) for part in error["loc"])
                    problems.append(f"{group}.{where}: {error['msg']}.")
    return problems


def _details_problems(values: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    from django.core.exceptions import ValidationError

    from karni.preferences.models import Details

    problems: list[str] = []
    for name, value in values.items():
        if name not in fields:
            problems.append(f"the details have no field {name!r}.")
            continue
        if name == "logo":
            if not isinstance(value, str):
                problems.append("details.logo is not a file path or address.")
            continue
        try:
            Details._meta.get_field(name).clean(str(value), Details())
        except ValidationError as exc:
            problems.append(f"details.{name}: {' '.join(exc.messages)}")
    return problems
