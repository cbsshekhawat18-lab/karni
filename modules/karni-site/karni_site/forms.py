"""Public forms: what ``{% karni_form %}`` renders and what its view saves.

A public form is a model that a ``BaseViewSet`` creates (``karni make form``
writes both). Nothing describes the form twice:

* The tag renders the writable fields of the viewset's create serializer,
  with their labels, required marks, limits and choices, plus the CSRF token
  and the viewset's honeypot field.
* Its view (``karni_site:form``, :mod:`karni_site.form_views`) saves through
  the viewset's own ``create``: the ``access`` declaration, the public-create
  rate limit (``KARNI_PUBLIC_CREATE_RATE``), the honeypot, validation, owner
  stamping and change history apply to the form exactly as to the API.

Without JavaScript the browser posts the form, the view redirects back to
the page with ``?sent=<form>`` (the tag then shows the success message), or
renders the page again with the errors next to each field. With
JavaScript, ``karni_site/forms.js`` posts the same data in place and shows
the same messages.

Finding a form by name (:func:`resolve_form`): ``KARNI_SITE_FORMS[name]``
(a viewset's dotted path or a model label), else the installed model whose
name is ``name`` (``"enquiry"``, ``"booking_request"`` for
``BookingRequest``, or ``"shop.enquiry"``), served by the viewset the API
router registered for it.

With ``editable="<key>"`` the texts a client may want to change (each
field's label and placeholder, the button, the sent message) are read from
editable blocks (:mod:`karni_site.blocks`) under that key, with the tag's
own texts as the defaults, so they are edited in the admin like the rest of
the page.

Override / escape hatch: ``KARNI_SITE_FORMS`` names any viewset.
``KARNI_SITE_FORM_CLASS`` swaps :class:`SiteForm` (override
:meth:`SiteForm.fields`, :meth:`SiteForm.describe`, :meth:`SiteForm.submit`
or :meth:`SiteForm.render`). The markup comes from templates
(``KARNI_SITE_FORM_TEMPLATE``, ``karni_site/forms/field.html``) and class
names (``KARNI_SITE_FORM_CLASSES``, ``KARNI_SITE_FORM_PRESETS``, the tag's
arguments). The viewset's own hooks (``access``, ``throttle``,
``get_honeypot_field()``, ``perform_create``) apply to the form.
"""

from __future__ import annotations

import copy
import functools
import html
import re
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldDoesNotExist
from django.forms.utils import flatatt
from django.http import HttpRequest, QueryDict
from django.template import Template, loader
from django.test.signals import setting_changed
from django.urls import NoReverseMatch, reverse
from django.utils.html import strip_tags
from django.utils.module_loading import import_string
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext_lazy as _
from karni.exceptions import KarniImproperlyConfigured
from rest_framework import serializers
from rest_framework.negotiation import BaseContentNegotiation, DefaultContentNegotiation
from rest_framework.request import Request
from rest_framework.settings import api_settings

from karni_site import conf

__all__ = [
    "CLASS_KEYS",
    "DEFAULT_CLASSES",
    "FIELD_ATTRIBUTES",
    "MESSAGE_KEYS",
    "PRESETS",
    "Choice",
    "FieldView",
    "FormState",
    "FormView",
    "Outcome",
    "RowView",
    "SiteForm",
    "UnknownForm",
    "class_names",
    "form_class",
    "messages",
    "resolve_form",
]

#: What every part of the form's markup carries, before KARNI_SITE_FORM_CLASSES,
#: a preset and the tag's own ``<key>_class`` arguments. Plain hooks a design's
#: stylesheet can target. ``""`` adds no class.
DEFAULT_CLASSES: Final[dict[str, str]] = {
    "form": "karni-form",  # <form>
    "row": "karni-form-row",  # the element around the fields of one row (rows="a,b")
    "column": "",  # added to a field's element inside a row (Bootstrap: col-md)
    "field": "karni-field",  # the element around one field: label, control, help, errors
    "label": "",  # <label>
    "input": "",  # <input> and <textarea>
    "select": "",  # <select>, else the input class
    "check": "karni-check",  # the element around a checkbox or a radio and its label
    "check_input": "",  # the checkbox or radio
    "check_label": "",  # the label next to a checkbox or radio
    "invalid": "",  # added to a control whose value was refused (aria-invalid is set too)
    "error": "karni-field-error",  # the message under a field whose value was refused
    "help": "karni-field-help",  # the help text under a field
    "message": "karni-form-message",  # the form's status line: sent, refused, rate-limited
    "success": "is-success",  # added to the status line after the form was sent
    "failure": "is-error",  # added to the status line when it was not
    "button": "",  # the submit button
    "required": "karni-required",  # the mark after a required field's label
}
CLASS_KEYS: Final[tuple[str, ...]] = tuple(DEFAULT_CLASSES)

