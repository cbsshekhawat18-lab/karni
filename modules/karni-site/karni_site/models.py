"""What a client edits on a public site, each on ``karni.models.BaseModel``.

* :class:`SiteSettings`: the one row of the site's own details (name,
  tagline, logo, contact details, opening hours, social links, the default
  share image), ``site`` in every template. Swappable through
  ``KARNI_SITE_SETTINGS_MODEL`` for a project that needs fields of its own.
* :class:`Block`: one piece of a page's text or one of its images, stored
  the first time the template renders (``{% editable %}``,
  ``{% editable_image %}``) and edited in the admin with history.
* :class:`Menu` and :class:`MenuItem`: a named, nested list of links
  (``{% get_menu %}``), each to a page by its URL name, to a row's own page,
  or to an address, optionally with one child per row of a model.
* :class:`Redirect`: an old address and where it now goes (301 or 302).
* :class:`PageSeo`: a page's title, description, share image and ``noindex``,
  by URL name or by path (:func:`karni_site.seo.page_seo`).

The admin is this module's own ``admin.py`` (see the README). History is
``karni.audit``: every model here opts in.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from karni.fields import LiveUniqueConstraint
from karni.models import BaseModel

from karni_site import conf
from karni_site.images import validate_image

__all__ = [
    "AbstractSiteSettings",
    "Block",
    "Menu",
    "MenuItem",
    "OpeningHours",
    "PageSeo",
    "Redirect",
    "SiteSettings",
    "SocialLink",
]

#: A block key: dotted lowercase parts, the first naming the page it is grouped under.
KEY_PATTERN = r"^[a-z0-9_][a-z0-9_-]*(\.[a-z0-9_][a-z0-9_-]*)*$"
validate_key = RegexValidator(
    KEY_PATTERN,
    "A block key is lowercase words joined by dots, the page first: home.intro.",
)
IMAGE_UPLOADS = "karni_site/images/%Y/%m/"


def _digits(value: str) -> str:
    return re.sub(r"[^\d+]", "", value).lstrip("+").replace("+", "")


class AbstractSiteSettings(BaseModel):
    """The site's own details: one row, ``site`` in every template.

    ``seeded`` records the values templates gave as defaults
    (``{% site_defaults %}``): a field keeps following the template until
    someone changes it here.

    Override / escape hatch: subclass this in a project app, add fields, and
    point ``KARNI_SITE_SETTINGS_MODEL`` at the subclass before karni_site's
    first migrate. The admin, the context processor and the tags follow it.
    """

    singleton = models.BooleanField(default=True, editable=False)
    name = models.CharField(_("name"), max_length=200, blank=True)
    tagline = models.CharField(_("tagline"), max_length=300, blank=True)
    logo = models.FileField(
        _("logo"), upload_to=IMAGE_UPLOADS, blank=True, validators=[validate_image]
    )
    favicon = models.FileField(
        _("favicon"),
        upload_to=IMAGE_UPLOADS,
        blank=True,
        validators=[validate_image],
        help_text=_("The small icon browsers show in the tab. Empty: the design's own."),
    )
    share_image = models.FileField(
        _("default share image"),
        upload_to=IMAGE_UPLOADS,
        blank=True,
        validators=[validate_image],
        help_text=_("Shown when a page is shared and has no image of its own."),
    )
    address = models.TextField(_("address"), blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    phone_link = models.CharField(
        _("phone number to dial"),
        max_length=50,
        blank=True,
        help_text=_(
            "The number a tap on the phone number dials, in international form "
            "(+441234567890). Empty: the digits of the phone above."
        ),
    )
    email = models.EmailField(_("email"), blank=True)
    map_url = models.URLField(
        _("map link"), max_length=500, blank=True, help_text=_("A link to the address on a map.")
    )
    seeded = models.JSONField(default=dict, blank=True, editable=False)

    class Meta(BaseModel.Meta):
        abstract = True
        verbose_name = _("site settings")
        verbose_name_plural = _("site settings")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            LiveUniqueConstraint(fields=["singleton"])
        ]

    class Karni:
        audit = [
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
        ]

    def __str__(self) -> str:
        return self.name or str(_("Site settings"))

    @property
    def phone_href(self) -> str:
        """``tel:`` and the number to dial, or ``""`` without a phone."""
        number = self.phone_link or self.phone
        if not number:
            return ""
        digits = _digits(number)
        return f"tel:+{digits}" if number.strip().startswith("+") else f"tel:{digits}"

    @property
    def email_href(self) -> str:
        return f"mailto:{self.email}" if self.email else ""

    @property
    def address_lines(self) -> list[str]:
        return [line.strip() for line in self.address.splitlines() if line.strip()]

    @property
    def hours(self) -> list[OpeningHours]:
        """The opening hours rows, in order."""
        cached = self.__dict__.get("_karni_hours")
        if cached is None:
            cached = list(OpeningHours.objects.filter(site=self.pk)) if self.pk else []
            self.__dict__["_karni_hours"] = cached
        return list(cached)

    @property
    def social_links(self) -> list[SocialLink]:
        """The social links, in order."""
        cached = self.__dict__.get("_karni_social")
        if cached is None:
            cached = list(SocialLink.objects.filter(site=self.pk)) if self.pk else []
            self.__dict__["_karni_social"] = cached
        return list(cached)

    @property
    def social(self) -> dict[str, SocialLink]:
        """The social links by slug: ``site.social.instagram.url``."""
        return {link.slug: link for link in self.social_links}


class SiteSettings(AbstractSiteSettings):
    """The site's own details (swappable: ``KARNI_SITE_SETTINGS_MODEL``)."""

    class Meta(AbstractSiteSettings.Meta):
        swappable = "KARNI_SITE_SETTINGS_MODEL"


