"""``{% karni_form "<name>" %}``: a public form, with or without JavaScript.

``{% load karni_site %}`` (or ``{% load karni_forms %}``) gives the tag::

    {% karni_form "contact" %}
    {% karni_form "contact" classes="bootstrap" button="Send message" %}
    {% karni_form "booking" rows="name,email|day,service" widgets="service: radios"
       field_class="field" row_class="form-row" button_class="btn btn-primary" %}

It renders the fields a visitor fills (the writable fields of the form
viewset's create serializer) with labels, required marks and limits, the
CSRF token, the viewset's honeypot field and ``karni_site/forms.js``. The
form posts to ``karni_site:form``, which works without JavaScript; the
script submits in place. See :mod:`karni_site.forms` for how the name is
found and :mod:`karni_site.form_views` for what a submission does.

Arguments (every one optional, each a string or a variable):

* ``fields="name,email,message"``: which fields, in this order.
* ``rows="name,email|phone,company"``: fields that share a row element.
* ``labels="name: Your name"``, ``placeholders="email: you@example.com"``,
  ``widgets="topic: radios"`` (input, textarea, select, radios, checkboxes).
* ``button``, and the texts ``success``, ``invalid``, ``throttled``,
  ``refused``, ``failed``, ``choose``.
* ``next="/thanks/"``: the page to go to once sent (default: this page).
* ``id``: the form's id (default ``karni-form-<name>``).
* ``classes="bootstrap"``: a preset of class names, and ``<part>_class`` for
  each part (``form_class``, ``row_class``, ``column_class``, ``field_class``,
  ``label_class``, ``input_class``, ``select_class``, ``check_class``,
  ``check_input_class``, ``check_label_class``, ``invalid_class``,
  ``error_class``, ``help_class``, ``message_class``, ``success_class``,
  ``failure_class``, ``button_class``, ``required_class``).
* ``template``: another template for the whole form.

Override / escape hatch: the settings ``KARNI_SITE_FORM_CLASSES``,
``KARNI_SITE_FORM_PRESETS``, ``KARNI_SITE_FORM_MESSAGES``,
``KARNI_SITE_FORM_TEMPLATE`` and ``KARNI_SITE_FORM_SCRIPT``. The templates
``karni_site/forms/form.html`` and ``karni_site/forms/field.html`` (or
``karni_site/forms/<form>/<field>.html`` for one field). And
``KARNI_SITE_FORM_CLASS`` for the code.
"""

from __future__ import annotations

from typing import Any, Final

from django import template
from django.template.base import FilterExpression, Node, Parser, Token, kwarg_re
from django.template.context import Context
from django.utils.safestring import SafeString, mark_safe
from karni.errorcodes import docs_url

from karni_site.forms import CLASS_KEYS, MESSAGE_KEYS, resolve_form

__all__ = ["OPTIONS", "KarniFormNode", "do_karni_form", "register"]

register = template.Library()

SYNTAX_CODE: Final = "SITE021"

#: Every argument ``{% karni_form %}`` takes.
OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "fields",
        "rows",
        "labels",
        "placeholders",
        "widgets",
        "next",
        "id",
        "classes",
        "template",
        *MESSAGE_KEYS,
        *(f"{key}_class" for key in CLASS_KEYS),
    }
)


def _syntax_error(message: str) -> template.TemplateSyntaxError:
    return template.TemplateSyntaxError(f"{SYNTAX_CODE}: {message} See {docs_url(SYNTAX_CODE)}")


class KarniFormNode(Node):
    def __init__(self, name: FilterExpression, options: dict[str, FilterExpression]) -> None:
        self.name = name
        self.options = options

    def render(self, context: Context) -> SafeString:
        request = getattr(context, "request", None)
        if request is None:
            request = context.get("request")
        name = str(self.name.resolve(context))
        options: dict[str, Any] = {
            key: value.resolve(context) for key, value in self.options.items()
        }
        form = resolve_form(name)
        return mark_safe(form.render(request, options))  # noqa: S308 - rendered by a template


@register.tag("karni_form")
def do_karni_form(parser: Parser, token: Token) -> KarniFormNode:
    """``{% karni_form "<name>" option="value" ... %}``."""
    bits = token.split_contents()
    if len(bits) < 2:
        raise _syntax_error(
            '{% karni_form %} needs the form\'s name, for example {% karni_form "contact" %}.'
        )
    options: dict[str, FilterExpression] = {}
    for bit in bits[2:]:
        match = kwarg_re.match(bit)
        key = match.group(1) if match else None
        if not key or key not in OPTIONS:
            known = ", ".join(sorted(OPTIONS))
            raise _syntax_error(
                f'{{% karni_form %}} does not take {bit!r}. Write option="value" with one of: '
                f"{known}."
            )
        if key in options:
            raise _syntax_error(f"{{% karni_form %}} got {key} twice.")
        options[key] = parser.compile_filter(match.group(2))
    return KarniFormNode(parser.compile_filter(bits[1]), options)
