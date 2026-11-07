"""Text with rules: case-insensitive emails, generated slugs, E.164 phone numbers, markdown.

* :class:`EmailField`: ``unique=True`` means unique **case-insensitively**,
  enforced by a unique index on ``LOWER(email)`` (partial on soft-deletable
  models), so ``Alice@x.com`` and ``alice@x.com`` cannot both exist, not even
  through raw SQL. The domain is lower-cased on save (the local part keeps
  its case: RFC 5321 lets a server treat it case-sensitively). Django 5
  removed the ``CI*`` fields and ``citext``, so this needs no extension.
* :class:`SlugField`: unique by default, indexed by that constraint, and
  generated on save from ``populate_from`` when left empty. A slug already
  taken by a live row gets ``-2``, ``-3``, ... (then a random suffix); the
  unique constraint still rejects a duplicate from a concurrent insert.
* :class:`PhoneField`: stored in E.164 (``+`` then country code and number,
  at most 15 digits: ``+14155552671``). Input may carry spaces, dashes,
  dots, parentheses, a ``(0)`` trunk marker or a ``00`` international prefix;
  it is normalised by the model field, its form field and the API's
  serializer field. A national number (no ``+``) is rejected unless
  ``KARNI_PHONE_COUNTRY_CODE`` names the country code to give it: then
  ``"01234 000 111"`` loses its trunk prefix (``KARNI_PHONE_TRUNK_PREFIX``,
  ``"0"`` by default) and is stored as ``+441234000111``. A database CHECK
  enforces the format on PostgreSQL (regular expression) and SQLite
  (``GLOB``).

  No dependency: per-country number plans need Google's ``phonenumbers``
  (several megabytes of metadata), which Karni does not impose. Add
  ``validators=[...]`` built on it when you need to know that a number is
  assignable, not just well-formed.

* :class:`MarkdownField` (experimental): a ``TextField`` whose value is
  markdown. The column is plain text and nothing is rendered on the server:
  the OpenAPI schema says ``format: markdown``, so ``@karni/ui``'s
  ResourceForm edits it with Write and Preview tabs and ResourceDetail shows
  it formatted and sanitized (MarkdownView). It is searched like any text
  field (list it in a viewset's ``search_fields``).

Override / escape hatch: ``models.EmailField``/``SlugField``/``CharField``/
``TextField`` are the plain replacements; ``unique=False`` drops the
constraint; ``KARNI_PHONE_NORMALIZER`` names a function that replaces the phone
rules (it may call :func:`to_e164` itself).
"""

from __future__ import annotations

import re
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Func, Q
from django.utils.crypto import get_random_string
from django.utils.deconstruct import deconstructible
from django.utils.text import slugify

from karni.fields.base import KarniField, is_soft_deletable

__all__ = [
    "E164",
    "E164Format",
    "EmailField",
    "MarkdownField",
    "PhoneField",
    "PhoneFormField",
    "SlugField",
    "default_phone_normalizer",
    "normalize_email",
    "normalize_phone",
    "to_e164",
    "validate_e164",
]

#: The E.164 format PhoneField stores: + then 2 to 15 digits, no leading zero.
E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")
_PHONE_JUNK = re.compile(r"[\s\-./()]")
_TRUNK = re.compile(r"\(0\)")


def normalize_email(value: Any) -> Any:
    """``value`` stripped, with its domain lower-cased (non-strings pass through)."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    local, at, domain = value.rpartition("@")
    return f"{local}@{domain.lower()}" if at else value


#: The function KARNI_PHONE_NORMALIZER names when the project sets none.
DEFAULT_PHONE_NORMALIZER = "karni.fields.text.default_phone_normalizer"


def to_e164(value: Any, *, country_code: str | None = None, trunk_prefix: str = "0") -> Any:
    """``value`` in E.164 when it can be read as a phone number, else unchanged.

    ``"+44 (0)20 7946 0958"`` and ``"0044 20 7946 0958"`` both become
    ``"+442079460958"``. With ``country_code`` (digits, ``"44"``), a number
    written without ``+`` or ``00`` is national: it loses ``trunk_prefix``
    when it starts with it and gets ``+<country_code>`` in front, so
    ``"01234 000 111"`` becomes ``"+441234000111"``. Anything else (letters,
    an extension, a national number without ``country_code``) comes back as
    given, for :func:`validate_e164` to reject.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    compact = _PHONE_JUNK.sub("", _TRUNK.sub("", value.strip()))
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    elif country_code and compact.isdigit():
        if trunk_prefix and compact.startswith(trunk_prefix):
            compact = compact[len(trunk_prefix) :]
        compact = f"+{country_code.lstrip('+')}{compact}"
    return compact if E164.match(compact) else value


def _setting(name: str, default: Any) -> Any:
    """A phone setting, read on every call (the default outside a configured project)."""
    return getattr(settings, name, default) if settings.configured else default


