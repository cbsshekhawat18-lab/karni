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

Override / escape hatch: ``KARNI_SITE_IS_ACTIVE`` replaces the rule that
decides the current page. ``KARNI_CSP`` adds sources site-wide instead of
per response, and ``@csp_extend`` per view.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any

from django import template
from django.template.base import FilterExpression, Node, NodeList, Parser, Token
from django.template.context import Context
from karni.errorcodes import docs_url
from karni.exceptions import KarniValueError
from karni.security import extend_request_csp, script_hash

from karni_site.navigation import any_active
from karni_site.text import highlight

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


@register.filter("highlight")
def highlight_filter(value: Any, spec: str = "em") -> str:
    """``{{ heading|highlight:"span.accent" }}``: ``*marked*`` words in the design's markup.

    See :mod:`karni_site.text`. A spec that is not a tag with classes fails the
    render with ``SITE003``.
    """
    try:
        return highlight(value, spec)
    except KarniValueError as exc:
        raise _syntax_error(exc.message) from None


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
