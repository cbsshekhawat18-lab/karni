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
from django.contrib import admin, messages
from django.contrib.admin.utils import flatten, flatten_fieldsets
from django.db import models
from django.db.models import Q
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
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
from karni.admin.scope import scope_queryset, scoped_choices, within_scope
from karni.admin.soft_delete import SoftDeleteAdminMixin, lift_soft_delete
from karni.admin.transfer import TransferAdminMixin
from karni.exceptions import KarniImproperlyConfigured, KarniWriteDeferred
from karni.models import SoftDeleteModel
from karni.signals import pre_write

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
        raise KarniImproperlyConfigured(
            f"KARNI_ADMIN_BASE points at {path!r}, which cannot be imported: {exc}", code="E301"
        ) from exc
    if not (isinstance(base, type) and issubclass(base, admin.ModelAdmin)):
        raise KarniImproperlyConfigured(
            f"KARNI_ADMIN_BASE must name a django.contrib.admin.ModelAdmin "
            f"subclass; {path!r} is not one.",
            code="E301",
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
    * **Row scope** (ADR 0002, P2): ``get_queryset`` shows only the rows the
      user's grants reach for ``view`` (:mod:`karni.admin.scope`), so the
      changelist, search, filters, autocomplete and actions all agree with
      the API; ``has_view/change/delete_permission(request, obj)`` also
      require the row to be inside the matching grant's scope, and relation
      choices are limited to target rows the user may view. Django's model
      permissions still decide which screens exist. ``scope_exempt = True``
      with a ``scope_exempt_reason`` turns the row scope off for one admin
      (``karni check`` lists every exemption).
    * **Import and export** (ADR 0002, P6) come from
      :class:`karni.admin.transfer.TransferAdminMixin`, mixed into
      :class:`KarniModelAdmin`: the *Export selected* actions and the
      *Import* page (``karni_transfer = False`` removes them).

    Override / escape hatch: subclass and override any ``derive_*`` hook to
    change one rule, or any plain ``ModelAdmin`` method to change behaviour;
    every override here calls ``super()``, so a custom ``KARNI_ADMIN_BASE``
    underneath keeps working.
    """

    scope_exempt: ClassVar[bool] = False
    """``True`` shows every row Django's model permissions admit (needs a reason)."""

    scope_exempt_reason: ClassVar[str] = ""
    """Why this admin is exempt from row scope — required with ``scope_exempt``."""

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

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[Any]:
        """The rows the user's grants reach for ``view`` (every surface starts here)."""
        return scope_queryset(self, request, super().get_queryset(request))

    def has_view_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        """Django's view-or-change permission, and the row inside the user's scope."""
        return super().has_view_permission(request, obj) and (
            within_scope(self, request, obj, "view") or within_scope(self, request, obj, "change")
        )

    def has_change_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        return super().has_change_permission(request, obj) and within_scope(
            self, request, obj, "change"
        )

    def has_delete_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        return super().has_delete_permission(request, obj) and within_scope(
            self, request, obj, "delete"
        )

    # -- field-level visibility (ADR 0002, P3) --------------------------------

    def hidden_fields(self, request: HttpRequest) -> frozenset[str]:
        """Fields ``Karni.field_roles`` hides from the requesting user."""
        from karni.accounts.visibility import hidden_fields

        return hidden_fields(self.model, getattr(request, "user", None))

    def protected_fields(self, request: HttpRequest) -> frozenset[str]:
        """Fields the requesting user may read but not change (shown read-only)."""
        from karni.accounts.visibility import protected_fields

        return protected_fields(self.model, getattr(request, "user", None))

    @staticmethod
    def _head(name: Any) -> str:
        return str(name).lstrip("^=@$").split("__", 1)[0]

    def get_list_display(self, request: HttpRequest) -> Any:
        hidden = self.hidden_fields(request)
        shown = [n for n in super().get_list_display(request) if self._head(n) not in hidden]
        return shown or ["__str__"]

    def get_list_filter(self, request: HttpRequest) -> Any:
        hidden = self.hidden_fields(request)
        kept = []
        for entry in super().get_list_filter(request):
            name = entry[0] if isinstance(entry, tuple | list) else entry
            if isinstance(name, str) and self._head(name) in hidden:
                continue
            kept.append(entry)
        return kept

    def get_search_fields(self, request: HttpRequest) -> Any:
        hidden = self.hidden_fields(request)
        return [n for n in super().get_search_fields(request) if self._head(n) not in hidden]

    def get_sortable_by(self, request: HttpRequest) -> Any:
        hidden = self.hidden_fields(request)
        return [n for n in super().get_sortable_by(request) if self._head(n) not in hidden]

    def get_fields(self, request: HttpRequest, obj: models.Model | None = None) -> Any:
        hidden = self.hidden_fields(request)
        return [n for n in super().get_fields(request, obj) if self._head(n) not in hidden]

    def get_fieldsets(self, request: HttpRequest, obj: models.Model | None = None) -> Any:
        hidden = self.hidden_fields(request)
        if not hidden:
            return super().get_fieldsets(request, obj)
        kept = []
        for title, options in super().get_fieldsets(request, obj):
            fields = [
                n
                for n in options.get("fields", ())
                if not (isinstance(n, str) and self._head(n) in hidden)
            ]
            kept.append((title, {**options, "fields": fields}))
        return kept

    def get_readonly_fields(self, request: HttpRequest, obj: models.Model | None = None) -> Any:
        protected = self.protected_fields(request) - self.hidden_fields(request)
        names = list(super().get_readonly_fields(request, obj))
        names.extend(sorted(n for n in protected if n not in names))
        return names

    def lookup_allowed(self, lookup: str, value: Any, request: HttpRequest | None = None) -> bool:
        """A changelist lookup on a hidden field is a value oracle; refuse it."""
        if request is not None and self._head(lookup) in self.hidden_fields(request):
            return False
        return bool(super().lookup_allowed(lookup, value, request))

    # -- change history (ADR 0002, P4) ----------------------------------------

    def history_view(
        self, request: HttpRequest, object_id: str, extra_context: dict[str, Any] | None = None
    ) -> Any:
        """The History tab: field-level changes (``karni.audit``) above Django's admin log.

        Only for models that opt in with ``Karni.audit``; the diffs shown
        respect ``Karni.field_roles`` for the viewing user.
        """
        from karni.audit.services import audited, history_for

        context = dict(extra_context or {})
        if audited(self.model):
            obj = self.get_object(request, object_id)
            entries: list[Any] = []
            if obj is not None:
                for entry in history_for(obj)[:200]:
                    entry.visible = entry.visible_diff(request.user)
                    entries.append(entry)
            context["karni_change_logs"] = entries
            self.object_history_template = "karni_admin/object_history.html"
        return super().history_view(request, object_id, context)

    def formfield_for_manytomany(
        self, db_field: models.ManyToManyField, request: HttpRequest, **kwargs: Any
    ) -> Any:
        """M2M choices limited to target rows the user may view (what the API accepts)."""
        if "queryset" not in kwargs and not self.scope_exempt:
            target = db_field.remote_field.model
            kwargs["queryset"] = scoped_choices(request, target._default_manager.all())
        return super().formfield_for_manytomany(db_field, request, **kwargs)

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

        The choices are also limited to the target rows the user may view
        (ADR 0002, P2) — what the API's relation fields accept.

        Override / escape hatch: pass ``kwargs["queryset"]`` from a subclass,
        or override this method.
        """
        target = db_field.remote_field.model
        if "queryset" not in kwargs:
            queryset = target._default_manager.all()
            if issubclass(target, SoftDeleteModel):
                obj = getattr(request, _REQUEST_OBJ_ATTR, None)
                current_pk = getattr(obj, db_field.attname, None) if obj is not None else None
                if current_pk is not None:
                    queryset = lift_soft_delete(
                        target._default_manager, reason="admin: keep the current FK value valid"
                    ).filter(Q(deleted_at__isnull=True) | Q(pk=current_pk))
            if not self.scope_exempt:
                queryset = scoped_choices(request, queryset)
            kwargs["queryset"] = queryset
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # -- deferred writes (karni.signals.pre_write) ----------------------------

    _DEFERRED_ATTR: ClassVar[str] = "_karni_write_deferred"

    def _defer(self, request: HttpRequest, exc: KarniWriteDeferred) -> None:
        setattr(request, self._DEFERRED_ATTR, exc)

    def _deferred_redirect(self, request: HttpRequest) -> HttpResponseRedirect | None:
        """After a deferred write: the receiver's message, then back to the changelist."""
        exc = getattr(request, self._DEFERRED_ATTR, None)
        if exc is None:
            return None
        self.message_user(request, str(exc), messages.INFO)
        opts = self.model._meta
        return HttpResponseRedirect(
            reverse(f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_changelist")
        )

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        """Save, unless a ``pre_write`` receiver defers the write (karni-approvals)."""
        try:
            super().save_model(request, obj, form, change)
        except KarniWriteDeferred as exc:
            self._defer(request, exc)

    def save_related(self, request: HttpRequest, form: Any, formsets: Any, change: bool) -> None:
        if getattr(request, self._DEFERRED_ATTR, None) is not None:
            return  # the parent was not written; its inlines must not be either
        super().save_related(request, form, formsets, change)

    def delete_model(self, request: HttpRequest, obj: Any) -> None:
        try:
            super().delete_model(request, obj)
        except KarniWriteDeferred as exc:
            self._defer(request, exc)

    def delete_queryset(self, request: HttpRequest, queryset: models.QuerySet[Any]) -> None:
        """One ``delete()`` per row when something listens to ``pre_write`` (bulk SQL skips it)."""
        if pre_write.has_listeners(queryset.model):
            for obj in queryset:
                self.delete_model(request, obj)
            return
        super().delete_queryset(request, queryset)

    def response_add(self, request: HttpRequest, obj: Any, post_url_continue: Any = None) -> Any:
        return self._deferred_redirect(request) or super().response_add(
            request, obj, post_url_continue
        )

    def response_change(self, request: HttpRequest, obj: Any) -> Any:
        return self._deferred_redirect(request) or super().response_change(request, obj)

    def response_delete(self, request: HttpRequest, obj_display: Any, obj_id: Any) -> Any:
        return self._deferred_redirect(request) or super().response_delete(
            request, obj_display, obj_id
        )

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


class KarniModelAdmin(KarniAdminMixin, TransferAdminMixin, _AdminBase):  # type: ignore[valid-type, misc]
    """:class:`KarniAdminMixin` (and the import/export mixin) on the ``KARNI_ADMIN_BASE`` class.

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
