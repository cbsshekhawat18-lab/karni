"""Realistic field values inferred from a field's name and type — one engine for tests and seeds.

:mod:`karni.testing.factories` (test rows) and :mod:`karni.seeding`
(``karni seed`` demo rows) both ask this module what to put in a field, so a
field called ``email`` gets an email, ``price`` gets money and ``starts_at``
a near-future datetime everywhere::

    from karni.testing.values import ValueInference

    values = ValueInference()
    values.value(Event, Event._meta.get_field("starts_at"))   # a datetime 1–60 days ahead
    values.declaration(Event, field, unique=True)             # a factory-boy declaration

**Resolution.** The first :class:`NameRule` in :attr:`ValueInference.rules`
whose pattern matches the (lower-cased) field name *and* whose field types
match wins; otherwise the field's type decides (the ``text``/``integer``/…
methods). A ``unique`` value always embeds the row's sequence number, so
uniqueness never depends on luck. Values that depend on another field read it
from the row being built: ``email`` follows ``first_name``/``last_name``,
``slug`` follows ``title``/``name`` and ``ends_at`` follows ``starts_at``.

**Determinism.** Every random choice comes from Faker's shared generator,
which ``factory.random.reseed_random(seed)`` reseeds (``karni seed --seed N``
and the ``karni`` pytest plugin per test do exactly that). Datetimes are
relative to :meth:`ValueInference.now` — the current time for tests, a fixed
anchor for seeds. Emails and URLs use the reserved ``example.com/.org/.net``
domains, so demo data can never reach a real inbox.

Override / escape hatches: subclass :class:`ValueInference` and change
``rules`` (prepend your own :class:`NameRule`), ``locale`` or any type method,
then hand it to a builder (``FactoryBuilder(values=MyValues())``); an explicit
factory or a seeder declaration always beats inference.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
import string
import uuid as uuidlib
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fnmatch import fnmatchcase
from functools import cache
from typing import Any, ClassVar, Final

import factory
from django.core import validators
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from faker import Faker

__all__ = [
    "MISSING",
    "NAME_RULES",
    "NameRule",
    "ValueContext",
    "ValueInference",
    "unique_field_names",
]

MISSING: Final = object()
"""Returned by :meth:`ValueInference.declaration` for a field type it cannot fill."""

SAFE_DOMAINS: Final = ("example.com", "example.org", "example.net")
"""RFC 2606 domains: generated emails and URLs never reach a real host."""

_INT_RANGES: Final[tuple[tuple[type[models.Field[Any, Any]], int, int], ...]] = (
    (models.PositiveSmallIntegerField, 0, 32767),
    (models.PositiveBigIntegerField, 0, 9223372036854775807),
    (models.PositiveIntegerField, 0, 2147483647),
    (models.SmallIntegerField, -32768, 32767),
    (models.BigIntegerField, -9223372036854775808, 9223372036854775807),
    (models.IntegerField, -2147483648, 2147483647),
)

_TEXT: Final = (models.CharField, models.TextField)
_STRICT_TEXT: Final = (models.EmailField, models.URLField, models.SlugField)
_INTEGER: Final = (models.IntegerField,)
_NUMBER: Final = (models.IntegerField, models.DecimalField, models.FloatField)


@dataclass(frozen=True)
class ValueContext:
    """Everything a value generator may use for one field of one row."""

    model: type[models.Model]
    field: Any
    #: The row's sequence number (factory-boy's ``n``); unique values embed it.
    n: int
    #: The value must differ from every other row's (``unique``/a unique constraint).
    unique: bool
    fake: Faker
    #: The anchor "now": the current time in tests, a fixed instant in seeds.
    now: dt.datetime
    #: The row being built (other fields' values), or ``None`` outside a factory.
    row: Any = None

    @property
    def random(self) -> Any:
        """Faker's shared ``random.Random`` (reseeded by ``factory.random.reseed_random``)."""
        return self.fake.random

    @property
    def model_word(self) -> str:
        """The last word of the model name, lower-cased: ``EventCategory`` → ``category``."""
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+", self.model.__name__)
        return (parts[-1] if parts else self.model.__name__).lower()

    def other(self, name: str) -> Any:
        """Another field's value on the row being built (``None`` when unknown)."""
        if self.row is None:
            return None
        try:
            return getattr(self.row, name)
        except (AttributeError, KeyError, TypeError):
            return None

    def fit(self, text: str, *, sep: str = " ") -> str:
        """``text`` within ``max_length``; a unique value keeps ``<sep><n>`` at the end."""
        suffix = f"{sep}{self.n}" if self.unique else ""
        limit = getattr(self.field, "max_length", None)
        if not limit:
            return text + suffix
        room = max(limit - len(suffix), 0)
        head = text[:room].rstrip(" -_.,;:") if len(text) > room else text
        return (head + suffix)[-limit:] if len(head + suffix) > limit else head + suffix

    def bounds(self, low: float, high: float) -> tuple[float, float]:
        """``[low, high]`` narrowed by the field's type range and Min/MaxValueValidators."""
        for kind, type_low, type_high in _INT_RANGES:
            if isinstance(self.field, kind):
                low, high = max(low, type_low), min(high, type_high)
                break
        if isinstance(self.field, models.DecimalField):
            places = self.field.decimal_places or 0
            whole = max((self.field.max_digits or 10) - places, 0)
            top = float(Decimal(10) ** whole - Decimal(1).scaleb(-places))
            low, high = max(low, -top), min(high, top)
        for validator in getattr(self.field, "validators", ()):
            limit = getattr(validator, "limit_value", None)
            if callable(limit) or limit is None:
                continue
            if isinstance(validator, validators.MinValueValidator):
                low = max(low, limit)
            elif isinstance(validator, validators.MaxValueValidator):
                high = min(high, limit)
        if low > high:
            low = high
        return low, high


