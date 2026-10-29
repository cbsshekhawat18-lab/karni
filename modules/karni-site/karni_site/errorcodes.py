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

#: SEO and images (SITE010 to SITE019): `karni check --seo`, {% karni_seo %}, {% image %} and
#: the sitemap.
SEO_CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="SITE010",
        title="A page has no title",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "Search results and browser tabs show a page's <title>. A page without one, or with "
            "an empty one, is listed under its address or a title the search engine makes up."
        ),
        fix=(
            "Give the page a title: {% block title %} in its template, the title of its row "
            "(class Karni: seo), or its entry in the admin's Page titles and descriptions. "
            "base.html needs {% karni_seo %} around its <title>."
        ),
    ),
    ErrorCode(
        code="SITE011",
        title="Two pages have the same title",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "Search engines treat pages with the same title as copies of one another and may "
            "show only one. Visitors cannot tell the results apart either. It usually means a "
            "template's title was written once for every page of a kind."
        ),
        fix=(
            "Give each page its own title. For pages of one view, let the row name it "
            '(class Karni: seo = {"title": "name"}, or {% block title %}{{ object.title }}'
            "{% endblock %}), or set it per page in the admin."
        ),
    ),
    ErrorCode(
        code="SITE012",
        title="A page has no description",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            'Search results show the <meta name="description"> under the title. Without one '
            "the search engine picks a fragment of the page, often the menu or a cookie notice."
        ),
        fix=(
            "Write one sentence about the page: {% block description %} in its template, the "
            'description of its row (class Karni: seo = {"description": "summary"}), its entry '
            "in the admin, or the site's tagline as the last default."
        ),
    ),
    ErrorCode(
        code="SITE013",
        title="Two pages have the same description",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "A description shared by several pages says nothing about any one of them, and "
            "search engines may ignore it. A detail page that repeats its card's text, or a "
            "layout's default left in place, is the usual cause."
        ),
        fix=(
            "Write a description per page, or let each row give its own "
            '(class Karni: seo = {"description": "intro"}).'
        ),
    ),
    ErrorCode(
        code="SITE014",
        title="An image has no alt text",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "Screen readers read an image's alt text, and search engines index it. An <img> "
            "without an alt attribute is announced by its file name."
        ),
        fix=(
            'Describe the image in alt="...", or write alt="" when it only decorates. '
            "{% image %} requires alt, and an image a client uploads takes its alt text in "
            "the admin."
        ),
    ),
    ErrorCode(
        code="SITE015",
        title="An image has no width and height",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "Without width and height the browser does not know how much room an image takes "
            "until it loads, so the text below it jumps when it does (layout shift, which "
            "search engines measure)."
        ),
        fix=(
            "Render uploaded images with {% image %}, which writes both. For a design's own "
            "image, write its pixel width and height (karni import design does). CSS still "
            "sizes it: {% karni_seo %} keeps such images in proportion."
        ),
    ),
    ErrorCode(
        code="SITE016",
        title="An image is much larger than the page shows it",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "A visitor downloads every pixel of an image, however small the page shows it. A "
            "photo thousands of pixels wide in a small card makes the page slow on a phone, "
            "and page speed counts in search rankings."
        ),
        fix=(
            "Give it smaller copies: {% image %} for uploads (with Pillow installed, "
            "pip install karni-site[images], and a Celery worker running), a srcset for a "
            "design's image (karni import design writes one when Pillow is installed where "
            "karni runs), or a smaller file. KARNI_SITE_SEO_IMAGE_BYTES and "
            "KARNI_SITE_SEO_PIXEL_RATIO set the limits."
        ),
    ),
    ErrorCode(
        code="SITE017",
        title="A link on the site leads nowhere",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "A link, image, stylesheet or script on one of the site's own pages points at an "
            "address that answers an error. Visitors land on a dead end, and search engines "
            "count broken links against the site."
        ),
        fix=(
            "Point it at a page that exists ({% url %} for the site's pages, {% static %} for "
            "its files), add a redirect for an address that moved, or remove it."
        ),
    ),
    ErrorCode(
        code="SITE018",
        title="The sitemap and the site's pages disagree",
        kind="check",
        source=f"{_SOURCE}.checks_seo",
        why=(
            "sitemap.xml tells search engines which pages exist. A page the site links to that "
            "the sitemap leaves out is found late or not at all, and an address in the sitemap "
            "that does not answer 200 (or asks not to be indexed) wastes the crawl."
        ),
        fix=(
            'Include karni_site\'s URLs (path("", include("karni_site.urls")) in config/urls.py, '
            "which karni make site writes). Give a model's rows get_absolute_url() and the "
            "public filter they need (class Karni: sitemap), and leave out an address that is "
            "not a page with KARNI_SITE_SITEMAP_EXCLUDE."
        ),
    ),
    ErrorCode(
        code="SITE019",
        title="An SEO tag or declaration is written wrongly",
        kind="exception",
        source=f"{_SOURCE}.seo_tags",
        why=(
            "{% karni_seo %} takes nothing and ends with {% endkarni_seo %}. {% image %} takes "
            "the image, then name=value pairs, alt among them. class Karni: sitemap is True, "
            "False or a dict of filter, exclude, lastmod, changefreq and priority, on a model "
            "with get_absolute_url(). class Karni: seo maps title, description, image and type "
            "to fields."
        ),
        fix="Write it as the message shows. The karni-site README has an example of each.",
    ),
)

CODES = (*CODES, *SEO_CODES)  # type: ignore[misc]  # CODES is Final: extended once, here
