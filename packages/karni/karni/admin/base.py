"""The derived admin base classes and the per-model admin factory.

:class:`KarniAdminMixin` carries every Karni behaviour as cooperative
``ModelAdmin`` overrides: attribute derivation at ``__init__`` time (one
classmethod hook per rule in :mod:`karni.admin.derive`), form-level exclusion
of password-named fields (admin contract amendment C5), and soft-delete-aware
foreign-key form fields (amendment C3). :class:`KarniModelAdmin` is that mixin
on top of the ``KARNI_ADMIN_BASE`` class — django-unfold's ``ModelAdmin`` by
default — and :func:`build_model_admin` turns one model (plus its ``AdminMeta``
overrides and any generated inlines) into a registrable admin class for
:func:`karni.admin.autodiscover`.

``KARNI_ADMIN_BASE`` is resolved lazily (amendment C6): this module is only
imported on first attribute access of :mod:`karni.admin` (its module
``__getattr__``) or at autodiscovery, never while the app registry is still
populating. Once imported, the class is fixed — changing the setting later
(including via ``override_settings``) does not rebuild ``KarniModelAdmin``;
:func:`resolve_admin_base` stays testable on its own.

Override / escape hatches, weakest to strongest:

* ``KARNI_ADMIN_BASE``: a dotted path to any ``ModelAdmin`` subclass (it must
  not itself derive from ``KarniModelAdmin`` — that would be circular); its
  behaviour sits *under* the mixin, whose overrides all call ``super()``.
* per model: ``class AdminMeta`` attributes, applied by
  :func:`build_model_admin` and always beating derivation.
* per project: subclass ``KarniModelAdmin``, override any ``derive_*``
  classmethod hook or plain ``ModelAdmin`` method, and register by hand
  (optionally with ``KARNI_ADMIN_AUTODISCOVER = False``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.utils import flatten, flatten_fieldsets
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.forms import ModelForm
from django.http import HttpRequest
from django.utils.module_loading import import_string

from karni.admin.derive import (
    admin_meta,
    derive_date_hierarchy,
    derive_list_display,
    derive_list_filter,
    derive_list_select_related,
    derive_readonly_fields,
    derive_search_fields,
    password_field_names,
)
from karni.admin.soft_delete import SoftDeleteAdminMixin, lift_soft_delete
from karni.models import SoftDeleteModel

__all__ = [
    "DEFAULT_ADMIN_BASE",
    "KarniAdminMixin",
    "KarniModelAdmin",
    "build_model_admin",
    "resolve_admin_base",
]

DEFAULT_ADMIN_BASE = "unfold.admin.ModelAdmin"
"""Fallback for the ``KARNI_ADMIN_BASE`` setting (kept in sync with
``karni.conf.base``)."""

#: Stock ``ModelAdmin`` defaults (identical on django-unfold's subclass): an
#: attribute still holding its stock value is considered "not set" and gets
#: derived at ``__init__`` time.
_STOCK_DEFAULTS: dict[str, Any] = {
    "list_display": ("__str__",),
    "list_filter": (),
    "search_fields": (),
    "date_hierarchy": None,
    "readonly_fields": (),
    "list_select_related": False,
}

#: ``AdminMeta`` attributes copied verbatim onto the generated admin class.
_ADMIN_META_PASSTHROUGH = (
    "list_display",
    "list_filter",
    "search_fields",
    "date_hierarchy",
    "ordering",
)

_REQUEST_OBJ_ATTR = "_karni_admin_obj"


def resolve_admin_base() -> type[admin.ModelAdmin]:
    """Resolve ``KARNI_ADMIN_BASE`` to the class ``KarniModelAdmin`` extends.

    Called once, when this module is first imported (which the package defers
    until after the app registry is ready — amendment C6). The dotted path
    must name a ``ModelAdmin`` subclass; anything else raises
    ``ImproperlyConfigured`` with the offending path in the message.

    Override / escape hatch: set ``KARNI_ADMIN_BASE`` in ``settings.py``
    *before* Django starts — because the result is baked into
    ``KarniModelAdmin`` at import time, changing it afterwards (e.g. with
    ``override_settings``) has no effect on already-built classes.
    """
    path: str = getattr(settings, "KARNI_ADMIN_BASE", DEFAULT_ADMIN_BASE)
    try:
        base = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"KARNI_ADMIN_BASE points at {path!r}, which cannot be imported: {exc}"
        ) from exc
    if not (isinstance(base, type) and issubclass(base, admin.ModelAdmin)):
        raise ImproperlyConfigured(
            f"KARNI_ADMIN_BASE must name a django.contrib.admin.ModelAdmin "
            f"subclass; {path!r} is not one."
        )
    return base


class KarniAdminMixin(admin.ModelAdmin):
    """Every Karni admin behaviour, as cooperative ``ModelAdmin`` overrides.

    * ``__init__`` fills each attribute still holding its stock default from
      the matching ``derive_*`` classmethod hook (which delegates to the pure
      functions in :mod:`karni.admin.derive`) — explicit class attributes, and
      anything :func:`build_model_admin` marked explicit from ``AdminMeta``,
      are never touched.
    * ``get_exclude`` keeps password-named fields out of derived forms
      (amendment C5) — unless the admin declares them itself via ``fields`` /
      ``fieldsets`` (the ``KarniUserAdmin`` pattern), in which case the
      declaration wins.
    * ``formfield_for_foreignkey`` keeps a change form's *current* value valid
      when it points at a soft-deleted row, while new choices stay alive-only
      (amendment C3). Add forms and untouched fields keep Django's default
      queryset, which is already alive-only for soft-delete targets.

    Override / escape hatch: subclass and override any ``derive_*`` hook to
    change one rule, or any plain ``ModelAdmin`` method to change behaviour;
    every override here calls ``super()``, so a custom ``KARNI_ADMIN_BASE``
    underneath keeps working.
    """

    _karni_generated: ClassVar[bool] = False
    """True only on classes built by :func:`build_model_admin`."""

    _karni_autocomplete_managed: ClassVar[bool] = False
    """Whether ``autodiscover()``'s second pass may assign ``autocomplete_fields``."""

    _karni_explicit: ClassVar[frozenset[str]] = frozenset()
    """Attribute names ``AdminMeta`` set explicitly — never derived, even when
    their value happens to equal the stock default (e.g. ``date_hierarchy =
    None`` to disable the drilldown). Hand-written subclasses may set this too.
    """

    karni_read_only: ClassVar[tuple[str, ...]] = ()
    """``AdminMeta.read_only`` entries, appended to the *derived*
    ``readonly_fields`` (an explicit ``readonly_fields`` wins outright)."""

    def __init__(self, model: type[models.Model], admin_site: admin.AdminSite) -> None:
        """Instantiate and fill underived attributes from the ``derive_*`` hooks.

        Derivation is per *instance* (Django registers one admin instance per
        model/site pair), so the shared class attributes and Django's stock
        defaults are never mutated, and ``override_settings`` on the caps
        affects freshly built admins only.
        """
        super().__init__(model, admin_site)
        cls = type(self)
        if self._karni_derivable("list_display"):
            self.list_display = list(cls.derive_list_display(model))
        if self._karni_derivable("list_filter"):
            self.list_filter = list(cls.derive_list_filter(model))
        if self._karni_derivable("search_fields"):
            self.search_fields = list(cls.derive_search_fields(model))
        if self._karni_derivable("date_hierarchy"):
            self.date_hierarchy = cls.derive_date_hierarchy(model)
        if self._karni_derivable("readonly_fields"):
            derived = list(cls.derive_readonly_fields(model))
            self.readonly_fields = [
                *derived,
                *(name for name in self.karni_read_only if name not in derived),
            ]
        if self._karni_derivable("list_select_related"):
            display = [name for name in self.list_display if isinstance(name, str)]
            related = cls.derive_list_select_related(model, display)
            if related:
                self.list_select_related = list(related)

    # -- derivation hooks (one per rule; see karni.admin.derive) -------------

    @classmethod
    def derive_list_display(cls, model: type[models.Model]) -> list[str]:
        """Hook for :func:`karni.admin.derive.derive_list_display`."""
        return derive_list_display(model)

    @classmethod
    def derive_list_filter(cls, model: type[models.Model]) -> list[Any]:
        """Hook for :func:`karni.admin.derive.derive_list_filter`."""
        return list(derive_list_filter(model))

    @classmethod
    def derive_search_fields(cls, model: type[models.Model]) -> list[str]:
        """Hook for :func:`karni.admin.derive.derive_search_fields`."""
        return derive_search_fields(model)

    @classmethod
    def derive_date_hierarchy(cls, model: type[models.Model]) -> str | None:
        """Hook for :func:`karni.admin.derive.derive_date_hierarchy`."""
        return derive_date_hierarchy(model)

    @classmethod
    def derive_readonly_fields(cls, model: type[models.Model]) -> tuple[str, ...]:
        """Hook for :func:`karni.admin.derive.derive_readonly_fields`."""
        return derive_readonly_fields(model)

    @classmethod
    def derive_list_select_related(
        cls, model: type[models.Model], list_display: list[str]
    ) -> tuple[str, ...]:
        """Hook for :func:`karni.admin.derive.derive_list_select_related`."""
        return derive_list_select_related(model, list_display)

    # -- behaviour overrides -------------------------------------------------

    def get_exclude(self, request: HttpRequest, obj: models.Model | None = None) -> Any:
        """Exclude password-named fields from the form (amendment C5).

        A field the admin *declares* — in ``fields`` or ``fieldsets`` — is
        deliberately exposed and stays (``KarniUserAdmin`` declares
        ``password`` this way to keep Django's hashed-password widget), as
        does anything an explicit ``exclude`` already lists.

        Override / escape hatch: declare the field in ``fields`` /
        ``fieldsets`` (via ``AdminMeta.extra`` or a subclass), or override
        this method outright.
        """
        exclude = super().get_exclude(request, obj)
        passwords = password_field_names(self.model)
        if not passwords:
            return exclude
        declared: set[str] = set()
        if self.fieldsets:
            declared.update(flatten_fieldsets(self.fieldsets))
        if self.fields:
            declared.update(flatten(self.fields))
        merged: list[str] = list(exclude) if exclude is not None else []
        merged.extend(name for name in passwords if name not in declared and name not in merged)
        return merged or None

    def get_form(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[ModelForm]:
        """Stash the edited object so FK form fields can keep its current values.

        ``formfield_for_foreignkey`` receives only the request, so the object
        travels on it (one admin form is built per request; inlines build
        their own form classes and never read the stash).
        """
        setattr(request, _REQUEST_OBJ_ATTR, obj)
        return super().get_form(request, obj=obj, change=change, **kwargs)

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: Any
    ) -> Any:
        """Keep a soft-deleted *current* FK value valid; new choices stay alive.

        Only intervenes when the field targets a
        :class:`karni.models.SoftDeleteModel`, no explicit ``queryset`` was
        passed, and the form's current value exists — the queryset then
        becomes "alive rows plus that one value", so re-saving a row that
        already references a deleted object validates (amendment C3). In every
        other case Django's default applies, which is alive-only for
        soft-delete targets (their default manager hides deleted rows).

        Override / escape hatch: pass ``kwargs["queryset"]`` from a subclass,
        or override this method.
        """
        target = db_field.remote_field.model
        if "queryset" not in kwargs and issubclass(target, SoftDeleteModel):
            obj = getattr(request, _REQUEST_OBJ_ATTR, None)
            current_pk = getattr(obj, db_field.attname, None) if obj is not None else None
            if current_pk is not None:
                kwargs["queryset"] = lift_soft_delete(
                    target._default_manager, reason="admin: keep the current FK value valid"
                ).filter(Q(deleted_at__isnull=True) | Q(pk=current_pk))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # -- internals -----------------------------------------------------------

    def _karni_derivable(self, name: str) -> bool:
        """Whether ``name`` should be derived: not explicit, still stock."""
        if name in self._karni_explicit:
            return False
        current = getattr(self, name)
        stock = _STOCK_DEFAULTS[name]
        if isinstance(stock, tuple):
            return isinstance(current, list | tuple) and tuple(current) == stock
        return bool(current == stock)