#: Shipped class sets a tag picks with ``classes="<name>"``. A project adds its own,
#: or replaces one, in ``KARNI_SITE_FORM_PRESETS``.
PRESETS: Final[dict[str, dict[str, str]]] = {
    "bootstrap": {
        "form": "",
        "row": "row",
        "column": "col-md",
        "field": "mb-3",
        "label": "form-label",
        "input": "form-control",
        "select": "form-select",
        "check": "form-check mb-3",
        "check_input": "form-check-input",
        "check_label": "form-check-label",
        "invalid": "is-invalid",
        "error": "invalid-feedback",
        "help": "form-text",
        "message": "alert",
        "success": "alert-success",
        "failure": "alert-danger",
        "button": "btn btn-primary",
        "required": "text-danger",
    },
}

MESSAGE_KEYS: Final[tuple[str, ...]] = (
    "success",
    "invalid",
    "throttled",
    "refused",
    "failed",
    "choose",
    "button",
)

#: The texts a form shows before KARNI_SITE_FORM_MESSAGES and the tag's arguments.
DEFAULT_MESSAGES: Final[dict[str, Any]] = {
    "success": _("Thank you. Your submission was received."),
    "invalid": _("Please correct the fields marked below."),
    "throttled": _("This form was sent several times in a short while. Please try again later."),
    "refused": _("This form cannot be sent."),
    "failed": _("The form could not be sent. Please try again in a moment."),
    "choose": _("Choose one"),
    "button": _("Send"),
}

#: The hidden fields the form posts next to the model's fields. A dash keeps them
#: apart from every model field name.
NEXT_FIELD: Final = "karni-next"

#: Common field names and the browser autofill token each one is (WHATWG autocomplete).
AUTOCOMPLETE: Final[dict[str, str]] = {
    "name": "name",
    "full_name": "name",
    "your_name": "name",
    "first_name": "given-name",
    "given_name": "given-name",
    "last_name": "family-name",
    "family_name": "family-name",
    "surname": "family-name",
    "email": "email",
    "email_address": "email",
    "phone": "tel",
    "phone_number": "tel",
    "telephone": "tel",
    "mobile": "tel",
    "company": "organization",
    "organization": "organization",
    "organisation": "organization",
    "address": "street-address",
    "street_address": "street-address",
    "city": "address-level2",
    "town": "address-level2",
    "postcode": "postal-code",
    "postal_code": "postal-code",
    "zip": "postal-code",
    "zip_code": "postal-code",
    "country": "country-name",
    "website": "url",
}

#: The attributes a tag's ``attrs="message: rows=4 | guests: min=1 max=8"`` may give a
#: field's control, as a design's own markup sets them. The name, type, value, required
#: and class come from the form itself.
FIELD_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"rows", "cols", "min", "max", "step", "pattern", "size", "inputmode", "autocomplete"}
)

_CODE = "SITE020"
_ROUTE_CODE = "SITE022"