Generator = Callable[[ValueContext], Any]


@dataclass(frozen=True)
class NameRule:
    """A value for fields whose name matches ``patterns`` and whose type is one of ``kinds``.

    ``patterns`` are shell-style (``fnmatch``) patterns over the lower-cased
    field name, e.g. ``("email", "*_email")``. ``exclude`` lists field types
    the rule never applies to (an ``EmailField`` named ``title`` keeps its
    email).
    """

    label: str
    patterns: tuple[str, ...]
    kinds: tuple[type[Any], ...]
    make: Generator
    exclude: tuple[type[Any], ...] = field(default=())

    def matches(self, model_field: Any) -> bool:
        if not isinstance(model_field, self.kinds) or isinstance(model_field, self.exclude):
            return False
        name = model_field.name.lower()
        return any(fnmatchcase(name, pattern) for pattern in self.patterns)


# --- generators -------------------------------------------------------------------------------

_PERSON_MODELS: Final = frozenset(
    "user person member customer client contact author speaker attendee organizer organiser "
    "employee staff student teacher instructor guest player profile patient doctor driver "
    "owner host artist writer participant volunteer candidate".split()
)
_ORG_MODELS: Final = frozenset(
    "company organization organisation org vendor supplier brand publisher team club agency "
    "firm partner sponsor business store shop merchant school university".split()
)
_PLACE_MODELS: Final = frozenset(
    "venue location place room hall building site office branch warehouse stadium theater "
    "theatre restaurant hotel".split()
)
_TAG_MODELS: Final = frozenset(
    "tag category label topic genre skill keyword interest badge department type kind".split()
)
_PRODUCT_MODELS: Final = frozenset(
    "product item plan package course book service menu dish".split()
)
_PLACE_SUFFIXES: Final = (
    "Hall", "Center", "Arena", "Theatre", "Pavilion", "Studio", "Gardens", "Auditorium",
)  # fmt: skip
_PRODUCT_ADJECTIVES: Final = (
    "Premium", "Classic", "Deluxe", "Compact", "Smart", "Eco", "Pro", "Essential", "Vintage",
)  # fmt: skip