_AdminBase: type[admin.ModelAdmin] = resolve_admin_base()


class KarniModelAdmin(KarniAdminMixin, _AdminBase):  # type: ignore[valid-type, misc]
    """:class:`KarniAdminMixin` on the ``KARNI_ADMIN_BASE`` class.

    The class :func:`karni.admin.autodiscover` derives every generated admin
    from, and the base class to hand-register with when autodiscovery is off::

        from django.contrib import admin
        from karni.admin import KarniModelAdmin
        from myapp.models import Invoice

        @admin.register(Invoice)
        class InvoiceAdmin(KarniModelAdmin):
            # anything not set here is derived from the model
            list_per_page = 25

    Override / escape hatch: any stock ``ModelAdmin`` attribute or method, the
    ``derive_*`` hooks, or ``_karni_explicit`` to pin an attribute to a value
    that happens to equal the stock default (e.g. no date drilldown).
    """


def build_model_admin(
    model: type[models.Model],
    *,
    inlines: Sequence[type[admin.options.InlineModelAdmin]] = (),
) -> type[KarniModelAdmin]:
    """Build the admin class :func:`karni.admin.autodiscover` registers for ``model``.

    ``AdminMeta`` attributes become explicit class attributes (and are marked
    so derivation leaves them alone — including explicit ``None`` /
    empty values); ``AdminMeta.read_only`` extends the derived
    ``readonly_fields``; ``AdminMeta.extra`` is applied last and may set *any*
    ``ModelAdmin`` attribute, including callables. Soft-delete models get
    :class:`karni.admin.soft_delete.SoftDeleteAdminMixin` in front.

    The generated class carries ``_karni_generated = True`` (so the
    autocomplete second pass, and nothing else, may touch it later) and
    ``_karni_autocomplete_managed`` unless ``extra`` pinned
    ``autocomplete_fields`` itself.

    Override / escape hatch: register the model yourself before autodiscovery
    runs — this factory is only used for models nothing else registered — or
    call it directly with your own ``inlines`` when hand-registering.
    """
    meta = admin_meta(model)
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "__qualname__": f"{model.__name__}Admin",
        "_karni_generated": True,
    }
    explicit: set[str] = set()
    if meta is not None:
        for name in _ADMIN_META_PASSTHROUGH:
            if hasattr(meta, name):
                attrs[name] = getattr(meta, name)
                explicit.add(name)
        if hasattr(meta, "read_only"):
            attrs["karni_read_only"] = tuple(meta.read_only or ())
        extra = dict(getattr(meta, "extra", None) or {})
        attrs.update(extra)
        explicit.update(extra)
    if inlines:
        attrs["inlines"] = list(inlines)
    attrs["_karni_explicit"] = frozenset(explicit)
    attrs["_karni_autocomplete_managed"] = "autocomplete_fields" not in attrs
    bases: tuple[type, ...]
    if issubclass(model, SoftDeleteModel):
        bases = (SoftDeleteAdminMixin, KarniModelAdmin)
    else:
        bases = (KarniModelAdmin,)
    return type(f"{model.__name__}Admin", bases, attrs)
