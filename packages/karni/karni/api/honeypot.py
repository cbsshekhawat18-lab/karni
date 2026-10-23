"""A honeypot field on public creates: a form field no person fills in.

A viewset whose ``create`` lets anonymous callers in (``create=Public()``,
see :func:`karni.api.throttling.is_public_create`) accepts one extra field
named by ``KARNI_PUBLIC_CREATE_HONEYPOT_FIELD`` (default ``"homepage"``).
@karni/ui's ``ResourceForm`` renders it hidden from people and from
assistive technology. A request that fills it is a script: it is answered
``202 Accepted`` and nothing is saved, the same way registration treats its
honeypot (``KARNI_ACCOUNTS_HONEYPOT_FIELD``), so the script learns nothing.

The field is not part of the request body in the OpenAPI schema, so it is
never required and never generated as a form field. The create operation
names it in ``x-karni-honeypot`` instead, which is how the form knows it.

It is a sibling of the registration setting, not the same one, because
registration's default name (``website``) is a common model field: a contact
form that asks for a website would silently drop every real submission.
When the model or an explicit serializer has a field of the honeypot's name,
the honeypot is off for that viewset, so a real field is never swallowed.

Override / escape hatch: ``KARNI_PUBLIC_CREATE_HONEYPOT_FIELD = ""`` turns
the honeypot off everywhere, another value renames it, and a viewset's
``get_honeypot_field()`` returns ``None`` (off) or another name for that
viewset alone.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DEFAULT_HONEYPOT_FIELD", "honeypot_field", "honeypot_filled"]

#: ``KARNI_PUBLIC_CREATE_HONEYPOT_FIELD`` when the setting is absent.
DEFAULT_HONEYPOT_FIELD = "homepage"


def _taken_names(view: Any) -> set[str]:
    """Field names the request body may legitimately carry: the model's and the serializer's."""
    names: set[str] = set()
    model = getattr(view, "model", None) or getattr(getattr(view, "queryset", None), "model", None)
    if model is not None:
        for field in model._meta.get_fields():
            names.add(field.name)
            attname = getattr(field, "attname", None)
            if attname:
                names.add(attname)
    serializer_class = getattr(view, "serializer_class", None)
    names.update(getattr(serializer_class, "_declared_fields", {}) or {})
    return names


def honeypot_field(view: Any) -> str | None:
    """The honeypot field of ``view``'s create, or ``None`` when it has none.

    ``None`` when the setting is empty, when ``create`` is not public, or
    when the model or serializer already has a field of that name.
    """
    from django.conf import settings

    from karni.api.throttling import is_public_create

    name = getattr(settings, "KARNI_PUBLIC_CREATE_HONEYPOT_FIELD", DEFAULT_HONEYPOT_FIELD)
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    if not is_public_create(view) or name in _taken_names(view):
        return None
    return name


def honeypot_filled(request: Any, name: str) -> bool:
    """Whether the request body fills ``name`` with anything but whitespace."""
    data = getattr(request, "data", None)
    getter = getattr(data, "get", None)
    if not callable(getter):
        return False
    return bool(str(getter(name) or "").strip())
