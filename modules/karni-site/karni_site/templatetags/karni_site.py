"""Template tags for a public site: ``{% load karni_site %}``.

``{% ifactive "website:about" %} class="active"{% endifactive %}``
    Renders its content when one of the patterns names the current page, and
    the ``{% else %}`` part otherwise. A pattern is a URL name
    (``"website:about"``, wildcards allowed: ``"website:service_*"``) or a
    path (``"/about/"``, ``"/services/*"``). The tag knows nothing about the
    markup, so it works with any design: put it where the design marks the
    current page, around a class (``class="nav-link{% ifactive ... %}
    active{% endifactive %}"``) or a whole attribute (``{% ifactive ... %}
    aria-current="page"{% endifactive %}``). It needs the ``request`` in the
    context. Without one (an e-mail, a plain ``Template.render``) nothing is
    active.

``<script>{% csp_hash %}...{% endcsp_hash %}</script>``
    Renders its content unchanged and adds the content's SHA-256 hash to the
    ``script-src`` of the Content-Security-Policy of this response only
    (``karni.security.extend_request_csp``). The design's inline script runs
    under Karni's policy, and an edited script is hashed again on the next
    render. ``{% csp_hash attribute %}`` is for an event handler attribute
    (``onclick="{% csp_hash attribute %}...{% endcsp_hash %}"``): it adds
    ``'unsafe-hashes'`` and the hash of the attribute's decoded value.

``{% csp_allow "style-src https://fonts.googleapis.com" "font-src https://fonts.gstatic.com" %}``
    Adds sources to the policy of this response only, one directive per
    argument. A template that loads something from another origin says so
    next to the markup that loads it. It renders nothing.

``{% editable "home.intro" %}<default HTML>{% endeditable %}``
    Text a client edits in the admin. The content is the default: the first
    render stores it under the key, and while nobody changes it the block
    follows the template. An edited block shows the edited HTML, cleaned to
    the inline markup ``KARNI_SITE_INLINE_TAGS`` allows. The key's first part
    is the page the admin groups it under (:mod:`karni_site.blocks`).

``{% editable_image "home.hero" %}<img src="..." alt="...">{% endeditable_image %}``
    An image a client replaces. The design's markup stays: an uploaded
    picture changes the ``<img>``'s ``src`` (and ``srcset`` and ``<source>``
    go), an edited alternative text its ``alt``. ``{% editable_image "key"
    url %}{% static '...' %}{% endeditable_image %}`` holds a bare address,
    for a ``style="background-image: url(...)"``.

``{% site_image "logo" %}<img ...>{% endsite_image %}``
    The same, from a file field of the site's settings (``logo``,
    ``favicon``, ``share_image``): the design's image until one is uploaded.

``{% site_defaults name="Crumb & Co" phone="01234 567890" social_instagram="https://..." %}``
    The design's values for the site's details: stored the first time,
    followed until someone changes them in the admin. Renders nothing. Put
    it at the top of the layout, before anything reads ``site``.

``{% get_menu "header" as items %}`` (``seed="<template>"`` optional)
    The items of a menu for a ``{% for %}`` loop that keeps the design's
    markup: ``item.title``, ``item.url``, ``item.new_tab``, ``item.current``
    (this page), ``item.active`` (this page or one under it),
    ``item.children``. With ``seed``, a menu the database does not have yet
    is created from the links in that template (:mod:`karni_site.menus`).

Override / escape hatch: ``KARNI_SITE_IS_ACTIVE`` replaces the rule that
decides the current page. ``KARNI_CSP`` adds sources site-wide instead of
per response, and ``@csp_extend`` per view. ``KARNI_SITE_SANITIZER``,
``KARNI_SITE_INLINE_TAGS`` and ``KARNI_SITE_HIGHLIGHT`` decide what an edited
block keeps, and ``KARNI_SITE_SEED_ON_RENDER = False`` stores nothing while
a page renders.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any

from django import template
from django.template import Engine
from django.template.base import FilterExpression, Node, NodeList, Parser, Token
from django.template.context import Context
from django.utils.safestring import SafeString, mark_safe
from karni.errorcodes import docs_url
from karni.security import extend_request_csp, script_hash

from karni_site import blocks, menus, sitesettings
from karni_site.navigation import any_active

register = template.Library()

_DIRECTIVE = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
SYNTAX_CODE = "SITE003"


def _syntax_error(message: str) -> template.TemplateSyntaxError:
    return template.TemplateSyntaxError(f"{SYNTAX_CODE}: {message} See {docs_url(SYNTAX_CODE)}")


def _request(context: Context) -> Any:
    request = getattr(context, "request", None)
    return request if request is not None else context.get("request")


def _flatten(values: Iterable[Any]) -> list[str]:
    found: list[str] = []
    for value in values:
        if isinstance(value, list | tuple | set | frozenset):
            found.extend(str(item) for item in value)
        elif value is not None and value != "":
            found.append(str(value))
    return found


# {% ifactive %}


class IfActiveNode(Node):
    child_nodelists = ("nodelist_true", "nodelist_false")

    def __init__(
        self, patterns: list[FilterExpression], nodelist_true: NodeList, nodelist_false: NodeList
    ) -> None:
        self.patterns = patterns
        self.nodelist_true = nodelist_true
        self.nodelist_false = nodelist_false

    def render(self, context: Context) -> str:
        patterns = _flatten(pattern.resolve(context) for pattern in self.patterns)
        if any_active(_request(context), patterns):
            return str(self.nodelist_true.render(context))
        return str(self.nodelist_false.render(context))


@register.tag("ifactive")
def do_ifactive(parser: Parser, token: Token) -> IfActiveNode:
    """``{% ifactive "app:name" "/path/*" ... %}...{% else %}...{% endifactive %}``."""
    bits = token.split_contents()
    if len(bits) < 2:
        raise _syntax_error(
            "{% ifactive %} needs at least one URL name or path, for example "
            '{% ifactive "website:about" %} class="active"{% endifactive %}.'
        )
    patterns = [parser.compile_filter(bit) for bit in bits[1:]]
    nodelist_true = parser.parse(("else", "endifactive"))
    next_token = parser.next_token()
    if next_token.contents == "else":
        nodelist_false = parser.parse(("endifactive",))
        parser.delete_first_token()
    else:
        nodelist_false = NodeList()
    return IfActiveNode(patterns, nodelist_true, nodelist_false)


# {% csp_hash %}


def inline_source(text: str, *, attribute: bool = False) -> str:
    """What the browser hashes: the script's text, or an attribute's decoded value.

    Browsers turn CR LF and CR into LF before they parse, so the hash is of that.
    """
    source = html.unescape(text) if attribute else text
    return source.replace("\r\n", "\n").replace("\r", "\n")


class CspHashNode(Node):
    child_nodelists = ("nodelist",)

    def __init__(self, nodelist: NodeList, *, attribute: bool) -> None:
        self.nodelist = nodelist
        self.attribute = attribute

    def render(self, context: Context) -> str:
        text = str(self.nodelist.render(context))
        request = _request(context)
        if request is not None:
            sources = [script_hash(inline_source(text, attribute=self.attribute))]
            if self.attribute:
                sources.insert(0, "'unsafe-hashes'")
            extend_request_csp(request, {"script-src": sources})
        return text


@register.tag("csp_hash")
def do_csp_hash(parser: Parser, token: Token) -> CspHashNode:
    """``{% csp_hash %}<inline script>{% endcsp_hash %}``, or ``{% csp_hash attribute %}``."""
    bits = token.split_contents()
    if len(bits) > 2 or (len(bits) == 2 and bits[1] != "attribute"):
        raise _syntax_error(
            "{% csp_hash %} takes nothing, or `attribute` for an event handler attribute: "
            '<script>{% csp_hash %}...{% endcsp_hash %}</script> or onclick="{% csp_hash '
            'attribute %}...{% endcsp_hash %}".'
        )
    nodelist = parser.parse(("endcsp_hash",))
    parser.delete_first_token()
    return CspHashNode(nodelist, attribute=len(bits) == 2)


# {% csp_allow %}


def parse_spec(spec: str) -> tuple[str, list[str]]:
    """``"font-src https://fonts.gstatic.com"`` as ``("font-src", ["https://..."])``."""
    name, *sources = str(spec).split()
    if not _DIRECTIVE.match(name) or not sources:
        raise _syntax_error(
            f"{{% csp_allow %}} takes a directive and its sources in each argument, such as "
            f'"font-src https://fonts.gstatic.com". Got {spec!r}.'
        )
    return name, sources


class CspAllowNode(Node):
    def __init__(self, specs: list[FilterExpression]) -> None:
        self.specs = specs

    def render(self, context: Context) -> str:
        request = _request(context)
        if request is None:
            return ""
        directives: dict[str, list[str]] = {}
        for spec in _flatten(expression.resolve(context) for expression in self.specs):
            name, sources = parse_spec(spec)
            directives.setdefault(name, []).extend(sources)
        if directives:
            extend_request_csp(request, directives)
        return ""


@register.tag("csp_allow")
def do_csp_allow(parser: Parser, token: Token) -> CspAllowNode:
    """``{% csp_allow "<directive> <source> ..." ... %}``: sources for this response."""
    bits = token.split_contents()[1:]
    if not bits:
        raise _syntax_error(
            '{% csp_allow %} needs at least one "<directive> <source>" argument, such as '
            '"font-src https://fonts.gstatic.com".'
        )
    for bit in bits:
        if bit[:1] in "\"'" and bit[-1:] == bit[:1]:
            parse_spec(bit[1:-1])  # a literal: wrong here is wrong on every render
    return CspAllowNode([parser.compile_filter(bit) for bit in bits])


# {% editable %} and {% editable_image %}

_KEY = re.compile(r"^[a-z0-9_][a-z0-9_-]*(\.[a-z0-9_][a-z0-9_-]*)*$")


def _literal(bit: str) -> str | None:
    if len(bit) >= 2 and bit[0] in "\"'" and bit[-1] == bit[0]:
        return bit[1:-1]
    return None


def _key_expression(parser: Parser, tag: str, bit: str) -> FilterExpression:
    literal = _literal(bit)
    if literal is not None and not _KEY.match(literal):
        raise _syntax_error(
            f"{{% {tag} %}} key {literal!r} is not a block key: lowercase words joined by "
            'dots, the page first, such as "home.intro" or "footer.opening_hours".'
        )
    return parser.compile_filter(bit)


def _resolved_key(expression: FilterExpression, context: Context, tag: str) -> str:
    key = str(expression.resolve(context) or "")
    if not _KEY.match(key):
        raise _syntax_error(f"{{% {tag} %}} got {key!r}, which is not a block key.")
    return key


class EditableNode(Node):
    child_nodelists = ("nodelist",)

    def __init__(self, key: FilterExpression, nodelist: NodeList) -> None:
        self.key = key
        self.nodelist = nodelist

    def render(self, context: Context) -> SafeString:
        key = _resolved_key(self.key, context, "editable")
        default = str(self.nodelist.render(context))
        return mark_safe(blocks.text(key, default, _request(context)))  # noqa: S308 - template default or cleaned HTML


@register.tag("editable")
def do_editable(parser: Parser, token: Token) -> EditableNode:
    """``{% editable "<page>.<name>" %}<default HTML>{% endeditable %}``."""
    bits = token.split_contents()
    if len(bits) != 2:
        raise _syntax_error(
            '{% editable %} takes one key: {% editable "home.intro" %}Welcome.{% endeditable %}.'
        )
    key = _key_expression(parser, "editable", bits[1])
    nodelist = parser.parse(("endeditable",))
    parser.delete_first_token()
    return EditableNode(key, nodelist)


class EditableImageNode(Node):
    child_nodelists = ("nodelist",)

    def __init__(self, key: FilterExpression, nodelist: NodeList, *, url: bool) -> None:
        self.key = key
        self.nodelist = nodelist
        self.url = url

    def render(self, context: Context) -> SafeString:
        key = _resolved_key(self.key, context, "editable_image")
        default = str(self.nodelist.render(context))
        return mark_safe(blocks.image(key, default, _request(context), url=self.url))  # noqa: S308 - the design's markup with an escaped address


def _image_bits(tag: str, bits: list[str]) -> bool:
    if len(bits) == 2:
        return False
    if len(bits) == 3 and bits[2] == "url":
        return True
    raise _syntax_error(
        f'{{% {tag} %}} takes a name and maybe `url`: {{% {tag} "home.hero" %}}<img ...>'
        f'{{% end{tag} %}}, or {{% {tag} "home.hero" url %}}<address>{{% end{tag} %}}.'
    )


@register.tag("editable_image")
def do_editable_image(parser: Parser, token: Token) -> EditableImageNode:
    """``{% editable_image "<page>.<name>" [url] %}<img ...>{% endeditable_image %}``."""
    bits = token.split_contents()
    url = _image_bits("editable_image", bits)
    key = _key_expression(parser, "editable_image", bits[1])
    nodelist = parser.parse(("endeditable_image",))
    parser.delete_first_token()
    return EditableImageNode(key, nodelist, url=url)


# the site's settings: {% site_image %} and {% site_defaults %}


def _site(context: Context) -> Any:
    found = context.get("site")
    return found if found is not None and found != "" else sitesettings.get_site_settings()


def _file_fields() -> set[str]:
    from django.db import models

    model = sitesettings.settings_model()
    return {f.name for f in model._meta.get_fields() if isinstance(f, models.FileField)}


class SiteImageNode(Node):
    child_nodelists = ("nodelist",)

    def __init__(self, field: str, nodelist: NodeList, *, url: bool) -> None:
        self.field = field
        self.nodelist = nodelist
        self.url = url

    def render(self, context: Context) -> SafeString:
        from karni_site.images import img_attributes, replace_image

        default = str(self.nodelist.render(context))
        site = _site(context)
        src = default.strip() if self.url else img_attributes(default).get("src", "")
        recorded = ((getattr(site, "seeded", None) or {}).get("images") or {}).get(self.field)
        if src and recorded != src:
            fresh = sitesettings.seed({"images": {self.field: src}})
            if fresh is not None:
                site = _replace_site(context, fresh)
        stored = getattr(site, self.field, None)
        try:
            address = stored.url if stored else ""
        except ValueError:
            address = ""
        if not address:
            return mark_safe(default)  # noqa: S308 - the design's own markup
        if self.url:
            return mark_safe(html.escape(address))  # noqa: S308 - escaped
        return mark_safe(replace_image(default, address))  # noqa: S308 - escaped address


@register.tag("site_image")
def do_site_image(parser: Parser, token: Token) -> SiteImageNode:
    """``{% site_image "logo" [url] %}<img ...>{% endsite_image %}``."""
    bits = token.split_contents()
    url = _image_bits("site_image", bits)
    field = _literal(bits[1])
    fields = _file_fields()
    if field is None or field not in fields:
        raise _syntax_error(
            f"{{% site_image %}} names a file field of the site's settings in quotes, one of "
            f"{', '.join(sorted(fields))}. Got {bits[1]}."
        )
    nodelist = parser.parse(("endsite_image",))
    parser.delete_first_token()
    return SiteImageNode(field, nodelist, url=url)


def _replace_site(context: Context, row: Any) -> Any:
    from karni_site.context_processors import SiteProxy

    current = context.get("site")
    if isinstance(current, SiteProxy):
        current.replace(row)
    else:
        context["site"] = row
    return row


class SiteDefaultsNode(Node):
    def __init__(self, values: dict[str, FilterExpression]) -> None:
        self.values = values

    def render(self, context: Context) -> str:
        defaults = {
            name: str(expression.resolve(context) or "") for name, expression in self.values.items()
        }
        fresh = sitesettings.seed(defaults)
        if fresh is not None:
            _replace_site(context, fresh)
        return ""


@register.tag("site_defaults")
def do_site_defaults(parser: Parser, token: Token) -> SiteDefaultsNode:
    """``{% site_defaults name="..." phone="..." social_<network>="https://..." %}``."""
    from django.template.base import kwarg_re

    values: dict[str, FilterExpression] = {}
    for bit in token.split_contents()[1:]:
        match = kwarg_re.match(bit)
        name = match.group(1) if match else None
        if not name or (name not in sitesettings.SEEDABLE and not name.startswith("social_")):
            raise _syntax_error(
                "{% site_defaults %} takes name=value pairs for "
                f"{', '.join(sitesettings.SEEDABLE)}, or social_<network>=<address>. Got {bit}."
            )
        values[name] = parser.compile_filter(bit.split("=", 1)[1])
    if not values:
        raise _syntax_error('{% site_defaults %} needs at least one value: name="..."')
    return SiteDefaultsNode(values)


# {% get_menu %}


class GetMenuNode(Node):
    def __init__(
        self, name: FilterExpression, seed: FilterExpression | None, variable: str
    ) -> None:
        self.name = name
        self.seed = seed
        self.variable = variable

    def render(self, context: Context) -> str:
        name = str(self.name.resolve(context) or "")
        seed_path = str(self.seed.resolve(context) or "") if self.seed is not None else ""

        def seed() -> str:
            engine = (
                context.template.engine if context.template is not None else Engine.get_default()
            )
            template = engine.get_template(seed_path)
            with context.push():
                return str(template.render(context))

        context[self.variable] = menus.entries(
            name, _request(context), seed if seed_path else None, source=seed_path
        )
        return ""


@register.tag("get_menu")
def do_get_menu(parser: Parser, token: Token) -> GetMenuNode:
    """``{% get_menu "<name>" [seed="<template>"] as <variable> %}``."""
    bits = token.split_contents()
    usage = (
        '{% get_menu %} is written {% get_menu "header" as items %}, or with a seed template: '
        '{% get_menu "header" seed="website/menus/header.html" as items %}.'
    )
    if len(bits) not in (4, 5) or bits[-2] != "as":
        raise _syntax_error(usage)
    seed: FilterExpression | None = None
    if len(bits) == 5:
        if not bits[2].startswith("seed="):
            raise _syntax_error(usage)
        seed = parser.compile_filter(bits[2].removeprefix("seed="))
    return GetMenuNode(parser.compile_filter(bits[1]), seed, bits[-1])


# {% karni_form %}: public forms. The tag lives in karni_site.templatetags.karni_forms and is
# part of this library too, so one {% load karni_site %} gives a page every site tag.

from karni_site.templatetags.karni_forms import register as _forms  # noqa: E402

register.tags.update(_forms.tags)