def _ascii(text: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", text.lower())


def _first_last(ctx: ValueContext) -> tuple[str, str]:
    first, last = ctx.other("first_name"), ctx.other("last_name")
    if isinstance(first, str) and first and isinstance(last, str) and last:
        return first, last
    return ctx.fake.first_name(), ctx.fake.last_name()


def _email(ctx: ValueContext) -> str:
    first, last = _first_last(ctx)
    local = _ascii(f"{first}.{last}") or "user"
    if ctx.unique:
        local += str(ctx.n)
    domain = ctx.random.choice(SAFE_DOMAINS)
    address = f"{local}@{domain}"
    limit = getattr(ctx.field, "max_length", None)
    if limit and len(address) > limit:
        address = f"u{ctx.n}@{domain}"[-limit:]
    return address


def _person(ctx: ValueContext) -> str:
    first, last = _first_last(ctx)
    return ctx.fit(f"{first} {last}")


def _name(ctx: ValueContext) -> str:
    word = ctx.model_word
    if word in _PERSON_MODELS:
        return _person(ctx)
    if word in _ORG_MODELS:
        return ctx.fit(ctx.fake.company())
    if word in _PLACE_MODELS:
        return ctx.fit(f"{ctx.fake.last_name()} {ctx.random.choice(_PLACE_SUFFIXES)}")
    if word in _TAG_MODELS:
        return ctx.fit(ctx.fake.word().capitalize())
    if word in _PRODUCT_MODELS:
        adjective = ctx.random.choice(_PRODUCT_ADJECTIVES)
        return ctx.fit(f"{adjective} {ctx.fake.word().capitalize()}")
    return ctx.fit(" ".join(word.capitalize() for word in ctx.fake.words(2)))


def _title(ctx: ValueContext) -> str:
    return ctx.fit(string.capwords(ctx.fake.catch_phrase()))


def _prose(ctx: ValueContext) -> str:
    if isinstance(ctx.field, models.TextField):
        return ctx.fit("\n\n".join(ctx.fake.paragraphs(nb=2)))
    return ctx.fit(ctx.fake.sentence(nb_words=8))


def _username(ctx: ValueContext) -> str:
    return ctx.fit(ctx.fake.user_name(), sep="")


def _phone(ctx: ValueContext) -> str:
    number = ctx.fake.phone_number()
    limit = getattr(ctx.field, "max_length", None) or 32
    if len(number) > limit:
        number = ctx.fake.numerify("#" * min(limit, 10))
    return number


def _code(ctx: ValueContext) -> str:
    return ctx.fit(ctx.fake.bothify("??-####").upper(), sep="-")


def _token(ctx: ValueContext) -> str:
    return ctx.fit(ctx.fake.sha1(), sep="")


def _slug(ctx: ValueContext) -> str:
    source = ctx.other("title") or ctx.other("name")
    text = source if isinstance(source, str) and source else " ".join(ctx.fake.words(3))
    return ctx.fit(slugify(text) or "item", sep="-")


def _url(ctx: ValueContext) -> str:
    domain = ctx.random.choice(SAFE_DOMAINS)
    path = slugify(" ".join(ctx.fake.words(2)))
    return ctx.fit(f"https://{domain}/{path}", sep="-")


def _color(ctx: ValueContext) -> str:
    return ctx.fit(ctx.fake.hex_color(), sep="")


def _plain(method: str) -> Generator:
    """A generator calling ``Faker.<method>()`` and fitting the result."""

    def make(ctx: ValueContext) -> str:
        return ctx.fit(str(getattr(ctx.fake, method)()))

    make.__name__ = method
    return make


def _number(low: float, high: float, *, places: int | None = None) -> Generator:
    """A number in ``[low, high]`` (narrowed by the field), typed after the field."""

    def make(ctx: ValueContext) -> Any:
        lo, hi = ctx.bounds(low, high)
        if ctx.unique:
            return _sequence_number(ctx, lo, hi)
        if isinstance(ctx.field, models.DecimalField):
            quantum = Decimal(1).scaleb(-(ctx.field.decimal_places or 0))
            raw = Decimal(str(round(ctx.random.uniform(lo, hi), 6)))
            return min(max(raw.quantize(quantum), _dec(lo, quantum)), _dec(hi, quantum, down=True))
        if isinstance(ctx.field, models.FloatField):
            return round(ctx.random.uniform(lo, hi), places if places is not None else 2)
        return ctx.random.randint(int(lo), int(hi))

    return make


def _dec(value: float, quantum: Decimal, *, down: bool = False) -> Decimal:
    rounding = ROUND_FLOOR if down else ROUND_CEILING
    return Decimal(str(value)).quantize(quantum, rounding=rounding)


def _sequence_number(ctx: ValueContext, low: float, high: float) -> Any:
    start, span = int(low), max(int(high) - int(low) + 1, 1)
    value = start + ctx.n % span
    if isinstance(ctx.field, models.DecimalField):
        return Decimal(value).quantize(Decimal(1).scaleb(-(ctx.field.decimal_places or 0)))
    if isinstance(ctx.field, models.FloatField):
        return float(value)
    return value


def _position(ctx: ValueContext) -> Any:
    low, high = ctx.bounds(0, 2147483647)
    return _sequence_number(ctx, low, high)


def _year(ctx: ValueContext) -> int:
    return ctx.random.randint(ctx.now.year - 30, ctx.now.year)


def _trim(ctx: ValueContext, value: dt.datetime) -> dt.datetime:
    return value.replace(second=0, microsecond=0)


def _future(ctx: ValueContext) -> Any:
    days = ctx.random.randint(1, 60)
    if isinstance(ctx.field, models.DateTimeField):
        hour, minute = ctx.random.randint(9, 20), ctx.random.choice((0, 15, 30, 45))
        moment = ctx.now + dt.timedelta(days=days)
        return _trim(ctx, moment.replace(hour=hour, minute=minute))
    return ctx.now.date() + dt.timedelta(days=days)


def _past(ctx: ValueContext) -> Any:
    minutes = ctx.random.randint(60, 90 * 24 * 60)
    moment = ctx.now - dt.timedelta(minutes=minutes)
    if isinstance(ctx.field, models.DateTimeField):
        return _trim(ctx, moment)
    return moment.date()


def _birth(ctx: ValueContext) -> Any:
    days = ctx.random.randint(18 * 365, 80 * 365)
    moment = ctx.now - dt.timedelta(days=days)
    if isinstance(ctx.field, models.DateTimeField):
        return _trim(ctx, moment.replace(hour=0, minute=0))
    return moment.date()


_START_FOR_END: Final = {
    "ends_at": "starts_at",
    "end_at": "start_at",
    "end": "start",
    "end_time": "start_time",
    "end_date": "start_date",
    "ends_on": "starts_on",
    "finishes_at": "starts_at",
    "closes_at": "opens_at",
    "check_out": "check_in",
    "returns_at": "departs_at",
}


def _end(ctx: ValueContext) -> Any:
    start_name = _START_FOR_END.get(ctx.field.name.lower(), "")
    start = ctx.other(start_name) if start_name else None
    if isinstance(start, dt.datetime):
        hours = ctx.random.randint(1, 4)
        if isinstance(ctx.field, models.DateTimeField):
            return start + dt.timedelta(hours=hours)
        return start.date() + dt.timedelta(days=ctx.random.randint(0, 3))
    if isinstance(start, dt.date):
        days = ctx.random.randint(0, 5)
        if isinstance(ctx.field, models.DateTimeField):
            moment = dt.datetime.combine(start, dt.time(18), tzinfo=ctx.now.tzinfo)
            return moment + dt.timedelta(days=days)
        return start + dt.timedelta(days=days)
    return _future(ctx)


def _chance(probability: float) -> Generator:
    def make(ctx: ValueContext) -> bool:
        return bool(ctx.random.random() < probability)

    return make


def _minutes(ctx: ValueContext) -> dt.timedelta:
    return dt.timedelta(minutes=ctx.random.choice((15, 30, 45, 60, 90, 120, 180)))


def _clock(low: int, high: int) -> Generator:
    def make(ctx: ValueContext) -> dt.time:
        return dt.time(ctx.random.randint(low, high), ctx.random.choice((0, 15, 30, 45)))

    return make


_DATES: Final = (models.DateField, models.DateTimeField)  # DateTimeField subclasses DateField

NAME_RULES: tuple[NameRule, ...] = (
    # --- people and identity -----------------------------------------------------------------
    NameRule("first name", ("first_name", "firstname", "given_name"), _TEXT, _plain("first_name"),
             _STRICT_TEXT),
    NameRule("last name", ("last_name", "lastname", "surname", "family_name"), _TEXT,
             _plain("last_name"), _STRICT_TEXT),
    NameRule("person name", ("full_name", "display_name", "contact_name", "*_full_name",
                             "author_name", "owner_name", "customer_name"), _TEXT, _person,
             _STRICT_TEXT),
    NameRule("username", ("username", "user_name", "handle", "login", "nickname", "screen_name"),
             _TEXT, _username, _STRICT_TEXT),
    NameRule("email", ("email", "*_email", "email_address", "mail"), _TEXT, _email,
             (models.URLField, models.SlugField)),
    NameRule("phone", ("phone", "*_phone", "phone_number", "mobile", "telephone", "tel", "fax"),
             _TEXT, _phone, _STRICT_TEXT),
    NameRule("company", ("company", "company_name", "organization", "organisation", "employer",
                         "brand", "publisher", "vendor", "supplier"), _TEXT,
             _plain("company"), _STRICT_TEXT),
    NameRule("job title", ("job", "job_title", "occupation", "position", "designation"), _TEXT,
             _plain("job"), _STRICT_TEXT),
    # --- text --------------------------------------------------------------------------------
    NameRule("name", ("name", "*_name"), _TEXT, _name, _STRICT_TEXT),
    NameRule("title", ("title", "*_title", "headline", "subject", "heading"), _TEXT, _title,
             _STRICT_TEXT),
    NameRule("prose", ("description", "*_description", "body", "content", "text", "bio",
                       "about", "summary", "details", "notes", "note", "comment", "comments",
                       "message", "overview", "abstract", "excerpt", "instructions", "remarks"),
             _TEXT, _prose, _STRICT_TEXT),
    NameRule("street address", ("address", "*_address", "street", "street_address",
                                "address_line*", "line1", "line2"), _TEXT,
             _plain("street_address"), (*_STRICT_TEXT, models.GenericIPAddressField)),
    NameRule("city", ("city", "town", "*_city"), _TEXT, _plain("city"), _STRICT_TEXT),
    NameRule("state", ("state", "province", "region", "county"), _TEXT, _plain("state"),
             _STRICT_TEXT),
    NameRule("country code", ("country_code",), _TEXT, _plain("country_code"), _STRICT_TEXT),
    NameRule("country", ("country", "*_country", "nationality"), _TEXT, _plain("country"),
             _STRICT_TEXT),
    NameRule("postcode", ("zip", "zipcode", "zip_code", "postal_code", "postcode", "pincode",
                          "pin_code"), _TEXT, _plain("postcode"), _STRICT_TEXT),
    NameRule("currency", ("currency", "currency_code"), _TEXT, _plain("currency_code"),
             _STRICT_TEXT),
    NameRule("language", ("language", "language_code", "locale", "lang"), _TEXT,
             _plain("language_code"), _STRICT_TEXT),
    NameRule("timezone", ("timezone", "time_zone", "tz"), _TEXT, _plain("timezone"), _STRICT_TEXT),
    NameRule("color", ("color", "colour", "*_color", "*_colour"), _TEXT, _color, _STRICT_TEXT),
    NameRule("code", ("code", "*_code", "sku", "reference", "ref", "*_number", "order_number",
                      "invoice_number"), (models.CharField,), _code, _STRICT_TEXT),
    NameRule("token", ("token", "*_token", "key", "*_key", "secret", "hash", "checksum"),
             (models.CharField,), _token, _STRICT_TEXT),
    NameRule("url", ("url", "*_url", "website", "homepage", "link", "*_link", "site"),
             (models.CharField,), _url, (models.EmailField, models.SlugField)),
    NameRule("slug", ("slug", "*_slug"), (models.CharField,), _slug,
             (models.EmailField, models.URLField)),
    # --- numbers -----------------------------------------------------------------------------
    NameRule("money", ("price", "*_price", "amount", "*_amount", "cost", "*_cost", "total",
                       "subtotal", "fee", "*_fee", "balance", "budget", "salary", "revenue",
                       "rate", "fare"), _NUMBER, _number(5, 500)),
    NameRule("percent", ("percent", "percentage", "*_percent", "progress", "completion",
                         "discount", "tax", "tax_rate", "vat"), _NUMBER, _number(0, 30)),
    NameRule("rating", ("rating", "stars", "score", "*_rating"), _NUMBER, _number(1, 5)),
    NameRule("capacity", ("capacity", "seats", "max_attendees", "attendees", "guests",
                          "max_participants", "spots"), _NUMBER, _number(10, 500)),
    NameRule("quantity", ("quantity", "qty", "stock", "inventory", "units", "count", "*_count",
                          "items"), _NUMBER, _number(1, 50)),
    NameRule("age", ("age",), _NUMBER, _number(18, 80)),
    NameRule("year", ("year", "*_year"), _INTEGER, _year),
    NameRule("month", ("month",), _INTEGER, _number(1, 12)),
    NameRule("priority", ("priority", "level", "tier"), _INTEGER, _number(1, 5)),
    NameRule("position", ("position", "order", "sort_order", "ordering", "rank", "sequence",
                          "index", "weight_order"), _INTEGER, _position),
    NameRule("minutes", ("minutes", "*_minutes", "duration"), _NUMBER, _number(15, 240)),
    NameRule("popularity", ("views", "likes", "followers", "downloads", "*_views", "*_likes"),
             _NUMBER, _number(0, 10_000)),
    NameRule("weight", ("weight", "height", "width", "length", "depth"), _NUMBER,
             _number(1, 100)),
    NameRule("latitude", ("latitude", "lat"), (models.FloatField, models.DecimalField),
             _number(-60, 70, places=6)),
    NameRule("longitude", ("longitude", "lng", "lon", "long"),
             (models.FloatField, models.DecimalField), _number(-180, 180, places=6)),
    # --- dates and times ---------------------------------------------------------------------
    NameRule("birth date", ("birth_date", "birthdate", "birthday", "date_of_birth", "dob",
                            "born_on", "born_at"), _DATES, _birth),
    NameRule("end", tuple(_START_FOR_END), _DATES, _end),
    NameRule("near future", ("starts_at", "start_at", "start", "start_time", "start_date",
                             "starts_on", "begins_at", "scheduled_at", "scheduled_for", "due",
                             "due_at", "due_date", "deadline", "expires_at", "expiry",
                             "expiry_date", "valid_until", "opens_at", "departs_at", "check_in",
                             "event_date", "renews_at", "*_due"), _DATES, _future),
    NameRule("recent past", ("created*", "updated*", "modified*", "published*", "posted*",
                             "sent_at", "joined*", "date_joined", "registered*", "last_login",
                             "last_seen*", "paid_at", "completed_at", "approved_at",
                             "verified_at", "*_on"), _DATES, _past),
    NameRule("opening time", ("opens", "opening_time", "start_time"), (models.TimeField,),
             _clock(8, 11)),
    NameRule("closing time", ("closes", "closing_time", "end_time"), (models.TimeField,),
             _clock(17, 22)),
    # --- booleans ----------------------------------------------------------------------------
    NameRule("mostly on", ("is_active", "active", "enabled", "is_enabled", "is_published",
                           "published", "visible", "is_visible", "is_public", "public",
                           "available", "is_available", "in_stock"), (models.BooleanField,),
             _chance(0.8)),
    NameRule("mostly off", ("is_deleted", "deleted", "archived", "is_archived", "blocked",
                            "is_blocked", "banned", "is_banned", "hidden", "is_hidden",
                            "is_staff", "is_superuser", "is_admin"), (models.BooleanField,),
             _chance(0.1)),
)  # fmt: skip
"""The built-in name rules, first match wins (see :class:`NameRule`)."""


def unique_field_names(model: type[models.Model]) -> frozenset[str]:
    """Fields whose value must differ per row: ``unique=True`` and every unique constraint's."""
    names: set[str] = set()
    meta = model._meta
    for model_field in meta.concrete_fields:
        if model_field.unique and not model_field.primary_key:
            names.add(model_field.name)
    for together in meta.unique_together:
        names.update(together)
    for constraint in meta.constraints:
        if isinstance(constraint, models.UniqueConstraint):
            names.update(constraint.fields)
    return frozenset(names)


@cache
def _faker(locale: str) -> Faker:
    return Faker(locale)


class ValueInference:
    """Field values from names and types. Subclass to change any rule (see the module docs).

    :param now: the anchor every relative date uses — a datetime, a function
        returning one, or ``None`` for :func:`django.utils.timezone.now` at
        generation time.
    """

    rules: ClassVar[tuple[NameRule, ...]] = NAME_RULES
    locale: ClassVar[str] = "en_US"

    def __init__(self, *, now: dt.datetime | Callable[[], dt.datetime] | None = None) -> None:
        self._now = now

    @property
    def fake(self) -> Faker:
        """The Faker instance (one per locale; randomness is Faker's shared generator)."""
        return _faker(self.locale)

    def now(self) -> dt.datetime:
        """The anchor for relative dates."""
        if self._now is None:
            return timezone.now()
        if callable(self._now):
            return self._now()
        return self._now

    # --- resolution ------------------------------------------------------------------------

    def rule_for(self, model_field: Any) -> NameRule | None:
        """The first rule matching ``model_field``, or ``None``."""
        for rule in self.rules:
            if rule.matches(model_field):
                return rule
        return None

    def generator(self, model: type[models.Model], model_field: Any) -> Generator | None:
        """The function producing ``model_field``'s value, or ``None`` for an unknown type."""
        rule = self.rule_for(model_field)
        if rule is not None:
            return rule.make
        return self.type_generator(model_field)

    def type_generator(self, model_field: Any) -> Generator | None:
        """The type default for ``model_field`` (no name rule matched)."""
        checks: tuple[tuple[type[Any] | tuple[type[Any], ...], Generator], ...] = (
            (models.EmailField, self.email),
            (models.URLField, self.url),
            (models.GenericIPAddressField, self.ip),
            (models.SlugField, self.slug),
            (models.TextField, self.long_text),
            (models.CharField, self.text),
            (models.BooleanField, self.boolean),
            (models.DecimalField, self.decimal),
            (models.FloatField, self.floating),
            (models.IntegerField, self.integer),
            (models.DateTimeField, self.datetime),
            (models.DateField, self.date),
            (models.TimeField, self.time),
            (models.DurationField, self.duration),
            (models.UUIDField, self.uuid),
            (models.JSONField, self.json),
            (models.BinaryField, self.binary),
        )
        for kinds, make in checks:
            if isinstance(model_field, kinds):
                return make
        return None

    def context(
        self, model: type[models.Model], model_field: Any, n: int, *, unique: bool, row: Any = None
    ) -> ValueContext:
        return ValueContext(model, model_field, n, unique, self.fake, self.now(), row)

    def declaration(self, model: type[models.Model], model_field: Any, *, unique: bool) -> Any:
        """A factory-boy declaration for ``model_field``, or :data:`MISSING`."""
        make = self.generator(model, model_field)
        if make is None:
            return MISSING
        inference = self

        def evaluate(row: Any, n: int) -> Any:
            return make(inference.context(model, model_field, n, unique=unique, row=row))

        return factory.LazyAttributeSequence(evaluate)

    def value(
        self,
        model: type[models.Model],
        model_field: Any,
        n: int = 0,
        *,
        unique: bool = False,
        row: Any = None,
    ) -> Any:
        """One value for ``model_field`` outside a factory (``MISSING`` for an unknown type)."""
        make = self.generator(model, model_field)
        if make is None:
            return MISSING
        return make(self.context(model, model_field, n, unique=unique, row=row))

    # --- type defaults (override any of them) ------------------------------------------------

    def text(self, ctx: ValueContext) -> str:
        words = ctx.fake.words(ctx.random.randint(2, 3))
        return ctx.fit(" ".join(words).capitalize())

    def long_text(self, ctx: ValueContext) -> str:
        return ctx.fit(ctx.fake.paragraph(nb_sentences=3))

    def email(self, ctx: ValueContext) -> str:
        return _email(ctx)

    def url(self, ctx: ValueContext) -> str:
        return _url(ctx)

    def slug(self, ctx: ValueContext) -> str:
        return _slug(ctx)

    def ip(self, ctx: ValueContext) -> str:
        protocol = str(getattr(ctx.field, "protocol", "both")).lower()
        n = ctx.n if ctx.unique else ctx.random.randint(1, 2**16)
        if protocol == "ipv6":
            return str(ipaddress.IPv6Address(0x20010DB8 << 96 | n))
        return str(ipaddress.IPv4Address(0x0A000000 + n % 2**24))

    def boolean(self, ctx: ValueContext) -> bool:
        return bool(ctx.random.random() < 0.5)

    def integer(self, ctx: ValueContext) -> int:
        if ctx.unique:
            low, high = ctx.bounds(1, 2**63 - 1)
            return int(_sequence_number(ctx, low, high))
        low, high = ctx.bounds(1, 100)
        return ctx.random.randint(int(low), int(high))

    def decimal(self, ctx: ValueContext) -> Decimal:
        value: Decimal = _number(1, 1000)(ctx)
        return value

    def floating(self, ctx: ValueContext) -> float:
        value: float = _number(0, 1000)(ctx)
        return value

    def datetime(self, ctx: ValueContext) -> dt.datetime:
        minutes = ctx.random.randint(-30 * 24 * 60, 30 * 24 * 60)
        return _trim(ctx, ctx.now + dt.timedelta(minutes=minutes))

    def date(self, ctx: ValueContext) -> dt.date:
        return ctx.now.date() + dt.timedelta(days=ctx.random.randint(-30, 30))

    def time(self, ctx: ValueContext) -> dt.time:
        value: dt.time = _clock(8, 20)(ctx)
        return value

    def duration(self, ctx: ValueContext) -> dt.timedelta:
        return _minutes(ctx)

    def uuid(self, ctx: ValueContext) -> uuidlib.UUID:
        return uuidlib.UUID(int=ctx.random.getrandbits(128), version=4)

    def json(self, ctx: ValueContext) -> Any:
        return {"n": ctx.n}

    def binary(self, ctx: ValueContext) -> bytes:
        return b""