def phone_country_code() -> str | None:
    """``KARNI_PHONE_COUNTRY_CODE`` without a leading ``+``, or ``None`` (read on every call)."""
    code = _setting("KARNI_PHONE_COUNTRY_CODE", None)
    if code is None:
        return None
    return str(code).strip().lstrip("+") or None


def default_phone_normalizer(value: Any) -> Any:
    """Karni's rules (:func:`to_e164`) with ``KARNI_PHONE_COUNTRY_CODE`` and ``_TRUNK_PREFIX``."""
    trunk = _setting("KARNI_PHONE_TRUNK_PREFIX", "0")
    return to_e164(
        value, country_code=phone_country_code(), trunk_prefix="" if trunk is None else str(trunk)
    )


def normalize_phone(value: Any) -> Any:
    """``value`` through the function ``KARNI_PHONE_NORMALIZER`` names.

    That is :func:`default_phone_normalizer` unless the project names its
    own: a function taking the value as typed and returning it in E.164, or
    unchanged when it cannot (:func:`validate_e164` then rejects it).
    """
    from karni.imports import import_setting

    path = _setting("KARNI_PHONE_NORMALIZER", None) or DEFAULT_PHONE_NORMALIZER
    normalizer = import_setting("KARNI_PHONE_NORMALIZER", path)
    return normalizer(value)


def _phone_message() -> str:
    code = phone_country_code()
    if code is None:
        return (
            "Enter the number in international format, e.g. +14155552671: a + and the "
            "country code, then the number (at most 15 digits). For national numbers "
            "such as 020 7946 0958, set KARNI_PHONE_COUNTRY_CODE."
        )
    return (
        "Enter a phone number: a national one, which gets +"
        f"{code} (KARNI_PHONE_COUNTRY_CODE), or + and the country code, then the "
        "number, e.g. +14155552671 (at most 15 digits)."
    )


def validate_e164(value: Any) -> None:
    """Reject a value that does not normalise to E.164 (the message names the setting)."""
    if value in (None, ""):
        return
    if not (isinstance(value, str) and E164.match(str(normalize_phone(value)))):
        raise ValidationError(_phone_message(), code="invalid_phone", params={"value": value})


class PhoneFormField(forms.CharField):
    """A form field that cleans a phone number to E.164 (:func:`normalize_phone`).

    So a form saves what the model stores, and an unchanged number written
    another way ("020 7946 0958" for ``+442079460958``) is not a change.
    """

    default_validators = [validate_e164]

    def to_python(self, value: Any) -> Any:
        return normalize_phone(super().to_python(value))


@deconstructible(path="karni.fields.E164Format")
class E164Format(Func):
    """True when the expression is an E.164 number: a regex on PostgreSQL, ``GLOB`` on SQLite.

    The condition of :class:`PhoneField`'s CHECK. Other databases get no
    check (``1 = 1``; ``karni.W964`` says so).
    """

    conditional = True
    output_field = models.BooleanField()
    arity = 1

    def as_postgresql(self, compiler: Any, connection: Any, **extra: Any) -> tuple[str, list[Any]]:
        sql, params = compiler.compile(self.get_source_expressions()[0])
        return f"{sql}::text ~ %s", [*params, E164.pattern]

    def as_sqlite(self, compiler: Any, connection: Any, **extra: Any) -> tuple[str, list[Any]]:
        sql, params = compiler.compile(self.get_source_expressions()[0])
        return (
            f"({sql} GLOB %s AND length({sql}) BETWEEN 3 AND 16 AND substr({sql}, 2) NOT GLOB %s)",
            [*params, "+[1-9]*", *params, *params, "*[^0-9]*"],
        )

    def as_sql(self, compiler: Any, connection: Any, **extra: Any) -> tuple[str, list[Any]]:
        return "1 = 1", []


class EmailField(KarniField, models.EmailField):
    """An email address; ``unique=True`` is case-insensitive (see the module docstring)."""

    case_insensitive_unique = True
    plain_django = "models.EmailField"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._pop_unique(kwargs)
        super().__init__(*args, **kwargs)

    def to_python(self, value: Any) -> Any:
        return normalize_email(super().to_python(value))

    def get_prep_value(self, value: Any) -> Any:
        return normalize_email(super().get_prep_value(value))

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        value = normalize_email(super().pre_save(model_instance, add))
        setattr(model_instance, self.attname, value)
        return value

    def karni_column(self) -> str:
        return f"EmailField: varchar({self.max_length}), domain lower-cased on save"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        self._unique_deconstruct(kwargs)
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        return NotImplemented  # the name rules already make example.com addresses