class OpeningHours(BaseModel):
    """One line of opening hours, written as the site shows it: "Mon to Fri", "9:00 to 17:00"."""

    site = models.ForeignKey(
        conf.get("KARNI_SITE_SETTINGS_MODEL"),
        on_delete=models.CASCADE,
        related_name="opening_hours_rows",
    )
    days = models.CharField(_("days"), max_length=100)
    times = models.CharField(_("times"), max_length=100, blank=True)
    order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["order", "created_at"]
        verbose_name = _("opening hours")
        verbose_name_plural = _("opening hours")

    class Karni:
        audit = ["days", "times", "order"]
        cascade = {"site": "a line of opening hours belongs to the site's settings"}

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"{self.days}: {self.times}" if self.times else self.days


class SocialLink(BaseModel):
    """A profile elsewhere: its name as shown ("Instagram") and its address."""

    site = models.ForeignKey(
        conf.get("KARNI_SITE_SETTINGS_MODEL"),
        on_delete=models.CASCADE,
        related_name="social_link_rows",
    )
    name = models.CharField(_("name"), max_length=50)
    url = models.URLField(_("address"), max_length=500)
    order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["order", "created_at"]
        verbose_name = _("social link")

    class Karni:
        audit = ["name", "url", "order"]
        cascade = {"site": "a social link belongs to the site's settings"}

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return self.name

    @property
    def slug(self) -> str:
        """``"instagram"`` for "Instagram": the key in ``site.social``."""
        return slugify(self.name).replace("-", "_")


