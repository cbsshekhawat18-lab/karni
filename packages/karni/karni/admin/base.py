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
from django.contrib.admin.utils import flatten, flatten_fieldsets, quote
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Q
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from karni.admin.bulk import BulkEditAdminMixin
from karni.admin.derive import (
    admin_meta,
    derive_date_hierarchy,
    derive_help,
    derive_list_display,
    derive_list_filter,
    derive_list_select_related,
    derive_readonly_fields,
    derive_search_fields,
    password_field_names,
    technical_fields,
)
from karni.admin.listing import (
    PER_PAGE_CHOICES,
    PER_PAGE_VAR,
    KarniChangeListMixin,
    KarniPaginator,
    per_page_default,
)
from karni.admin.scope import scope_queryset, scoped_choices, within_scope
from karni.admin.soft_delete import SoftDeleteAdminMixin, lift_soft_delete
from karni.admin.transfer import TransferAdminMixin
from karni.conflicts import KarniConflict
from karni.exceptions import KarniImproperlyConfigured, KarniWriteDeferred
from karni.meta import STANDARD_ACTIONS
from karni.models import SoftDeleteModel
from karni.signals import pre_write
from karni.tree import is_tree_model

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

_LIST_CLASSES: dict[type, type] = {}


def _karni_changelist_class(base: type) -> type:
    """``base`` with :class:`KarniChangeListMixin` in front (one class per base)."""
    found = _LIST_CLASSES.get(base)
    if found is None:
        found = type(f"Karni{base.__name__}", (KarniChangeListMixin, base), {})
        _LIST_CLASSES[base] = found
    return found


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
            f"subclass, and {path!r} is not one.",
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
    * **Who may open a page**: a role's grant (``app.model:<action>``) opens
      the page for that action, and so does Django's model permission
      (:meth:`granted`; ``KARNI_ADMIN_GRANTS_OPEN_PAGES = False`` leaves
      Django's permissions alone). The index and app list show exactly the
      models the user may open. Signing in still needs ``is_staff``.
    * **Row scope** (ADR 0002, P2): ``get_queryset`` shows only the rows the
      user's grants reach for ``view`` (:mod:`karni.admin.scope`), so the
      changelist, search, filters, autocomplete and actions all agree with
      the API; ``has_view/change/delete_permission(request, obj)`` also
      require the row to be inside the matching grant's scope, and relation
      choices are limited to target rows the user may view.
      ``scope_exempt = True`` with a ``scope_exempt_reason`` turns the row
      scope off for one admin (``karni check`` lists every exemption).
    * **Read-only external models** (experimental): a model with ``class
      Karni: external = True`` and no ``writable = True`` has no add, change
      or delete permission here, so the admin lists it and shows its rows
      read-only (:meth:`is_read_only`).
    * **Tree models** (experimental): a :class:`karni.models.TreeModel`'s
      changelist lists the rows in tree order with the name indented by
      depth (:mod:`karni.admin.tree`, ``tree_changelist_max_rows``).
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
    """``True`` shows every row to whoever may open the page (needs a reason)."""

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

    tree_changelist_max_rows: ClassVar[int] = 10000
    """Experimental. The most rows a tree model's changelist puts in tree order (0: never)."""

    karni_read_only: ClassVar[tuple[str, ...]] = ()
    """``AdminMeta.read_only`` entries, appended to the *derived*
    ``readonly_fields`` (an explicit ``readonly_fields`` wins outright)."""

    karni_help: ClassVar[str | None] = None
    """The one line shown at the top of the list and form. ``None`` derives it
    (:func:`karni.admin.derive.derive_help`: ``class Karni: help`` and nothing
    else, never the docstring), ``""`` shows none."""

    list_per_page = None  # type: ignore[assignment]
    """Rows per page. ``None`` takes ``KARNI_ADMIN_PER_PAGE`` (25) at ``__init__``;
    ``AdminMeta.per_page`` or a number here sets one model's."""

    karni_per_page_choices: ClassVar[tuple[int, ...]] = PER_PAGE_CHOICES
    """The page sizes ``?per_page=`` accepts (the admin's own ``list_per_page`` joins them)."""

    paginator = KarniPaginator
    """Django's paginator, with a count that is an estimate on a very large PostgreSQL table."""

    karni_row_actions: ClassVar[bool] = True
    """``False`` removes the *Actions* column (Edit, Delete, Restore) from the list."""

    karni_details: ClassVar[bool] = True
    """``False`` keeps technical fields (ids, timestamps, internal keys) in the
    form's own fieldsets instead of a collapsed, read-only *Details* section."""

    change_list_template = "karni_admin/change_list.html"
    change_form_template = "karni_admin/change_form.html"
    delete_selected_confirmation_template = "karni_admin/delete_selected_confirmation.html"

    def __init__(self, model: type[models.Model], admin_site: admin.AdminSite) -> None:
        """Instantiate and fill underived attributes from the ``derive_*`` hooks.

        Derivation is per *instance* (Django registers one admin instance per
        model/site pair), so the shared class attributes and Django's stock
        defaults are never mutated, and ``override_settings`` on the caps
        affects freshly built admins only.
        """
        super().__init__(model, admin_site)
        cls = type(self)
        if self.list_per_page is None:
            self.list_per_page = cls.derive_per_page(model)
        if is_tree_model(model):
            from karni.admin.tree import TreeLabel, tree_list_display

            self.tree_label = TreeLabel(None, str(model._meta.verbose_name).capitalize())
            if self._karni_derivable("list_display"):
                derived = list(cls.derive_list_display(model))
                self.list_display, self.tree_label = tree_list_display(model, derived)
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
        current = list(getattr(self, "actions", None) or ())
        if "delete_selected" not in current:
            self.actions = ["delete_selected", *current]
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
    def derive_per_page(cls, model: type[models.Model]) -> int:
        """Rows per page: ``KARNI_ADMIN_PER_PAGE``. Override for one rule per model."""
        return per_page_default()

    @classmethod
    def derive_help(cls, model: type[models.Model]) -> str:
        """Hook for :func:`karni.admin.derive.derive_help`."""
        return derive_help(model)

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

    # -- who may open a page: a grant, or Django's model permission -----------

    def granted(self, request: HttpRequest, action: str) -> bool:
        """Whether the user holds ``app_label.model:<action>`` through a role.

        A grant opens this admin's page for that action, as Django's model
        permission does. Superusers hold every grant. ``False`` for everyone
        while ``KARNI_ADMIN_GRANTS_OPEN_PAGES`` is ``False``: then only Django's
        model permissions open pages, the rule before 0.5.0.

        Override / escape hatch: override this method to open pages on another
        rule (``return False`` keeps one admin on Django's permissions only).
        """
        if not getattr(settings, "KARNI_ADMIN_GRANTS_OPEN_PAGES", True):
            return False
        from karni.accounts.roles import user_can
        from karni.meta import permission_key

        return user_can(getattr(request, "user", None), permission_key(self.model, action))

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Django's app permission, or any grant on this model (the index lists it)."""
        return bool(super().has_module_permission(request)) or any(
            self.granted(request, action) for action in ("view", "change", "add", "delete")
        )

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> Any:
        """The base changelist, in tree order for a tree model (:mod:`karni.admin.tree`)."""
        from karni.admin.tree import tree_changelist_class

        base = tree_changelist_class(super().get_changelist(request, **kwargs), self.model)
        return _karni_changelist_class(base)

    def karni_page_sizes(self) -> list[int]:
        """The page sizes the list offers: the choices and this admin's own, ascending."""
        return sorted({*self.karni_per_page_choices, int(self.list_per_page or 0)})

    def karni_page_size(self, request: HttpRequest) -> int:
        """Rows on this request's page: ``?per_page=`` when it is one of the choices."""
        asked = request.GET.get(PER_PAGE_VAR, "")
        if asked.isdigit() and int(asked) in self.karni_page_sizes():
            return int(asked)
        return int(self.list_per_page or 0)

    def get_changelist_instance(self, request: HttpRequest) -> Any:
        request._karni_per_page = self.karni_page_size(request)  # type: ignore[attr-defined]
        return super().get_changelist_instance(request)

    def get_ordering(self, request: HttpRequest) -> Any:
        """The admin's ordering, else the model's, else newest updated first, else newest key.

        Pages must not shuffle, so a list always has an order: ``ordering`` on
        the admin, the model's ``Meta.ordering``, ``-updated_at`` (then
        ``-created_at``) when the model has one, and ``-pk`` at last.

        Override / escape hatch: set ``ordering`` on the admin (``AdminMeta.ordering``),
        or override this method.
        """
        found = super().get_ordering(request)
        if found or self.model._meta.ordering:
            return found
        for name in ("updated_at", "created_at"):
            try:
                field = self.model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            if getattr(field, "concrete", False):
                return [f"-{name}"]
        return ["-pk"]

    def has_view_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        """A view or change grant (else Django's permission), and the row inside the scope."""
        opened = (
            self.granted(request, "view")
            or self.granted(request, "change")
            or super().has_view_permission(request, obj)
        )
        return opened and (
            within_scope(self, request, obj, "view") or within_scope(self, request, obj, "change")
        )

    def is_read_only(self) -> bool:
        """Experimental. Whether this admin only shows rows (:func:`karni.db.is_read_only`).

        True for a model with ``class Karni: external = True`` that does not
        declare ``writable = True``: no add, change or delete, the import
        page is gone, and the change view shows every field read-only.

        Override / escape hatch: return ``False`` to edit through this admin
        alone, or ``True`` to make any admin read-only.
        """
        from karni.db import is_read_only

        return is_read_only(self.model)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """An add grant (else Django's permission), unless a veto or read-only refuses it."""
        opened = self.granted(request, "add") or super().has_add_permission(request)
        return opened and not self.is_read_only() and self.vetoed(request, "add") is None

    def has_change_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        """A change grant (else Django's permission), the row in scope, and no veto."""
        opened = self.granted(request, "change") or super().has_change_permission(request, obj)
        return (
            not self.is_read_only()
            and opened
            and within_scope(self, request, obj, "change")
            and self.vetoed(request, "change") is None
        )

    def has_delete_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        """A delete grant (else Django's permission), the row in scope, and no veto."""
        opened = self.granted(request, "delete") or super().has_delete_permission(request, obj)
        return (
            not self.is_read_only()
            and opened
            and within_scope(self, request, obj, "delete")
            and self.vetoed(request, "delete") is None
        )

    def vetoed(self, request: HttpRequest, action: str) -> str | None:
        """Why a registered veto (:mod:`karni.vetoes`) refuses ``action`` here, or ``None``."""
        from karni.meta import permission_key
        from karni.vetoes import VetoContext, check_vetoes

        permission = permission_key(self.model, action) if action in STANDARD_ACTIONS else None
        return check_vetoes(
            VetoContext(
                request, "admin", action, model=self.model, permission=permission, view=self
            )
        )

    @admin.action(
        description=_lazy("Delete selected %(verbose_name_plural)s"),
        permissions=["delete"],
    )
    def delete_selected(self, request: HttpRequest, queryset: models.QuerySet[Any]) -> Any:
        """Django's "delete selected" with Karni's confirmation page (count and a sample).

        A soft-delete model's rows are soft-deleted (:meth:`delete_queryset`), and the
        page says they can be restored. Permission, the admin log and the response
        cache work as in Django's action.
        """
        from django.contrib.admin.actions import delete_selected

        response = delete_selected(self, request, queryset)
        context = getattr(response, "context_data", None)
        if isinstance(context, dict):
            context["karni_soft"] = issubclass(self.model, SoftDeleteModel)
        return response

    def get_actions(self, request: HttpRequest) -> Any:
        """Django's actions minus the ones a veto refuses (``delete_selected``, ``export_csv``)."""
        found = super().get_actions(request)
        for name in list(found):
            if self.vetoed(request, name) is not None:
                found.pop(name, None)
        return found

    def response_action(self, request: HttpRequest, queryset: models.QuerySet[Any]) -> Any:
        """Run the chosen bulk action, invalidating the API response cache once, at its end.

        Every write the action makes (row by row or in bulk) is collected by
        :func:`karni.api.caching.invalidation_batch`, so a delete of 500 rows
        replaces the model's cache tokens once, not 500 times.
        """
        from karni.api.caching import invalidation_batch

        with invalidation_batch():
            return super().response_action(request, queryset)

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
        column = self.row_actions_column(request)
        return [*(shown or ["__str__"]), *([column] if column is not None else [])]

    # -- the simple screens: a line of help, buttons on each row ----------------

    def model_help(self, request: HttpRequest | None = None) -> str:
        """The one line shown at the top of this model's list and form (``karni_help``)."""
        if self.karni_help is not None:
            return str(self.karni_help)
        return type(self).derive_help(self.model)

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> Any:
        extra = dict(extra_context or {})
        extra.setdefault("karni_help", self.model_help(request))
        return super().changelist_view(request, extra)

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: models.Model | None = None,
    ) -> Any:
        context.setdefault("karni_help", self.model_help(request))
        return super().render_change_form(request, context, add, change, form_url, obj)

    def row_actions_column(self, request: HttpRequest) -> Any:
        """The *Actions* column: Edit and Delete (or Restore) on each row, as rights allow.

        ``None`` (no column) when ``karni_row_actions`` is off, in a popup, or the
        user may do none of it. A user who can only view gets *View*. Rights are
        checked once for the model here, and again by the page each button opens.

        Override / escape hatch: ``karni_row_actions = False`` removes the column,
        or override this method to draw other buttons.
        """
        if not self.karni_row_actions or "_popup" in request.GET:
            return None
        can_change = self.has_change_permission(request)
        can_delete = self.has_delete_permission(request)
        can_view = self.has_view_permission(request)
        if not (can_change or can_delete or can_view):
            return None
        opts = self.model._meta
        stem = f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}"
        soft = issubclass(self.model, SoftDeleteModel)

        def karni_row_actions(obj: models.Model) -> Any:
            key = quote(obj.pk)
            deleted = soft and getattr(obj, "deleted_at", None) is not None
            name = str(obj)
            buttons: list[tuple[str, str, str, str]] = []  # (tag, url, kind, text)
            if can_change:
                buttons.append(("a", reverse(f"{stem}_change", args=[key]), "", _("Edit")))
            elif can_view:
                buttons.append(("a", reverse(f"{stem}_change", args=[key]), "", _("View")))
            if deleted and can_change:
                buttons.append(("button", reverse(f"{stem}_restore", args=[key]), "", _("Restore")))
            elif can_delete and not deleted:
                buttons.append(("a", reverse(f"{stem}_delete", args=[key]), "danger", _("Delete")))
            return format_html(
                '<span class="karni-row-actions">{}</span>',
                format_html_join(
                    "",
                    "{}",
                    (
                        (_row_button(tag, url, kind, text, name),)
                        for tag, url, kind, text in buttons
                    ),
                ),
            )

        karni_row_actions.short_description = _("Actions")  # type: ignore[attr-defined]
        karni_row_actions.admin_order_field = None  # type: ignore[attr-defined]
        return karni_row_actions

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
        """``Karni.field_groups`` as fieldsets, unless the admin declares ``fieldsets`` itself.

        Each group is a fieldset of the form's fields it lists, and the fields
        in no group the last one, "Other" (:func:`karni.layout.fieldsets`).
        A field the user may not read is left out of every fieldset.
        """
        fieldsets = self._base_fieldsets(request, obj)
        if self.karni_details and not self.fieldsets:
            return self._with_details(request, obj, fieldsets)
        return fieldsets

    def _base_fieldsets(
        self, request: HttpRequest, obj: models.Model | None = None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        if not self.fieldsets:
            grouped = self.derive_fieldsets(request, obj)
            if grouped is not None:
                return grouped
        hidden = self.hidden_fields(request)
        if not hidden:
            return list(super().get_fieldsets(request, obj))
        kept = []
        for title, options in super().get_fieldsets(request, obj):
            fields = [
                n
                for n in options.get("fields", ())
                if not (isinstance(n, str) and self._head(n) in hidden)
            ]
            kept.append((title, {**options, "fields": fields}))
        return kept

    def _with_details(
        self,
        request: HttpRequest,
        obj: models.Model | None,
        fieldsets: list[tuple[str | None, dict[str, Any]]],
    ) -> list[tuple[str | None, dict[str, Any]]]:
        """Move the technical read-only fields into a collapsed *Details* fieldset.

        Ids, timestamps, who changed the row and internal keys
        (:func:`karni.admin.derive.technical_fields`) are not what a person edits.
        They leave the form's own fieldsets and, on an existing row, come last in
        *Details*, read-only and collapsed. A new row shows no *Details*.
        """
        shown = [n for _title, options in fieldsets for n in options.get("fields", ())]
        names = [n for n in shown if isinstance(n, str)]
        technical = [
            n
            for n in technical_fields(self.model, names)
            if n in set(self.get_readonly_fields(request, obj))
        ]
        if not technical:
            return fieldsets
        kept: list[tuple[str | None, dict[str, Any]]] = []
        for title, options in fieldsets:
            fields = [n for n in options.get("fields", ()) if n not in technical]
            if fields:
                kept.append((title, {**options, "fields": fields}))
        if obj is not None:
            kept.append((_("Details"), {"fields": technical, "classes": ["collapse"]}))
        return kept

    def derive_fieldsets(
        self, request: HttpRequest, obj: models.Model | None = None
    ) -> list[tuple[str | None, dict[str, Any]]] | None:
        """The fieldsets ``Karni.field_groups`` gives (experimental), or ``None`` without groups.

        A malformed declaration also gives ``None`` (Django's single fieldset):
        ``karni check`` reports it (E550 to E552). Override to group otherwise.
        """
        from karni.errorcodes import KarniError
        from karni.layout import fieldsets

        try:
            return fieldsets(self.model, self.get_fields(request, obj))
        except KarniError:
            return None

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
        form: type[ModelForm] = super().get_form(request, obj=obj, change=change, **kwargs)
        _offer_legal_states(form, self.model, obj)
        return form

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
        conflict = getattr(request, _CONFLICT_ATTR, None)
        if conflict is not None:
            self.message_user(request, str(conflict), messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        exc = getattr(request, self._DEFERRED_ATTR, None)
        if exc is None:
            return None
        self.message_user(request, str(exc), messages.INFO)
        opts = self.model._meta
        return HttpResponseRedirect(
            reverse(f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_changelist")
        )

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        """Save, unless a ``pre_write`` receiver defers the write (karni-approvals).

        A conflict the database reports while saving (a taken slot, a sold-out
        resource, a state another user just changed: ``E981`` / ``E984`` /
        ``E985``) is shown as an error on the same form; nothing is written.
        """
        try:
            super().save_model(request, obj, form, change)
        except KarniWriteDeferred as exc:
            self._defer(request, exc)
        except KarniConflict as exc:
            setattr(request, _CONFLICT_ATTR, exc)

    def save_related(self, request: HttpRequest, form: Any, formsets: Any, change: bool) -> None:
        if getattr(request, self._DEFERRED_ATTR, None) is not None:
            return  # the parent was not written; its inlines must not be either
        if getattr(request, _CONFLICT_ATTR, None) is not None:
            return
        super().save_related(request, form, formsets, change)

    def log_addition(self, request: HttpRequest, obj: Any, message: Any) -> Any:
        if getattr(request, _CONFLICT_ATTR, None) is not None:
            return None  # nothing was added
        return super().log_addition(request, obj, message)

    def log_change(self, request: HttpRequest, obj: Any, message: Any) -> Any:
        if getattr(request, _CONFLICT_ATTR, None) is not None:
            return None  # nothing was changed
        return super().log_change(request, obj, message)

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


class KarniModelAdmin(KarniAdminMixin, BulkEditAdminMixin, TransferAdminMixin, _AdminBase):  # type: ignore[valid-type, misc]
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
        per_page = getattr(meta, "per_page", None)
        if per_page is not None:
            attrs["list_per_page"] = int(per_page)
        choices = getattr(meta, "per_page_choices", None)
        if choices:
            attrs["karni_per_page_choices"] = tuple(int(n) for n in choices)
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


def _row_button(tag: str, url: str, kind: str, text: str, name: str) -> Any:
    """One button of the *Actions* column, named for its row for screen readers."""
    classes = "karni-button karni-button-sm " + (
        "karni-button-danger" if kind == "danger" else "karni-button-secondary"
    )
    label = f"{text} {name}"
    if tag == "button":
        # A POST to the row's own URL from inside the changelist form (it carries the CSRF token).
        return format_html(
            '<button type="submit" class="{}" formaction="{}" formmethod="post"'
            ' aria-label="{}">{}</button>',
            classes,
            url,
            label,
            text,
        )
    return format_html('<a class="{}" href="{}" aria-label="{}">{}</a>', classes, url, label, text)


# lifecycle columns (karni.fields.StateField)

#: Request attribute carrying a conflict raised by ``save_model`` (E981/E984/E985).
_CONFLICT_ATTR = "_karni_write_conflict"


def _offer_legal_states(form: type[ModelForm], model: type[models.Model], obj: Any) -> None:
    """Limit each StateField's select to the current state and the legal next ones.

    A new row offers its initial states. The model still checks the
    transition on save; this only keeps illegal choices out of the menu.
    """
    from karni.lifecycle import allowed_transitions, state_fields

    for state in state_fields(model):
        formfield = form.base_fields.get(state.name)
        if formfield is None or not hasattr(formfield, "choices"):
            continue
        if obj is None or obj._state.adding:
            offered = list(state.machine.initial)
        else:
            current = getattr(obj, state.attname)
            offered = [current, *allowed_transitions(obj, state.name)]
        formfield.choices = [(value, state.machine.labels.get(value, value)) for value in offered]