class SlugField(KarniField, models.SlugField):
    """A URL slug, unique among live rows, generated from ``populate_from``."""

    plain_django = "models.SlugField(unique=True)"
    #: Numbered suffixes tried before a random one.
    max_attempts = 50

    def __init__(self, *args: Any, populate_from: str | None = None, **kwargs: Any) -> None:
        self._pop_unique(kwargs, default=True)
        self.populate_from = populate_from
        if self.karni_unique:
            kwargs.setdefault("db_index", False)  # the unique constraint is the index
        if populate_from:
            kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        value = super().pre_save(model_instance, add)
        if value or not self.populate_from:
            return value
        source = model_instance
        for part in self.populate_from.split("__"):
            source = getattr(source, part, None)
        base = slugify(str(source or ""), allow_unicode=self.allow_unicode) or "item"
        value = self.unique_slug(model_instance, base) if self.karni_unique else base
        value = value[: self.max_length]
        setattr(model_instance, self.attname, value)
        return value

    def unique_slug(self, instance: Any, base: str) -> str:
        """``base``, or ``base-2``, ``base-3``, ... : the first one no live row holds."""
        model = type(instance)
        rows = model._base_manager.all()
        if is_soft_deletable(model):
            rows = rows.filter(deleted_at__isnull=True)
        if instance.pk is not None:
            rows = rows.exclude(pk=instance.pk)
        limit = self.max_length or 50
        for attempt in range(1, self.max_attempts + 1):
            suffix = "" if attempt == 1 else f"-{attempt}"
            candidate = base[: limit - len(suffix)].rstrip("-") + suffix
            if not rows.filter(**{self.attname: candidate}).exists():
                return candidate
        suffix = "-" + get_random_string(6, "abcdefghijklmnopqrstuvwxyz0123456789")
        return base[: limit - len(suffix)].rstrip("-") + suffix

    def karni_column(self) -> str:
        source = f" from {self.populate_from}" if self.populate_from else ""
        return f"SlugField: varchar({self.max_length}), generated{source} when empty"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        self._unique_deconstruct(kwargs, default=True)
        if self.karni_unique:  # db_index defaults to False here (the constraint indexes it)
            if self.db_index:
                kwargs["db_index"] = True
            else:
                kwargs.pop("db_index", None)
        if self.populate_from:  # blank defaults to True here (the slug is generated)
            kwargs["populate_from"] = self.populate_from
            if self.blank:
                kwargs.pop("blank", None)
            else:
                kwargs["blank"] = False
        return name, self._public_path(path), args, kwargs


class PhoneField(KarniField, models.CharField):
    """A phone number stored in E.164, checked by the database (see the module docstring)."""

    plain_django = "models.CharField(max_length=32)"
    default_validators = [validate_e164]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._pop_unique(kwargs)
        # Room for formatted input ("+1 (415) 555-2671"); the CHECK keeps stored values E.164.
        kwargs.setdefault("max_length", 32)
        super().__init__(*args, **kwargs)

    def to_python(self, value: Any) -> Any:
        return normalize_phone(super().to_python(value))

    def get_prep_value(self, value: Any) -> Any:
        return normalize_phone(super().get_prep_value(value))

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        value = normalize_phone(super().pre_save(model_instance, add))
        setattr(model_instance, self.attname, value)
        return value

    def formfield(self, **kwargs: Any) -> Any:
        return super().formfield(**{"form_class": PhoneFormField, **kwargs})

    def check_condition(self) -> Any:
        condition = Q(E164Format(F(self.name)))
        return condition | Q(**{self.name: ""}) if self.blank and not self.null else condition

    def karni_column(self) -> str:
        return "PhoneField: varchar, E.164 (+ and up to 15 digits), CHECK format"

    def backend_problem(self, connection: Any) -> tuple[str, str] | None:
        if connection.vendor in ("postgresql", "sqlite"):
            return None
        return "warning", "the E.164 CHECK (only PostgreSQL and SQLite get one)"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        self._unique_deconstruct(kwargs)
        if kwargs.get("max_length") == 32:
            kwargs.pop("max_length")
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        # Area code 555 is not assigned in the North American plan: never a real number.
        number = ctx.n if ctx.unique else ctx.random.randint(0, 9_999_999)
        return f"+1555{number:07d}"


class MarkdownField(KarniField, models.TextField):
    """Experimental. Long-form text written in markdown (see the module docstring).

    A ``TextField`` in the database, in forms and in search. The API publishes
    it as ``{"type": "string", "format": "markdown"}``, and that is the only
    difference a client sees.
    """

    plain_django = "models.TextField()"
    #: The OpenAPI ``format`` of its property in the API schema (what ``@karni/ui`` reads).
    openapi_format = "markdown"

    def karni_column(self) -> str:
        return "MarkdownField: text, markdown that @karni/ui renders sanitized"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        heading = ctx.fake.sentence(nb_words=3).rstrip(".")
        items = "\n".join(f"- {ctx.fake.sentence(nb_words=5)}" for _ in range(3))
        return ctx.fit(f"## {heading}\n\n{ctx.fake.paragraph(nb_sentences=3)}\n\n{items}")