class Block(BaseModel):
    """One piece of a page a client edits: text (``html``) or an image.

    The template holds the default. The first render stores it
    (``default_html``, ``default_src``, ``default_alt``), and while nobody
    has changed the block it follows the template. ``page`` is the key's
    first part, which the admin groups by. Edited HTML is cleaned on save
    (:func:`karni_site.sanitize.clean`).
    """

    class Kind(models.TextChoices):
        TEXT = "text", _("Text")
        IMAGE = "image", _("Image")

    key = models.CharField(_("key"), max_length=150, validators=[validate_key])
    page = models.CharField(_("page"), max_length=100, db_index=True, editable=False)
    kind = models.CharField(
        _("kind"), max_length=10, choices=Kind.choices, default=Kind.TEXT, editable=False
    )
    position = models.PositiveIntegerField(default=0, editable=False)
    html = models.TextField(_("text"), blank=True)
    default_html = models.TextField(_("the template's text"), blank=True, editable=False)
    image = models.FileField(
        _("image"), upload_to=IMAGE_UPLOADS, blank=True, validators=[validate_image]
    )
    alt = models.CharField(
        _("alternative text"),
        max_length=300,
        blank=True,
        help_text=_("What the image shows, for people who cannot see it."),
    )
    default_alt = models.CharField(max_length=300, blank=True, editable=False)
    default_src = models.CharField(max_length=500, blank=True, editable=False)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["page", "position", "key"]
        constraints: ClassVar[list[models.BaseConstraint]] = [LiveUniqueConstraint(fields=["key"])]
        verbose_name = _("page content")
        verbose_name_plural = _("page content")

    class Karni:
        audit = ["html", "image", "alt"]

    def __str__(self) -> str:
        return self.key

    @staticmethod
    def page_of(key: str) -> str:
        return key.split(".", 1)[0]

    @property
    def edited(self) -> bool:
        """Whether someone changed it: it no longer follows the template."""
        if self.kind == self.Kind.IMAGE:
            return bool(self.image) or self.alt != self.default_alt
        return self.html != self.default_html

    def save(self, *args: Any, **kwargs: Any) -> None:
        from karni_site.sanitize import clean

        self.page = self.page_of(self.key)
        if self.kind == self.Kind.TEXT and self.html != self.default_html:
            self.html = clean(self.html)
        super().save(*args, **kwargs)


class Menu(BaseModel):
    """A named list of links: ``{% get_menu "<name>" as items %}`` loops over it."""

    name = models.SlugField(
        _("name"), max_length=100, help_text=_("The name templates use: header, footer.")
    )
    title = models.CharField(_("title"), max_length=200, blank=True)
    seed = models.CharField(max_length=300, blank=True, editable=False)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [LiveUniqueConstraint(fields=["name"])]
        verbose_name = _("menu")

    class Karni:
        audit = ["name", "title"]

    def __str__(self) -> str:
        return self.title or self.name


class MenuItem(BaseModel):
    """One link of a menu, maybe with children.

    It points at exactly one of: a page by URL name (``route``, with
    ``route_kwargs`` for a page with a capture), a row's own page
    (``content_type`` and ``object_id``, through its ``get_absolute_url()``)
    or an address (``url``: a path, ``https://...``, ``#section``,
    ``mailto:``). ``suffix`` is added after the page's address (``#cakes``,
    ``?topic=order``). ``children_from`` adds one child per row of a model,
    so a submenu follows the rows (``KARNI_SITE_MENU_ROWS`` decides which).
    """

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name="items")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("under"),
    )
    title = models.CharField(_("title"), max_length=200, blank=True)
    route = models.CharField(_("page"), max_length=200, blank=True)
    route_kwargs = models.JSONField(default=dict, blank=True)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    object_id = models.CharField(max_length=64, blank=True)
    url = models.CharField(_("address"), max_length=500, blank=True)
    suffix = models.CharField(
        _("after the address"),
        max_length=200,
        blank=True,
        help_text=_("Added after the page's address: #section or ?key=value."),
    )
    children_from = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("children from"),
    )
    new_tab = models.BooleanField(_("opens in a new tab"), default=False)
    enabled = models.BooleanField(_("shown"), default=True)
    order = models.PositiveIntegerField(_("order"), default=0)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["order", "created_at"]
        verbose_name = _("menu item")

    class Karni:
        audit = [
            "parent",
            "title",
            "route",
            "route_kwargs",
            "content_type",
            "object_id",
            "url",
            "suffix",
            "children_from",
            "new_tab",
            "enabled",
            "order",
        ]
        cascade = {
            "menu": "a menu item is part of its menu",
            "parent": "a child item is part of its parent",
            "content_type": "an item for a model that no longer exists has nowhere to point",
        }

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return self.title or self.route or self.url or f"item {self.pk}"

    def clean(self) -> None:
        from karni_site.menus import validate_item

        super().clean()
        validate_item(self)


