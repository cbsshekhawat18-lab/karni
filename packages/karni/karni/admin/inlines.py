"""``AdminMeta.inline_on`` → generated inline classes for parent admins.

A model declares, on its *own* ``AdminMeta``, the foreign key(s) it should be
inlined on::

    class Chapter(BaseModel):
        book = models.ForeignKey(Book, on_delete=models.CASCADE)
        title = models.CharField(max_length=200)

        class AdminMeta:
            inline_on = "book"          # or a list of FK names

:func:`collect_inlines` gathers those declarations into a parent-model →
children mapping, and :func:`build_inline` turns each ``(child, fk_name)``
pair into a django-unfold ``TabularInline`` that
:func:`karni.admin.autodiscover` attaches to the parent's *generated* admin.
The child model itself stays registered (or excludable) exactly like any
other model — ``inline_on`` only adds the inline.

Scope notes (by design): a parent that is registered explicitly (project
``admin.py``, third-party app) keeps its own admin untouched — declare the
inline there yourself; a soft-delete child's inline shows alive rows only
(the child's default manager hides deleted rows); and inline foreign keys to
soft-delete targets keep alive-only choices with no current-value carve-out
(one form field is shared by every inline row).

Override / escape hatch: set ``inlines`` via the parent's ``AdminMeta.extra``
(it beats the generated ones), or call :func:`build_inline` yourself and
subclass the result.

This module is imported from ``autodiscover()`` only — after the app registry
is ready — so the django-unfold import at module level is safe.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.contrib.admin.options import InlineModelAdmin
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.http import HttpRequest
from unfold.admin import TabularInline

from karni.admin.derive import admin_meta, password_field_names
from karni.db import is_read_only
from karni.exceptions import KarniImproperlyConfigured

__all__ = ["KarniInlineMixin", "build_inline", "collect_inlines"]

#: One ``AdminMeta.inline_on`` declaration: the child model and the name of
#: the FK on it that points at the parent.
InlineSpec = tuple[type[models.Model], str]


class KarniInlineMixin(InlineModelAdmin):  # type: ignore[type-arg]
    """An inline whose rows open for a role's grant on the inline's model.

    A user holding ``app_label.model:<action>`` for the inline's model may do
    that action on its rows, as Django's model permission allows. The same
    rule as :meth:`karni.admin.base.KarniAdminMixin.granted`, and off with it
    (``KARNI_ADMIN_GRANTS_OPEN_PAGES = False``). Mix it in front of any
    inline class: ``class LineInline(KarniInlineMixin, TabularInline)``.

    Override / escape hatch: override :meth:`granted`, or leave the mixin out
    to keep an inline on Django's permissions only.
    """

    def granted(self, request: HttpRequest, action: str) -> bool:
        """Whether the user holds ``action`` on the inline's model through a role."""
        from django.conf import settings

        if not getattr(settings, "KARNI_ADMIN_GRANTS_OPEN_PAGES", True):
            return False
        from karni.accounts.roles import user_can
        from karni.meta import permission_key

        return user_can(getattr(request, "user", None), permission_key(self.model, action))

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return (
            self.granted(request, "view")
            or self.granted(request, "change")
            or super().has_view_permission(request, obj)
        )

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.granted(request, "add") or super().has_add_permission(request, obj)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.granted(request, "change") or super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.granted(request, "delete") or super().has_delete_permission(request, obj)


def collect_inlines(
    model_list: Iterable[type[models.Model]],
) -> dict[type[models.Model], list[InlineSpec]]:
    """Map each parent model to the ``(child, fk_name)`` pairs declared on children.

    Walks ``model_list`` (normally ``apps.get_models()``) looking for
    ``AdminMeta.inline_on`` — a FK field name or a list of them — and resolves
    each name against the child's fields. Misconfigurations fail loudly at
    startup: a name that is not a field, or a field that is not a
    ``ForeignKey``, raises ``ImproperlyConfigured`` naming the model and
    field, because a silently dropped inline is far harder to notice.

    ``AdminMeta.exclude = True`` on the child skips its *own* registration
    only; the inline on the parent is still generated.
    """
    mapping: dict[type[models.Model], list[InlineSpec]] = {}
    for child in model_list:
        meta = admin_meta(child)
        inline_on = getattr(meta, "inline_on", None) if meta is not None else None
        if not inline_on:
            continue
        names = [inline_on] if isinstance(inline_on, str) else [str(name) for name in inline_on]
        for name in names:
            try:
                field = child._meta.get_field(name)
            except FieldDoesNotExist as exc:
                raise KarniImproperlyConfigured(
                    f"{child._meta.label}.AdminMeta.inline_on names {name!r}, "
                    f"which is not a field on {child.__name__}.",
                    code="E302",
                ) from exc
            if not isinstance(field, models.ForeignKey):
                raise KarniImproperlyConfigured(
                    f"{child._meta.label}.AdminMeta.inline_on names {name!r}, "
                    f"which is a {type(field).__name__}, not a ForeignKey.",
                    code="E302",
                )
            parent = field.remote_field.model
            mapping.setdefault(parent, []).append((child, name))
    return mapping


def build_inline(model: type[models.Model], fk_name: str) -> type[TabularInline]:
    """Build the ``TabularInline`` class for one ``(child, fk_name)`` pair.

    A django-unfold ``TabularInline`` (so inlines match the rest of the admin
    UI) with ``fk_name`` pinned — a child with several FKs to the same parent
    gets one inline per declared name — ``extra = 0`` (changelists stay
    honest; adding rows is one click) and ``show_change_link = True`` so the
    child's full change form stays reachable. Password-named fields are
    excluded from the inline form, mirroring the derived parent form
    (amendment C5). :class:`KarniInlineMixin` in front lets a role's grant
    on the child model open its rows.

    Override / escape hatch: subclass the returned class, or replace the
    parent's ``inlines`` wholesale via its ``AdminMeta.extra``.
    """
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "__qualname__": f"{model.__name__}Inline",
        "model": model,
        "fk_name": fk_name,
        "extra": 0,
        "show_change_link": True,
    }
    passwords = password_field_names(model)
    if passwords:
        attrs["exclude"] = list(passwords)
    if is_read_only(model):
        # An external table Karni only reads (experimental): its rows show, none changes.
        attrs.update(
            has_add_permission=_refuse,
            has_change_permission=_refuse,
            has_delete_permission=_refuse,
        )
    return type(f"{model.__name__}Inline", (KarniInlineMixin, TabularInline), attrs)


def _refuse(self: Any, request: Any, obj: Any = None) -> bool:
    return False
