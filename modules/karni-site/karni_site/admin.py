"""The site's content in the admin (explicit registrations, documented in the README).

* **Site settings** opens straight on the one row: name, tagline, logo,
  favicon, share image, contact details, with the opening hours and social
  links as rows below.
* **Page content** lists every block by page, in the order the page shows
  them. A text block is edited as plain text with new lines and the
  highlight marker (:func:`karni_site.sanitize.to_editing`), and saved
  cleaned. An image block takes an upload and its alternative text. The
  History tab has every change. *Reset to the template's text* hands a
  block back to the template.
* **Menus** edit their items as rows: where each goes (one of the site's
  pages, a row's page, or an address), under which item, in which order.
* **Redirects** and **Page titles and descriptions**.

These pages open for whoever the roles' grants admit (``karni.accounts``
roles, the permission matrix): the ``editor`` role this module declares
needs no Django permission ticked, only staff status. Rows still follow the
grants' scope, as everywhere in Karni's admin.

Override / escape hatch: unregister any of these and register your own
subclass (``admin.site.unregister(Block)``); ``GrantedAdminMixin`` and
``GrantedInlineMixin`` give your own admin the same grant-based access.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django import forms
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _
from karni.accounts.roles import user_can
from karni.admin import KarniModelAdmin
from karni.admin.scope import within_scope
from karni.meta import permission_key
from unfold.admin import TabularInline

from karni_site import routes
from karni_site.models import Block, Menu, MenuItem, OpeningHours, PageSeo, Redirect, SocialLink
from karni_site.sanitize import from_editing, to_editing
from karni_site.sitesettings import settings_model

__all__ = [
    "BlockAdmin",
    "GrantedAdminMixin",
    "GrantedInlineMixin",
    "MenuAdmin",
    "PageSeoAdmin",
    "RedirectAdmin",
    "SiteSettingsAdmin",
]


def _granted(request: HttpRequest, model: type[models.Model], action: str) -> bool:
    return user_can(getattr(request, "user", None), permission_key(model, action))


class GrantedAdminMixin:
    """A ``KarniModelAdmin`` whose pages open for a grant, not only a Django permission.

    A user holding ``app.model:<action>`` through a role may do that action
    here, inside the grant's scope and unless a veto refuses it. Anyone
    else falls back to Django's permissions, as in every Karni admin.
    """

    model: type[models.Model]

    def _grant(self, request: HttpRequest, action: str) -> bool:
        return _granted(request, self.model, action)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return super().has_module_permission(request) or any(  # type: ignore[misc]
            self._grant(request, action) for action in ("view", "change", "add", "delete")
        )

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if self._grant(request, "view") or self._grant(request, "change"):
            return within_scope(self, request, obj, "view") or within_scope(
                self, request, obj, "change"
            )
        return super().has_view_permission(request, obj)  # type: ignore[misc]

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if self._grant(request, "change"):
            return within_scope(self, request, obj, "change") and (
                self.vetoed(request, "change") is None  # type: ignore[attr-defined]
            )
        return super().has_change_permission(request, obj)  # type: ignore[misc]

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        if self._grant(request, "add"):
            return self.vetoed(request, "add") is None  # type: ignore[attr-defined]
        return super().has_add_permission(request, *args)  # type: ignore[misc]

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if self._grant(request, "delete"):
            return within_scope(self, request, obj, "delete") and (
                self.vetoed(request, "delete") is None  # type: ignore[attr-defined]
            )
        return super().has_delete_permission(request, obj)  # type: ignore[misc]


class GrantedInlineMixin:
    """The same for an inline: its rows open for a grant on the inline's model."""

    model: type[models.Model]

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return (
            _granted(request, self.model, "view")
            or _granted(request, self.model, "change")
            or super().has_view_permission(request, obj)  # type: ignore[misc]
        )

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return _granted(request, self.model, "add") or super().has_add_permission(  # type: ignore[misc]
            request, obj
        )

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return _granted(request, self.model, "change") or super().has_change_permission(  # type: ignore[misc]
            request, obj
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return _granted(request, self.model, "delete") or super().has_delete_permission(  # type: ignore[misc]
            request, obj
        )


#: An address typed without a scheme is https.
URL_FIELDS: dict[type[models.Field[Any, Any]], dict[str, Any]] = {
    models.URLField: {"assume_scheme": "https"}
}


class SiteAdmin(GrantedAdminMixin, KarniModelAdmin):
    """The base of this module's admins: grants open the pages, deletes go row by row."""

    karni_transfer = False
    formfield_overrides = URL_FIELDS

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        # Row by row: each soft delete is a save, which clears the cache and is history.
        for obj in queryset:
            self.delete_model(request, obj)


def _image_preview(url: str) -> str:
    if not url:
        return "-"
    return format_html(
        '<img src="{}" alt="" style="max-height: 6rem; max-width: 16rem; border-radius: 4px">',
        url,
    )


def _file_url(value: Any) -> str:
    try:
        return str(value.url) if value else ""
    except ValueError:
        return ""


# site settings


class OpeningHoursInline(GrantedInlineMixin, TabularInline):
    model = OpeningHours
    fields = ("days", "times", "order")
    extra = 0


class SocialLinkInline(GrantedInlineMixin, TabularInline):
    model = SocialLink
    formfield_overrides = URL_FIELDS
    fields = ("name", "url", "order")
    extra = 0


class SiteSettingsAdmin(SiteAdmin):
    """The one row of the site's details: the list opens it directly."""

    inlines: ClassVar[list[Any]] = [OpeningHoursInline, SocialLinkInline]
    readonly_fields = ("logo_preview", "favicon_preview", "share_image_preview")

    def get_fieldsets(self, request: HttpRequest, obj: Any = None) -> Any:
        own = {f.name for f in self.model._meta.concrete_fields if f.editable}
        known = {
            "name",
            "tagline",
            "logo",
            "favicon",
            "share_image",
            "address",
            "phone",
            "phone_link",
            "email",
            "map_url",
        }
        base = {"id", "created_at", "updated_at", "deleted_at", "created_by", "updated_by"}
        extra = sorted(own - known - base - {"singleton", "seeded"})
        fieldsets: list[tuple[Any, dict[str, Any]]] = [
            (None, {"fields": ("name", "tagline")}),
            (
                _("Images"),
                {
                    "fields": (
                        "logo",
                        "logo_preview",
                        "favicon",
                        "favicon_preview",
                        "share_image",
                        "share_image_preview",
                    )
                },
            ),
            (_("Contact"), {"fields": ("address", "phone", "phone_link", "email", "map_url")}),
        ]
        if extra:
            fieldsets.append((_("More"), {"fields": tuple(extra)}))
        return fieldsets

    def _preview(self, obj: Any, field: str) -> str:
        from karni_site.sitesettings import image_url

        url = _file_url(getattr(obj, field, None))
        if not url and obj is not None:
            url = image_url(obj, field)
        return _image_preview(url)

    @admin.display(description=_("logo shown"))
    def logo_preview(self, obj: Any) -> str:
        return self._preview(obj, "logo")

    @admin.display(description=_("favicon shown"))
    def favicon_preview(self, obj: Any) -> str:
        return self._preview(obj, "favicon")

    @admin.display(description=_("share image shown"))
    def share_image_preview(self, obj: Any) -> str:
        return self._preview(obj, "share_image")

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return not self.model._default_manager.exists() and super().has_add_permission(
            request, *args
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def changelist_view(self, request: HttpRequest, extra_context: Any = None) -> HttpResponse:
        """The list of one row is that row: open it (or the empty form)."""
        if not self.has_view_or_change_permission(request):
            return super().changelist_view(request, extra_context)
        row = self.model._default_manager.first()
        opts = self.model._meta
        name = self.admin_site.name
        if row is not None:
            url = reverse(f"{name}:{opts.app_label}_{opts.model_name}_change", args=[row.pk])
        elif self.has_add_permission(request):
            url = reverse(f"{name}:{opts.app_label}_{opts.model_name}_add")
        else:
            return super().changelist_view(request, extra_context)
        return HttpResponseRedirect(url)


# page content


class BlockForm(forms.ModelForm):
    """A text block as the text a client reads, an image block as an upload and its alt."""

    text = forms.CharField(
        label=_("text"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_(
            "A new line is a line break. Bold <b>, italic <em> and links <a href> are kept."
        ),
    )

    class Meta:
        model = Block
        fields = ("image", "alt")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["text"].initial = to_editing(self.instance.html or "")
        from karni_site.sanitize import highlight

        mark = highlight()
        if mark.marker and mark.tag:
            self.fields["text"].help_text = _(
                "A new line is a line break. Put %(marker)s around words to highlight them: "
                "%(marker)swords%(marker)s. Bold <b>, italic <em> and links <a href> are kept."
            ) % {"marker": mark.marker}

    def save(self, commit: bool = True) -> Any:
        block = self.instance
        if block.kind == Block.Kind.TEXT and "text" in self.cleaned_data:
            submitted = str(self.cleaned_data.get("text") or "")
            if submitted.strip() == to_editing(block.default_html).strip():
                block.html = block.default_html  # unchanged: it keeps following the template
            elif submitted.strip() != to_editing(block.html).strip():
                block.html = from_editing(submitted)
        return super().save(commit)


class BlockAdmin(SiteAdmin):
    """Every editable piece of the site's pages, grouped by page."""

    form = BlockForm
    list_display = ("key", "kind", "shows", "changed", "updated_at")
    list_display_links = ("key",)
    list_filter = ("page", "kind")
    search_fields = ("key", "html", "alt")
    ordering = ("page", "position", "key")
    readonly_fields = ("key", "page", "shows", "template_default")
    actions = ("reset_to_template",)

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        if obj is not None and obj.kind == Block.Kind.IMAGE:
            return ("key", "shows", "image", "alt", "template_default")
        return ("key", "text", "shows", "template_default")

    def get_fieldsets(self, request: HttpRequest, obj: Any = None) -> Any:
        return [(None, {"fields": self.get_fields(request, obj)})]

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return False  # a block comes from a template's {% editable %}

    @admin.display(description=_("shows"))
    def shows(self, obj: Block) -> str:
        if obj.kind == Block.Kind.IMAGE:
            return _image_preview(_file_url(obj.image) or obj.default_src)
        from html import unescape

        from django.utils.html import strip_tags

        return Truncator(unescape(strip_tags(obj.html))).chars(90)

    @admin.display(description=_("the template's version"))
    def template_default(self, obj: Block) -> str:
        if obj.kind == Block.Kind.IMAGE:
            return format_html("{}<br>{}", _image_preview(obj.default_src), obj.default_alt)
        return to_editing(obj.default_html)

    @admin.display(description=_("changed"), boolean=True)
    def changed(self, obj: Block) -> bool:
        return obj.edited

    @admin.action(description=_("Reset to the template's text or image"), permissions=["change"])
    def reset_to_template(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        count = 0
        for block in queryset:
            if not block.edited:
                continue
            block.html, block.alt = block.default_html, block.default_alt
            block.image = ""
            block.save()
            count += 1
        self.message_user(
            request,
            _("%(count)d block(s) follow the template again.") % {"count": count},
            messages.SUCCESS,
        )


# menus


def _target_choices() -> list[Any]:
    pages = [(f"route:{name}", f"{path}  ({name})") for name, path in routes.site_pages()]
    choices: list[Any] = [("", "---------"), (str(_("Pages")), pages)]
    for model in routes.linkable_models():
        content_type = ContentType.objects.get_for_model(model)
        rows = [
            (f"object:{content_type.pk}:{row.pk}", str(row))
            for row in model._default_manager.all()[:200]
        ]
        if rows:
            choices.append((str(model._meta.verbose_name_plural).capitalize(), rows))
    choices.append(("url", _("The address below")))
    return choices


def _model_choices() -> list[tuple[str, str]]:
    return [("", "---------")] + [
        (
            str(ContentType.objects.get_for_model(model).pk),
            str(model._meta.verbose_name_plural).capitalize(),
        )
        for model in routes.linkable_models()
    ]


class MenuItemForm(forms.ModelForm):
    """One menu row: a single "goes to" choice instead of four fields."""

    goes_to = forms.ChoiceField(label=_("goes to"), required=False)
    children = forms.ChoiceField(
        label=_("children from"),
        required=False,
        help_text=_("Adds one item per row, kept in step with the rows."),
    )

    class Meta:
        model = MenuItem
        fields = ("title", "parent", "url", "suffix", "new_tab", "enabled", "order")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        choices = list(getattr(self, "target_choices", None) or _target_choices())
        item = self.instance
        current = ""
        if item.route:
            current = f"route:{item.route}"
            known = {value for group in choices[1:2] for value, _label in group[1]}
            if current not in known:
                choices.insert(1, (current, item.route))
        elif item.content_type_id and item.object_id:
            current = f"object:{item.content_type_id}:{item.object_id}"
        elif item.url:
            current = "url"
        self.fields["goes_to"].choices = choices
        self.fields["goes_to"].initial = current
        self.fields["children"].choices = list(
            getattr(self, "model_choices", None) or _model_choices()
        )
        self.fields["children"].initial = (
            str(item.children_from_id) if item.children_from_id else ""
        )

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        item = self.instance
        goes_to = str(data.get("goes_to") or "")
        item.route, item.route_kwargs = "", {}
        item.content_type, item.object_id = None, ""
        if goes_to.startswith("route:"):
            item.route = goes_to.removeprefix("route:")
            data["url"] = ""
        elif goes_to.startswith("object:"):
            _kind, content_type, object_id = goes_to.split(":", 2)
            item.content_type = ContentType.objects.get_for_id(int(content_type))
            item.object_id = object_id
            data["url"] = ""
        children = str(data.get("children") or "")
        item.children_from = ContentType.objects.get_for_id(int(children)) if children else None
        return data


class MenuItemInline(GrantedInlineMixin, TabularInline):
    model = MenuItem
    form = MenuItemForm
    fields = (
        "title",
        "goes_to",
        "url",
        "suffix",
        "parent",
        "children",
        "order",
        "new_tab",
        "enabled",
    )
    extra = 0
    fk_name = "menu"

    def get_formset(self, request: HttpRequest, obj: Any = None, **kwargs: Any) -> Any:
        self._menu = obj
        formset = super().get_formset(request, obj, **kwargs)
        # The choices once per page, not once per row.
        formset.form = type(
            "MenuItemRowForm",
            (formset.form,),
            {"target_choices": _target_choices(), "model_choices": _model_choices()},
        )
        return formset

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: Any
    ) -> Any:
        if db_field.name == "parent":
            menu = getattr(self, "_menu", None)
            kwargs["queryset"] = (
                MenuItem.objects.filter(menu=menu) if menu is not None else MenuItem.objects.none()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class MenuAdmin(SiteAdmin):
    """A menu and its items, edited together."""

    list_display = ("name", "title", "item_count", "updated_at")
    search_fields = ("name", "title")
    fields = ("name", "title")
    inlines: ClassVar[list[Any]] = [MenuItemInline]

    @admin.display(description=_("items"))
    def item_count(self, obj: Menu) -> int:
        return obj.items.count()


# redirects and page SEO


class RedirectAdmin(SiteAdmin):
    list_display = ("old_path", "new_url", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("old_path", "new_url")
    fields = ("old_path", "new_url", "status")


class PageSeoForm(forms.ModelForm):
    route = forms.ChoiceField(label=_("page"), required=False)

    class Meta:
        model = PageSeo
        fields = ("route", "path", "title", "description", "share_image", "noindex")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        choices: list[tuple[str, str]] = [("", "---------")] + [
            (name, f"{path}  ({name})") for name, path in routes.site_pages()
        ]
        current = self.instance.route
        if current and current not in {value for value, _label in choices}:
            choices.append((current, current))
        self.fields["route"].choices = choices
        self.fields["path"].help_text = _("Or one address, from the first slash: /services/web/.")


class PageSeoAdmin(SiteAdmin):
    form = PageSeoForm
    list_display = ("__str__", "title", "noindex", "updated_at")
    list_filter = ("noindex",)
    search_fields = ("route", "path", "title", "description")
    fields = ("route", "path", "title", "description", "share_image", "noindex")


admin.site.register(settings_model(), SiteSettingsAdmin)
admin.site.register(Block, BlockAdmin)
admin.site.register(Menu, MenuAdmin)
admin.site.register(Redirect, RedirectAdmin)
admin.site.register(PageSeo, PageSeoAdmin)