class Redirect(BaseModel):
    """An old address and where it now goes: 301 (moved for good) or 302 (for now).

    ``old_path`` starts at the first slash. With a query string it matches
    only that exact query, without one it matches the path with any query,
    which is passed on. A redirect that would loop is refused (``SITE006``).
    """

    class Status(models.IntegerChoices):
        PERMANENT = 301, _("Moved for good (301)")
        TEMPORARY = 302, _("Moved for now (302)")

    old_path = models.CharField(
        _("old address"),
        max_length=500,
        help_text=_("From the first slash: /old-page/. A query string makes the match exact."),
    )
    new_url = models.CharField(
        _("new address"), max_length=500, help_text=_("/new-page/ or https://...")
    )
    status = models.PositiveSmallIntegerField(
        _("kind"), choices=Status.choices, default=Status.PERMANENT
    )

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["old_path"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            LiveUniqueConstraint(fields=["old_path"])
        ]
        verbose_name = _("redirect")

    class Karni:
        audit = ["old_path", "new_url", "status"]

    def __str__(self) -> str:
        return f"{self.old_path} -> {self.new_url}"

    def clean(self) -> None:
        from karni_site.redirects import normalize_path, validate_redirect

        super().clean()
        if self.old_path:
            self.old_path = normalize_path(self.old_path)
        validate_redirect(self)

    def save(self, *args: Any, **kwargs: Any) -> None:
        from karni_site.redirects import normalize_path

        self.old_path = normalize_path(self.old_path)
        self.new_url = self.new_url.strip()
        super().save(*args, **kwargs)


class PageSeo(BaseModel):
    """A page's title, description, share image and ``noindex``: by URL name or by path.

    ``route`` (``"website:about"``) covers every page of that view, ``path``
    (``"/services/dental/"``) one address. A path entry wins over a route
    entry for its page. ``{% karni_seo %}`` reads it through
    :func:`karni_site.seo.page_seo`.
    """

    route = models.CharField(_("page"), max_length=200, blank=True)
    path = models.CharField(_("path"), max_length=500, blank=True)
    title = models.CharField(_("title"), max_length=200, blank=True)
    description = models.CharField(_("description"), max_length=500, blank=True)
    share_image = models.FileField(
        _("share image"), upload_to=IMAGE_UPLOADS, blank=True, validators=[validate_image]
    )
    noindex = models.BooleanField(
        _("hide from search engines"),
        default=False,
        help_text=_("Asks search engines not to list this page."),
    )

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["route", "path"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            LiveUniqueConstraint(fields=["route"], condition=~Q(route="")),
            LiveUniqueConstraint(fields=["path"], condition=~Q(path="")),
            models.CheckConstraint(
                condition=(Q(route="") & ~Q(path="")) | (~Q(route="") & Q(path="")),
                name="karni_site_pageseo_route_or_path",
            ),
        ]
        verbose_name = _("page title and description")
        verbose_name_plural = _("page titles and descriptions")

    class Karni:
        audit = ["route", "path", "title", "description", "share_image", "noindex"]

    def __str__(self) -> str:
        return self.route or self.path

    def clean(self) -> None:
        super().clean()
        if bool(self.route) == bool(self.path):
            raise ValidationError(_("Choose a page, or write a path, not both."))
        if self.path:
            from karni_site.redirects import normalize_path

            self.path = normalize_path(self.path, keep_query=False)