class UnknownForm(KarniImproperlyConfigured):
    """``{% karni_form %}`` or the form view named a form Karni cannot find (``SITE020``)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=_CODE)


# settings


def _merged(base: Mapping[str, Any], *layers: Any) -> dict[str, Any]:
    merged = dict(base)
    for layer in layers:
        if isinstance(layer, Mapping):
            merged.update({str(key): value for key, value in layer.items()})
    return merged


def presets() -> dict[str, dict[str, str]]:
    """The shipped presets with ``KARNI_SITE_FORM_PRESETS`` over them (a project's wins)."""
    found = {name: dict(classes) for name, classes in PRESETS.items()}
    for name, classes in (conf.get("KARNI_SITE_FORM_PRESETS") or {}).items():
        found[str(name)] = dict(classes)
    return found


def class_names(
    preset: str | None = None, overrides: Mapping[str, Any] | None = None
) -> dict[str, str]:
    """The class of each part: defaults, ``KARNI_SITE_FORM_CLASSES``, the preset, ``overrides``.

    :raises KarniImproperlyConfigured: ``SITE021`` for a preset no setting defines.
    """
    layers: list[Any] = [conf.get("KARNI_SITE_FORM_CLASSES")]
    if preset:
        known = presets()
        if preset not in known:
            raise KarniImproperlyConfigured(
                f"{{% karni_form %}} classes={preset!r}: no such preset. Known: "
                f"{', '.join(sorted(known))}. Add it to KARNI_SITE_FORM_PRESETS, or pass the "
                "class names one by one (field_class=..., input_class=...).",
                code="SITE021",
            )
        layers.append(known[preset])
    layers.append(overrides)
    merged = _merged(DEFAULT_CLASSES, *layers)
    return {key: " ".join(str(merged.get(key) or "").split()) for key in CLASS_KEYS}


def messages(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The texts: defaults, ``KARNI_SITE_FORM_MESSAGES``, then ``overrides``."""
    merged = _merged(DEFAULT_MESSAGES, conf.get("KARNI_SITE_FORM_MESSAGES"), overrides)
    return {key: merged[key] for key in MESSAGE_KEYS}


# finding a form


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _viewset_for(model: type[Any]) -> type[Any] | None:
    from karni.api.routers import viewset_for_model

    return viewset_for_model(model)


def _from_reference(name: str, reference: Any) -> type[Any]:
    """``KARNI_SITE_FORMS[name]``: a viewset class or path, or a model label."""
    if isinstance(reference, type):
        return reference
    text = str(reference)
    if text.count(".") == 1:
        try:
            model = apps.get_model(text)
        except (LookupError, ValueError):
            model = None
        if model is not None:
            viewset = _viewset_for(model)
            if viewset is None:
                raise UnknownForm(
                    f"KARNI_SITE_FORMS[{name!r}] names {text}, which no viewset serves. Add a "
                    f"BaseViewSet for it (karni make viewset {model.__name__}), or name the "
                    "viewset's dotted path instead."
                )
            return viewset
    try:
        found = import_string(text)
    except ImportError as exc:
        raise UnknownForm(
            f"KARNI_SITE_FORMS[{name!r}] = {text!r} is neither a model label (app_label.Model) "
            f"nor the dotted path of a viewset ({exc})."
        ) from exc
    if not isinstance(found, type):
        raise UnknownForm(f"KARNI_SITE_FORMS[{name!r}] = {text!r} is not a viewset class.")
    return found


def _candidates(name: str) -> list[type[Any]]:
    wanted = name.lower()
    if "." in wanted:
        label, _sep, model_name = wanted.partition(".")
        return [
            model
            for model in apps.get_models()
            if model._meta.app_label == label and model._meta.model_name == _normal(model_name)
        ]
    key = _normal(wanted)
    return [model for model in apps.get_models() if model._meta.model_name == key]


@functools.lru_cache(maxsize=256)
def _viewset_named(name: str) -> type[Any]:
    configured = conf.get("KARNI_SITE_FORMS") or {}
    if name in configured:
        return _from_reference(name, configured[name])
    models = _candidates(name)
    served = [(model, _viewset_for(model)) for model in models]
    routed = [(model, viewset) for model, viewset in served if viewset is not None]
    if len(routed) == 1:
        return routed[0][1]
    if len(routed) > 1:
        labels = ", ".join(sorted(model._meta.label_lower for model, _ in routed))
        raise UnknownForm(
            f"{{% karni_form {name!r} %}} matches several models ({labels}). Name one by its "
            f'label, {{% karni_form "{routed[0][0]._meta.label_lower}" %}}, or map the name in '
            "KARNI_SITE_FORMS."
        )
    if models:
        model = models[0]
        raise UnknownForm(
            f"{{% karni_form {name!r} %}}: {model._meta.label} has no viewset, so nothing can "
            f"save the form. Add one that lets visitors create (karni make viewset "
            f"{model.__name__} --access public-create), or run karni make form."
        )
    raise UnknownForm(
        f"{{% karni_form {name!r} %}}: no model is named {name!r}. Create the form with "
        f"karni make form {name} <field:type> ..., use the name of a model a viewset serves, "
        "or map the name to a viewset in KARNI_SITE_FORMS."
    )


def _forget(sender: object, setting: str, **kwargs: Any) -> None:
    if setting in {"KARNI_SITE_FORMS", "KARNI_API_ROUTER", "KARNI_SITE_FORM_CLASS"}:
        _viewset_named.cache_clear()


setting_changed.connect(_forget, dispatch_uid="karni_site.forms.resolve_cache")


def form_class() -> type[SiteForm]:
    """The class ``KARNI_SITE_FORM_CLASS`` names (:class:`SiteForm` by default)."""
    configured = conf.get("KARNI_SITE_FORM_CLASS")
    found = configured if isinstance(configured, type) else import_string(str(configured))
    if not (isinstance(found, type) and issubclass(found, SiteForm)):
        raise KarniImproperlyConfigured(
            f"KARNI_SITE_FORM_CLASS = {configured!r} is not a karni_site.forms.SiteForm subclass.",
            code="SITE021",
        )
    return found


def resolve_form(name: str) -> SiteForm:
    """The form called ``name``. :raises UnknownForm: ``SITE020`` when there is none."""
    name = str(name).strip()
    if not name:
        raise UnknownForm("{% karni_form %} got an empty form name.")
    return form_class()(name, _viewset_named(name))


# outcomes


@dataclass
class Outcome:
    """What the viewset answered a submission, as a form sees it.

    ``kind`` is one of ``success`` (2xx, including the honeypot's 202),
    ``invalid`` (400, with ``errors``), ``throttled`` (429), ``refused``
    (401, 403, 404, 405) and ``failed`` (anything else).
    """

    status: int
    kind: str
    errors: dict[str, list[str]] = field(default_factory=dict)
    retry_after: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind == "success"


def _strings(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, Mapping):
        found: list[str] = []
        for key, inner in value.items():
            found.extend(_strings(inner, f"{prefix}{key}: "))
        return found
    if isinstance(value, list | tuple):
        return [text for item in value for text in _strings(item, prefix)]
    return [f"{prefix}{value}"]


def error_messages(data: Any) -> dict[str, list[str]]:
    """A DRF error body as ``{field: [message]}``. Errors on no field go under ``""``."""
    if isinstance(data, Mapping):
        found: dict[str, list[str]] = {}
        for key, value in data.items():
            target = "" if key in {api_settings.NON_FIELD_ERRORS_KEY, "detail"} else str(key)
            found.setdefault(target, []).extend(_strings(value))
        return found
    return {"": _strings(data)} if data else {}


def outcome_of(status: int, data: Any = None, retry_after: str | None = None) -> Outcome:
    """The :class:`Outcome` of a response's status and body."""
    if 200 <= status < 300:
        return Outcome(status, "success")
    if status == 400:
        return Outcome(status, "invalid", error_messages(data))
    if status == 429:
        return Outcome(status, "throttled", retry_after=retry_after)
    if status in {401, 403, 404, 405}:
        return Outcome(status, "refused")
    return Outcome(status, "failed")


@dataclass
class FormState:
    """A submission the page is rendered again for: the values sent and what came of them."""

    values: Mapping[str, Any]
    outcome: Outcome


def states(request: HttpRequest | None) -> dict[str, FormState]:
    """``request.karni_forms``: the forms submitted in this request, by name."""
    if request is None:
        return {}
    found = getattr(request, "karni_forms", None)
    if found is None:
        found = {}
        request.karni_forms = found
    return found


# what the template renders


@dataclass
class Choice:
    value: str
    label: str
    selected: bool
    id: str = ""


@dataclass
class FieldView:
    """One field as the templates see it. ``attrs`` is the control's attribute string."""

    name: str
    id: str
    label: str
    widget: str  # input, textarea, select, radios, checkbox, checkboxes
    input_type: str
    required: bool
    value: str
    values: list[str]
    choices: list[Choice]
    multiple: bool
    empty_option: bool
    help: str
    placeholder: str
    errors: list[str]
    classes: dict[str, str]
    attributes: dict[str, Any]
    template: Template | Any = None
    in_row: bool = False
    is_row: bool = False

    @property
    def attrs(self) -> SafeString:
        """The control's attributes, escaped: ``<input{{ field.attrs }}>``."""
        return mark_safe(flatatt(self.attributes))  # noqa: S308 - flatatt escapes every value

    @property
    def wrapper_class(self) -> str:
        parts = [self.classes["check"] if self.widget == "checkbox" else self.classes["field"]]
        if self.in_row:
            parts.append(self.classes["column"])
        return " ".join(part for part in parts if part)

    @property
    def described_by(self) -> str:
        ids = [f"{self.id}-help"] if self.help else []
        if self.errors:
            ids.append(f"{self.id}-error")
        return " ".join(ids)


@dataclass
class RowView:
    """Several fields on one row (``rows="name,email"``)."""

    fields: list[FieldView]
    is_row: bool = True


@dataclass
class FormView:
    """The form as ``karni_site/forms/form.html`` sees it."""

    name: str
    id: str
    action: str
    next: str
    follow: bool
    multipart: bool
    honeypot: str | None
    classes: dict[str, str]
    messages: dict[str, Any]
    message: str
    message_kind: str  # "", "success" or "failure"
    errors: list[str]
    required_mark: str
    items: list[FieldView | RowView]
    fields: list[FieldView]
    script: bool

    @property
    def message_class(self) -> str:
        extra = self.classes.get(self.message_kind, "") if self.message_kind else ""
        return " ".join(part for part in (self.classes["message"], extra) if part)

    @property
    def data_attrs(self) -> SafeString:
        """``data-karni-*`` attributes forms.js reads: classes and messages for in-place updates."""
        values: dict[str, Any] = {"data-karni-form": self.name}
        for key in ("error", "invalid", "success", "failure"):
            values[f"data-karni-{key}-class"] = self.classes[key]
        for key in ("success", "invalid", "throttled", "refused", "failed"):
            values[f"data-karni-{key}"] = str(self.messages[key])
        if self.follow:
            values["data-karni-follow"] = True
        return mark_safe(flatatt(values))  # noqa: S308 - flatatt escapes every value


def _pairs(spec: Any, what: str) -> dict[str, str]:
    """``"name: Your name | email: Your email"`` as a dict (a dict passes through)."""
    if isinstance(spec, Mapping):
        return {str(key): str(value) for key, value in spec.items()}
    found: dict[str, str] = {}
    for part in str(spec or "").split("|"):
        if not part.strip():
            continue
        key, colon, value = part.partition(":")
        if not colon or not key.strip():
            raise KarniImproperlyConfigured(
                f'{{% karni_form %}} {what}="{spec}": write "field: text | field: text".',
                code="SITE021",
            )
        found[key.strip()] = value.strip()
    return found


def _attributes(spec: Any) -> dict[str, dict[str, str]]:
    """``"message: rows=4 | guests: min=1 max=8"`` as ``{field: {attribute: value}}``.

    A value with spaces is written in single quotes: ``title='Five digits'``. A dict
    passes through. Only :data:`FIELD_ATTRIBUTES` are taken.
    """
    found: dict[str, dict[str, str]] = {}
    if isinstance(spec, Mapping):
        for name, given in spec.items():
            found[str(name)] = {str(key): str(value) for key, value in dict(given).items()}
    else:
        for name, text in _pairs(spec, "attrs").items():
            try:
                words = shlex.split(text)
            except ValueError as exc:
                raise KarniImproperlyConfigured(
                    f'{{% karni_form %}} attrs="{spec}": {name}: {exc}. Write "field: rows=4 '
                    "min=1 | field: pattern='[0-9]{5}'\" (single quotes around a value with "
                    "spaces).",
                    code="SITE021",
                ) from exc
            pairs: dict[str, str] = {}
            for word in words:
                key, equals, value = word.partition("=")
                if not equals or not key:
                    raise KarniImproperlyConfigured(
                        f'{{% karni_form %}} attrs="{spec}": {name}: {word!r} is not '
                        "attribute=value, such as rows=4.",
                        code="SITE021",
                    )
                pairs[key.lower()] = value
            found[name] = pairs
    for name, pairs in found.items():
        unknown = sorted(set(pairs) - FIELD_ATTRIBUTES)
        if unknown:
            raise KarniImproperlyConfigured(
                f"{{% karni_form %}} attrs: {name}: {', '.join(unknown)} cannot be set here. "
                f"attrs takes {', '.join(sorted(FIELD_ATTRIBUTES))}: the form sets the name, "
                "type, value, required and class itself (class names: <part>_class).",
                code="SITE021",
            )
    return found


def _names(spec: Any) -> list[str]:
    if isinstance(spec, list | tuple):
        return [str(item).strip() for item in spec if str(item).strip()]
    return [part.strip() for part in str(spec or "").split(",") if part.strip()]


def _rows(spec: Any) -> list[list[str]]:
    if isinstance(spec, list | tuple):
        return [_names(row) for row in spec if _names(row)]
    return [_names(row) for row in str(spec or "").split("|") if _names(row)]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else ""
    return str(value)


class _FirstRenderer(BaseContentNegotiation):
    """The viewset's first renderer whatever the browser accepts: the form reads ``.data`` only."""

    def select_parser(self, request: Any, parsers: Any) -> Any:
        return DefaultContentNegotiation().select_parser(request, parsers)

    def select_renderer(self, request: Any, renderers: Any, format_suffix: Any = None) -> Any:
        return renderers[0], renderers[0].media_type


class SiteForm:
    """A public form: the viewset that saves it, and how it is described and rendered.

    Override / escape hatch: subclass it and point ``KARNI_SITE_FORM_CLASS``
    at the subclass. :meth:`fields` picks the fields, :meth:`describe` turns
    one into what the template renders, :meth:`submit` saves a submission,
    :meth:`render` renders the form.
    """

    def __init__(self, name: str, viewset: type[Any]) -> None:
        self.name = name
        self.viewset = viewset

    @property
    def model(self) -> type[Any]:
        model = getattr(self.viewset, "model", None)
        return model if model is not None else self.viewset.queryset.model

    # the viewset

    def view(self, request: HttpRequest | None, user: Any) -> Any:
        """A viewset instance set up for ``create``, as ``user``, outside the dispatch."""
        base = copy.copy(request) if request is not None else HttpRequest()
        base.GET = QueryDict()
        if base.method is None:
            base.method = "GET"
        base._force_auth_user = user  # DRF's ForcedAuthentication reads it
        view = self.viewset()
        view.action = "create"
        view.action_map = {"post": "create"}
        view.args, view.kwargs = (), {}
        view.format_kwarg = None
        view.headers = {}
        view.request = Request(base)
        return view

    def is_public(self) -> bool:
        """Whether anonymous visitors may create (``create=Public()``)."""
        from karni.api.throttling import is_public_create

        return bool(is_public_create(self.viewset))

    def audience(self, request: HttpRequest | None) -> Any:
        """Who the fields are described for: an anonymous visitor when anyone may create.

        A signed-in staff member sees the public's form on the site, not the
        staff-only fields of the same model.
        """
        if self.is_public() or request is None:
            return AnonymousUser()
        return getattr(request, "user", None) or AnonymousUser()

    def fields(self, request: HttpRequest | None) -> list[tuple[str, Any]]:
        """``(name, serializer field)`` for every field a visitor fills, in declaration order."""
        view = self.view(request, self.audience(request))
        serializer = view.get_serializer()
        return [
            (name, item)
            for name, item in serializer.fields.items()
            if not item.read_only and not isinstance(item, serializers.HiddenField)
        ]

    def honeypot(self, request: HttpRequest | None) -> str | None:
        """The viewset's honeypot field for this form's create (``get_honeypot_field()``)."""
        view = self.view(request, self.audience(request))
        getter = getattr(view, "get_honeypot_field", None)
        return getter() if callable(getter) else None

    @functools.cached_property
    def create_view(self) -> Callable[..., Any]:
        """The viewset's ``create`` as a view, whatever ``Accept`` the browser sends."""
        view: Callable[..., Any] = self.viewset.as_view(
            {"post": "create"}, content_negotiation_class=_FirstRenderer
        )
        return view

    def submit(self, request: HttpRequest) -> Outcome:
        """Save the posted form through the viewset's ``create``, as the API would."""
        response = self.create_view(request)
        retry = response.headers.get("Retry-After") if hasattr(response, "headers") else None
        return outcome_of(response.status_code, getattr(response, "data", None), retry)

    # describing fields

    def model_field(self, name: str) -> Any:
        try:
            return self.model._meta.get_field(name)
        except FieldDoesNotExist:
            return None

    def widget(self, name: str, item: Any) -> tuple[str, str]:
        """``(widget, input type)`` for a serializer field."""
        if isinstance(item, serializers.BooleanField):
            return "checkbox", "checkbox"
        if isinstance(item, serializers.ManyRelatedField | serializers.MultipleChoiceField):
            return "select", ""
        if isinstance(item, serializers.ChoiceField | serializers.RelatedField):
            return "select", ""
        if isinstance(item, serializers.FileField):
            return "input", "file"
        if isinstance(item, serializers.EmailField):
            return "input", "email"
        if isinstance(item, serializers.URLField):
            return "input", "url"
        if isinstance(item, serializers.IntegerField | serializers.DecimalField):
            return "input", "number"
        if isinstance(item, serializers.FloatField):
            return "input", "number"
        if isinstance(item, serializers.DateTimeField):
            return "input", "datetime-local"
        if isinstance(item, serializers.DateField):
            return "input", "date"
        if isinstance(item, serializers.TimeField):
            return "input", "time"
        if isinstance(item, serializers.JSONField):
            return "textarea", ""
        style = getattr(item, "style", None) or {}
        if style.get("base_template") == "textarea.html":
            return "textarea", ""
        model_field = self.model_field(getattr(item, "source", name) or name)
        if type(model_field).__name__ == "PhoneField":
            return "input", "tel"
        return "input", "text"

    def choices(self, item: Any) -> list[tuple[str, str]]:
        """``(value, label)`` of a choice or relation field (relations: rows the visitor reads)."""
        source = getattr(item, "child_relation", item)
        try:
            found = source.get_choices(cutoff=None) if hasattr(source, "get_choices") else None
        except TypeError:
            found = None
        if found is None:
            found = getattr(source, "choices", None) or {}
        return [(_text(value), str(label)) for value, label in dict(found).items()]

    def initial(self, item: Any) -> Any:
        default = getattr(item, "default", serializers.empty)
        if default is serializers.empty or callable(default):
            return None
        return default

    def describe(
        self,
        name: str,
        item: Any,
        *,
        form_id: str,
        classes: Mapping[str, str],
        values: Mapping[str, Any] | None,
        errors: list[str],
        label: str | None = None,
        placeholder: str | None = None,
        widget: str | None = None,
        extra: Mapping[str, str] | None = None,
    ) -> FieldView:
        """One serializer field as a :class:`FieldView` (values come from a re-render).

        ``extra`` holds the tag's ``attrs`` for this field (:data:`FIELD_ATTRIBUTES`),
        set on its control over what the field itself gives (a design's ``rows="4"``).
        """
        kind, input_type = self.widget(name, item)
        multiple = isinstance(item, serializers.ManyRelatedField | serializers.MultipleChoiceField)
        if widget:
            if widget in {"radios", "checkboxes"} and kind == "select":
                kind = widget
            elif widget in {"textarea", "input"} and kind in {"input", "textarea"}:
                kind, input_type = widget, input_type or "text"
            elif widget not in {"select", "textarea", "input", "radios", "checkboxes"}:
                raise KarniImproperlyConfigured(
                    f'{{% karni_form %}} widgets="{name}: {widget}": choose input, textarea, '
                    "select, radios or checkboxes.",
                    code="SITE021",
                )
        if values is not None:
            getlist = getattr(values, "getlist", None)
            raw = getlist(name) if callable(getlist) else values.get(name)
            current = [_text(v) for v in (raw if isinstance(raw, list | tuple) else [raw]) if v]
        else:
            start = self.initial(item)
            seq = start if isinstance(start, list | tuple | set) else [start]
            current = [_text(v) for v in seq if v is not None and _text(v) != ""]
        value = current[0] if current else ""
        field_id = f"{form_id}-{name}"
        required = bool(getattr(item, "required", False))
        choices: list[Choice] = []
        if kind in {"select", "radios", "checkboxes"}:
            choices = [
                Choice(key, text, key in current, f"{field_id}-{index}")
                for index, (key, text) in enumerate(self.choices(item))
            ]
        control = classes["input"]
        if kind == "select":
            control = classes["select"] or classes["input"]
        elif kind in {"checkbox", "radios", "checkboxes"}:
            control = classes["check_input"]
        if errors and classes["invalid"]:
            control = f"{control} {classes['invalid']}".strip()
        attributes: dict[str, Any] = {"name": name}
        if kind not in {"radios", "checkboxes"}:
            attributes["id"] = field_id
        if kind == "input":
            attributes["type"] = input_type
            if input_type != "file" and value:
                attributes["value"] = value
        if kind == "checkbox":
            attributes["type"] = "checkbox"
            attributes["value"] = "true"
            attributes["checked"] = value.lower() in {"true", "on", "1", "yes"}
        attributes["required"] = required and kind not in {"checkboxes"}
        if multiple and kind == "select":
            attributes["multiple"] = True
        for source, target in (("max_length", "maxlength"), ("min_length", "minlength")):
            limit = getattr(item, source, None)
            if limit and kind in {"input", "textarea"} and input_type not in {"file", "number"}:
                attributes[target] = limit
        if input_type == "number":
            for source, target in (("min_value", "min"), ("max_value", "max")):
                limit = getattr(item, source, None)
                if limit is not None:
                    attributes[target] = limit
            places = getattr(item, "decimal_places", None)
            if isinstance(item, serializers.FloatField):
                attributes["step"] = "any"
            elif isinstance(places, int) and places > 0:
                attributes["step"] = str(Decimal(1).scaleb(-places))
        if input_type == "file" and isinstance(item, serializers.ImageField):
            attributes["accept"] = "image/*"
        text_hint = placeholder or ""
        if text_hint and kind in {"input", "textarea"}:
            attributes["placeholder"] = text_hint
        autofill = AUTOCOMPLETE.get(name) or {"email": "email", "tel": "tel"}.get(input_type)
        if autofill and kind == "input":
            attributes["autocomplete"] = autofill
        if control and kind not in {"radios", "checkboxes"}:
            attributes["class"] = control
        for attribute, given in (extra or {}).items():
            if attribute in FIELD_ATTRIBUTES:
                attributes[attribute] = given
        help_text = str(getattr(item, "help_text", "") or "")
        view = FieldView(
            name=name,
            id=field_id,
            label=str(label if label is not None else (getattr(item, "label", None) or name)),
            widget=kind,
            input_type=input_type,
            required=required,
            value=value,
            values=current,
            choices=choices,
            multiple=multiple,
            empty_option=kind == "select" and not multiple and (required or not value),
            help=help_text,
            placeholder=text_hint,
            errors=list(errors),
            classes=dict(classes),
            attributes=attributes,
        )
        if errors:
            attributes["aria-invalid"] = "true"
        if view.described_by and kind not in {"radios", "checkboxes"}:
            attributes["aria-describedby"] = view.described_by
        return view

    def field_template(self, name: str) -> Any:
        """``karni_site/forms/<form>/<field>.html``, ``.../<form>/field.html`` or the default."""
        form = re.sub(r"[^A-Za-z0-9_-]", "_", self.name)
        return loader.select_template(
            [
                f"karni_site/forms/{form}/{name}.html",
                f"karni_site/forms/{form}/field.html",
                "karni_site/forms/field.html",
            ]
        )

    # the form

    def action(self) -> str:
        try:
            return reverse("karni_site:form", args=[self.name])
        except NoReverseMatch as exc:
            raise KarniImproperlyConfigured(
                f"{{% karni_form {self.name!r} %}} posts to karni_site's form view, which is not "
                'routed. Add path("", include("karni_site.urls")) to urlpatterns in '
                "config/urls.py, before the site's own include.",
                code=_ROUTE_CODE,
            ) from exc

    def editable_text(self, key: str, default: str, request: HttpRequest | None) -> str:
        """The plain text of block ``key``: the client's edit, else ``default``.

        The block stores HTML like every text block, so the default goes in
        escaped and the result comes out as text, which the form's template
        escapes again where it writes it.
        """
        from karni_site import blocks

        stored = blocks.text(key, html.escape(str(default), quote=False), request)
        return html.unescape(strip_tags(stored)).strip()

    def editable_key(self, options: Mapping[str, Any]) -> str:
        """The ``editable="..."`` block key prefix, or ``""``.

        :raises KarniImproperlyConfigured: ``SITE021`` for a prefix that is not a block key.
        """
        from karni_site.models import KEY_PATTERN

        prefix = _text(options.get("editable")).strip()
        if prefix and not re.match(KEY_PATTERN, prefix):
            raise KarniImproperlyConfigured(
                f'{{% karni_form {self.name!r} %}} editable="{prefix}" is not a block key: '
                "lowercase words joined by dots, the page first, such as "
                'editable="contact.enquiry".',
                code="SITE021",
            )
        return prefix

    def layout(self, request: HttpRequest | None, options: Mapping[str, Any]) -> FormView:
        """The :class:`FormView` for ``options`` (the tag's arguments)."""
        overrides = {
            key[: -len("_class")]: value
            for key, value in options.items()
            if key.endswith("_class") and key[: -len("_class")] in CLASS_KEYS
        }
        classes = class_names(_text(options.get("classes")) or None, overrides)
        texts = messages({key: options[key] for key in MESSAGE_KEYS if options.get(key)})
        form_id = _text(options.get("id")) or f"karni-form-{self.name}"
        state = states(request).get(self.name)
        values = state.values if state is not None else None
        errors = dict(state.outcome.errors) if state is not None else {}
        labels = _pairs(options.get("labels"), "labels")
        hints = _pairs(options.get("placeholders"), "placeholders")
        widgets = _pairs(options.get("widgets"), "widgets")
        extras = _attributes(options.get("attrs"))
        available = self.fields(request)
        chosen = _names(options.get("fields"))
        by_name = dict(available)
        named = [*chosen, *labels, *hints, *widgets, *extras]
        unknown = [name for name in named if name not in by_name]
        for row in _rows(options.get("rows")):
            unknown += [name for name in row if name not in by_name]
        if unknown:
            raise KarniImproperlyConfigured(
                f"{{% karni_form {self.name!r} %}} names {', '.join(sorted(set(unknown)))}, which "
                f"a visitor does not fill. The fields are: {', '.join(by_name) or 'none'}.",
                code="SITE021",
            )
        order = chosen or [name for name, _ in available]
        prefix = self.editable_key(options)
        if prefix:
            for key in ("button", "success"):
                texts[key] = self.editable_text(f"{prefix}.{key}", str(texts[key]), request)
            for name in order:
                item = by_name[name]
                default = labels.get(name) or str(getattr(item, "label", None) or name)
                labels[name] = self.editable_text(f"{prefix}.{name}.label", default, request)
                if hints.get(name):
                    hints[name] = self.editable_text(
                        f"{prefix}.{name}.placeholder", hints[name], request
                    )
        views: dict[str, FieldView] = {}
        for name in order:
            view = self.describe(
                name,
                by_name[name],
                form_id=form_id,
                classes=classes,
                values=values,
                errors=errors.pop(name, []),
                label=labels.get(name),
                placeholder=hints.get(name),
                widget=widgets.get(name),
                extra=extras.get(name),
            )
            view.template = self.field_template(name)
            views[name] = view
        leftover = [message for messages_ in errors.values() for message in messages_]
        items: list[FieldView | RowView] = []
        placed: set[str] = set()
        rows = {name: row for row in _rows(options.get("rows")) for name in row}
        for name in order:
            if name in placed:
                continue
            shared = rows.get(name)
            if shared:
                members = [views[member] for member in shared if member in views]
                for member in members:
                    member.in_row = True
                    placed.add(member.name)
                items.append(RowView(members))
            else:
                items.append(views[name])
                placed.add(name)
        message, kind = "", ""
        param = conf.get("KARNI_SITE_FORM_SENT_PARAM")
        if state is not None:
            message, kind = str(texts[state.outcome.kind]), "failure"
        elif request is not None and param and request.GET.get(param) == self.name:
            message, kind = str(texts["success"]), "success"
        follow = bool(options.get("next"))
        next_url = _text(options.get("next"))
        if not next_url and request is not None:
            next_url = _without_param(request.get_full_path(), param) + f"#{form_id}"
        script = bool(conf.get("KARNI_SITE_FORM_SCRIPT"))
        if script and request is not None:
            script = not getattr(request, "_karni_form_script", False)
            request._karni_form_script = True
        return FormView(
            name=self.name,
            id=form_id,
            action=self.action(),
            next=next_url,
            follow=follow,
            multipart=any(view.input_type == "file" for view in views.values()),
            honeypot=self.honeypot(request),
            classes=classes,
            messages=texts,
            message=message,
            message_kind=kind,
            errors=leftover if state is not None else [],
            required_mark=str(conf.get("KARNI_SITE_FORM_REQUIRED_MARK") or ""),
            items=items,
            fields=list(views.values()),
            script=script,
        )

    def render(self, request: HttpRequest | None, options: Mapping[str, Any]) -> str:
        """The form's HTML: ``template=`` or ``KARNI_SITE_FORM_TEMPLATE``, with ``form``."""
        name = _text(options.get("template")) or str(conf.get("KARNI_SITE_FORM_TEMPLATE"))
        template = loader.get_template(name)
        return str(template.render({"form": self.layout(request, options)}, request))


def _without_param(path: str, param: str | None) -> str:
    """``path`` without ``?<param>=...``, so a page sent from twice does not stack it."""
    if not param or "?" not in path:
        return path
    base, _sep, query = path.partition("?")
    params = QueryDict(query, mutable=True)
    params.pop(param, None)
    rest = params.urlencode()
    return f"{base}?{rest}" if rest else base
