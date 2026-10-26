"""karni-site's error codes (prefix ``SITE``), registered with Karni's registry."""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_site"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="SITE001",
        title="Templates do not get the request",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "{% ifactive %} reads the current page from the request, and {% csp_hash %} and "
            "{% csp_allow %} add to the request's Content-Security-Policy. Without "
            "django.template.context_processors.request in the template engine's "
            "context_processors, no menu item is ever current and the design's inline "
            "scripts are blocked in production."
        ),
        fix=(
            "Add 'django.template.context_processors.request' to "
            "TEMPLATES[0]['OPTIONS']['context_processors'] in config/settings.py "
            "(karni_settings() includes it unless the project replaced TEMPLATES)."
        ),
    ),
    ErrorCode(
        code="SITE002",
        title="{% ifactive %} names a URL the project does not have",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "A menu item marks itself current when the request resolved to one of the URL "
            "names in its {% ifactive %}. A name that no URL pattern has, after a view was "
            "renamed or removed, never matches, so the item is never marked and nothing fails."
        ),
        fix=(
            "Use the name `karni routes` lists for that page (`<app>:<name>`), or remove the "
            "name from the tag."
        ),
    ),
    ErrorCode(
        code="SITE003",
        title="A karni_site template tag is written wrongly",
        kind="exception",
        source=f"{_SOURCE}.templatetags.karni_site",
        why=(
            "{% ifactive %} needs at least one URL name or path. {% csp_hash %} takes nothing, "
            "or `attribute`. {% csp_allow %} takes arguments like "
            '"font-src https://fonts.gstatic.com". {% editable %} and {% editable_image %} '
            'take a block key ("home.intro": lowercase words joined by dots, the page first), '
            "{% site_image %} a file field of the site's settings, {% site_defaults %} "
            'name="value" pairs, and {% get_menu %} a name and `as <variable>`. The template '
            "does not compile otherwise."
        ),
        fix="Write the tag as the message shows. The karni-site README has an example of each.",
    ),
    ErrorCode(
        code="SITE004",
        title="Templates do not get `site`",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "`site` (the site's name, logo, contact details, opening hours and social links, "
            "edited in the admin) reaches templates through the context processor "
            "karni_site.context_processors.site. Without it every {{ site.<field> }} renders "
            "empty and nothing fails."
        ),
        fix=(
            "Add 'karni_site.context_processors.site' to "
            "TEMPLATES[0]['OPTIONS']['context_processors'] in config/settings.py. "
            "`karni make site <app>` adds it."
        ),
    ),
    ErrorCode(
        code="SITE005",
        title="The redirect middleware is not installed",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "Redirects a client adds in the admin are answered by "
            "karni_site.middleware.RedirectMiddleware. Without it they are stored and never "
            "used, and the old addresses answer 404."
        ),
        fix=(
            "Add 'karni_site.middleware.RedirectMiddleware' to the `# karni:middleware` block "
            "of config/settings.py. `karni make site <app>` adds it."
        ),
    ),
    ErrorCode(
        code="SITE006",
        title="A redirect would send visitors in a circle",
        kind="exception",
        source=f"{_SOURCE}.redirects",
        why=(
            "The new address of a redirect is itself redirected, through one redirect or "
            "several, back to the old address. A browser would follow the chain until it "
            "gives up, so the page could never be reached."
        ),
        fix=(
            "Point the redirect at the page's final address, or remove the redirect that "
            "leads back. The message lists the chain."
        ),
    ),
    ErrorCode(
        code="SITE007",
        title="A menu item does not point at a page",
        kind="exception",
        source=f"{_SOURCE}.menus",
        why=(
            "A menu item goes to exactly one place: one of the site's pages by URL name, a "
            "row's own page (its get_absolute_url), or an address. An item with none of them "
            "(and no children from a model), with a URL name no route has, with a row that no "
            "longer exists, with an address such as javascript:, or under itself, would render "
            "a broken link."
        ),
        fix=(
            "Choose where the item goes in the admin (or set route, content_type and "
            "object_id, or url), and pick a parent from the same menu."
        ),
    ),
    ErrorCode(
        code="SITE008",
        title="One block key has two different defaults",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "A block is stored once per key. While nobody has edited it, it follows its "
            "template's default, so a key written with one default in one template and another "
            "default elsewhere (or used for text in one place and an image in another) would "
            "be stored again on every render and show the other place's text."
        ),
        fix=(
            "Give each place its own key (`karni import design --editable` does), or the same "
            "default in both when the text is meant to be shared."
        ),
    ),
    ErrorCode(
        code="SITE009",
        title="KARNI_SITE_SETTINGS_MODEL names no installed model",
        kind="exception",
        source=f"{_SOURCE}.sitesettings",
        why=(
            "`site`, the admin's site settings and the editor role read the model "
            "KARNI_SITE_SETTINGS_MODEL names. A label that is not an installed model (a typo, "
            "an app missing from INSTALLED_APPS) leaves them nothing to read."
        ),
        fix=(
            "Set it to 'app_label.ModelName' of a model that subclasses "
            "karni_site.models.AbstractSiteSettings and whose app is installed, or remove it "
            "for karni_site.SiteSettings."
        ),
    ),
)
