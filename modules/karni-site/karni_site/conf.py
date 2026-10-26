"""Settings vocabulary for karni-site: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Override / escape hatch: define any of these names in the project's
settings.py.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

DEFAULTS: dict[str, Any] = {
    # The function {% ifactive %} asks whether a pattern names the current page:
    # (request, pattern) -> bool. A dotted path, so a project can swap the rule.
    "KARNI_SITE_IS_ACTIVE": "karni_site.navigation.is_active",
    # The templates karni_site.views.server_error tries in order. The first that
    # renders is the page. The last is this module's plain page, which needs nothing.
    "KARNI_SITE_SERVER_ERROR_TEMPLATES": ["500.html", "karni_site/500.html"],
    # The same for karni_site.views.page_not_found.
    "KARNI_SITE_NOT_FOUND_TEMPLATES": ["404.html", "karni_site/404.html"],
}


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])


# --- Public forms ({% karni_form %}, karni_site.forms, karni_site.notify) -------
# Kept as one block at the end of the file: each key is read through get() like the ones above.
DEFAULTS |= {
    # Form name -> the dotted path of the BaseViewSet that saves it, or a model label
    # ("shop.Enquiry"). Without an entry, {% karni_form "enquiry" %} finds the model by name.
    "KARNI_SITE_FORMS": {},
    # The class that renders and submits a form. A dotted path to a karni_site.forms.SiteForm
    # subclass, to change how fields are described or how a submission is saved.
    "KARNI_SITE_FORM_CLASS": "karni_site.forms.SiteForm",
    # The template {% karni_form %} renders. Each field renders karni_site/forms/field.html, or
    # karni_site/forms/<form>/<field>.html or karni_site/forms/<form>/field.html when one exists.
    "KARNI_SITE_FORM_TEMPLATE": "karni_site/forms/form.html",
    # Class names on the form's markup, merged over the module's plain defaults:
    # form, row, column, field, label, input, select, check, check_input, check_label,
    # invalid, error, help, message, success, failure, button, required.
    "KARNI_SITE_FORM_CLASSES": {},
    # Named sets of class names a tag picks with classes="<name>", merged over the shipped
    # "bootstrap" preset (Bootstrap 5). {"salon": {"field": "field", "row": "form-row"}}.
    "KARNI_SITE_FORM_PRESETS": {},
    # The texts a form shows, merged over the defaults: success, invalid, throttled, refused,
    # failed, choose (a select's empty option) and button. A tag's own success="..." wins.
    "KARNI_SITE_FORM_MESSAGES": {},
    # The text after a required field's label.
    "KARNI_SITE_FORM_REQUIRED_MARK": "*",
    # Whether {% karni_form %} adds karni_site/forms.js (submit in place, inline errors).
    # False leaves the form working without JavaScript, and a site may load its own script.
    "KARNI_SITE_FORM_SCRIPT": True,
    # The query parameter the page gets after a form was sent without JavaScript: ?sent=<form>.
    "KARNI_SITE_FORM_SENT_PARAM": "sent",
    # The page that shows a form with its errors when the page it was sent from cannot be
    # rendered again (no page, a page that needs a POST, a page that fails).
    "KARNI_SITE_FORM_PAGE_TEMPLATE": "karni_site/forms/page.html",
    # The sender of karni_site.notify emails. Empty: Django's DEFAULT_FROM_EMAIL.
    "KARNI_SITE_NOTIFY_FROM": "",
}
