"""The error codes of karni-site's public forms (SITE020 to SITE023), part of ``CODES``."""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["FORM_CODES"]

_SOURCE = "karni_site"

FORM_CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="SITE020",
        title="{% karni_form %} names a form Karni cannot find",
        kind="check",
        source=f"{_SOURCE}.forms.resolve_form; {_SOURCE}.form_checks",
        why=(
            'The tag finds a form by the name of its model ("enquiry" for Enquiry, '
            '"booking_request" for BookingRequest, or "app_label.model"), served by the viewset '
            "the API router registered for it, or by an entry in KARNI_SITE_FORMS. A name that "
            "matches no model, a model no viewset serves, or several models leaves the page "
            "without its form. karni check reports it before a visitor does."
        ),
        fix=(
            "Create the form with karni make form <name> <field:type> ..., use the name of a "
            "model a viewset serves, write app_label.model when several apps have the name, or "
            'map the name in KARNI_SITE_FORMS = {"<name>": "app.viewsets.SomeViewSet"}.'
        ),
    ),
    ErrorCode(
        code="SITE021",
        title="{% karni_form %} is written wrongly",
        kind="exception",
        source=f"{_SOURCE}.templatetags.karni_forms",
        why=(
            'The tag takes the form\'s name and then option="value" pairs it knows: fields, '
            "rows, labels, placeholders, widgets, next, id, classes, template, the texts (button, "
            "success, invalid, throttled, refused, failed, choose) and a <part>_class per part "
            'of the markup. labels, placeholders and widgets are "field: text | field: text", '
            "and every field they name must be one a visitor fills."
        ),
        fix=(
            'Write it like {% karni_form "contact" fields="name,email,message" '
            'labels="name: Your name" classes="bootstrap" %}. The karni-site README lists '
            "every option."
        ),
    ),
    ErrorCode(
        code="SITE022",
        title="The form view is not routed",
        kind="exception",
        source=f"{_SOURCE}.forms.SiteForm.action",
        why=(
            "Every {% karni_form %} posts to karni_site's form view (karni_site:form), which "
            "saves the submission through the form's viewset and works without JavaScript. "
            "Without the include in config/urls.py the form has nowhere to post."
        ),
        fix=(
            'Add path("", include("karni_site.urls")) to urlpatterns in config/urls.py, before '
            "the site's own include. karni make form adds it."
        ),
    ),
    ErrorCode(
        code="SITE023",
        title="A notification does not say who to email",
        kind="exception",
        source=f"{_SOURCE}.notify.recipients; {_SOURCE}.notify.notify_recipients",
        why=(
            'karni_site.notify.notify_recipients(row, setting="NAME", ...) emails the '
            "addresses in settings.NAME, and to=[...] emails fixed addresses. It needs exactly "
            "one of the two. A setting that does not exist is a typo or a missing line, and "
            "the email would never go out. An empty list only logs a warning."
        ),
        fix=(
            'Pass setting= or to=. For a setting, add NAME = env.list("NAME", default=[]) to '
            "config/settings.py and NAME=team@example.com to .env (karni make form --notify "
            "NAME writes both)."
        ),
    ),
)
