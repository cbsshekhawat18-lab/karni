"""The shared seed pool: one set of people and organisations for every part.

``karni seed`` runs :class:`OrganisationSeeder` and :class:`PersonSeeder`
once, before any part's seeders (a part's rows point at people). The people
get invented, real-sounding names, emails at example domains (members of an
organisation on its own ``.example`` domain), phones in a range kept for
fiction, a home address for every other one, and a third of them an
account (password ``karni-password``, email verified, the default roles of
a sign-up), linked to them.

A part's seeder picks people from the pool in a fixed order, so the same
person is the shop's customer, the CRM's contact and next week's guest::

    from karni import people

    class OrderSeeder(Seeder):
        class Meta:
            model = Order

        def seed(self, context):
            buyers = people.pool()
            return [
                context.create(1, person=buyers[i % len(buyers)])[0]
                for i in range(context.count)
            ]

The same ``--seed`` gives the same people, and a run after ``--reset``
finds the accounts the last one made by their email. The demo login is the
first person of the pool, so it has an account and every part's rows.

Override / escape hatch: a project's own ``PersonSeeder`` (in its
``seeds.py``, for ``people.Person``) replaces this one; ``Meta.count`` sets
how many people a run makes; :func:`pool` takes ``with_account``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from karni.seeding import DEMO_LOGIN, SeedContext, Seeder, cycled

__all__ = ["OrganisationSeeder", "PersonSeeder", "pool"]

GIVEN_NAMES: Final = (
    "Ana", "Ben", "Chloe", "Dev", "Elena", "Farid", "Grace", "Hiro", "Ines", "Jonas",
    "Kemi", "Lucas", "Maya", "Nikhil", "Olga", "Pablo", "Quinn", "Rosa", "Samir", "Tara",
    "Umar", "Vera", "Wen", "Yara", "Zoe",
)  # fmt: skip
FAMILY_NAMES: Final = (
    "Almeida", "Brooks", "Chen", "Diallo", "Eriksen", "Fischer", "Garcia", "Haddad", "Ito",
    "Jansen", "Kowalski", "Lopez", "Mensah", "Novak", "Okafor", "Patel", "Quintero",
    "Rossi", "Silva", "Tanaka", "Ueda", "Varga", "Weber", "Yilmaz", "Zhang",
)  # fmt: skip
ORGANISATIONS: Final = (
    "Alder Finch Studio", "Bluepine Freight", "Cobalt Harbor Supply", "Fernwood Design",
    "Granite Lane Partners", "Hollow Oak Bakery", "Juniper Field Clinic", "Kestrel Bay Travel",
    "Lumen Grove School", "Maple Ridge Builders", "Orchard Row Foods", "Pebble Creek Fitness",
    "Quarry Hill Labs", "Riverbend Books", "Saltmarsh Cycles", "Tidewater Florists",
)  # fmt: skip
TITLES: Final = (
    "Owner", "Office manager", "Head of sales", "Buyer", "Accountant", "Operations lead",
    "Founder", "Project manager",
)  # fmt: skip
#: Where people live: country, city, region, time zone, language.
PLACES: Final = (
    ("GB", "Leeds", "West Yorkshire", "Europe/London", "en"),
    ("US", "Portland", "Oregon", "America/Los_Angeles", "en"),
    ("DE", "Leipzig", "Saxony", "Europe/Berlin", "de"),
    ("FR", "Lyon", "Auvergne-Rhone-Alpes", "Europe/Paris", "fr"),
    ("IN", "Pune", "Maharashtra", "Asia/Kolkata", "en"),
    ("BR", "Curitiba", "Parana", "America/Sao_Paulo", "pt-BR"),
    ("JP", "Sapporo", "Hokkaido", "Asia/Tokyo", "ja"),
    ("NG", "Ibadan", "Oyo", "Africa/Lagos", "en"),
)
STREETS: Final = ("Mill Lane", "Station Road", "Park Avenue", "Church Street", "River Walk")
PERSONAL_DOMAINS: Final = ("example.com", "example.org", "example.net")


def pool(*, with_account: bool | None = None) -> list[Any]:
    """The live people, in the fixed order every part's seeders pick from.

    Ordered by email, then key, so the same seed gives the same order.
    ``with_account`` keeps only people with (``True``) or without
    (``False``) an account.
    """
    from karni.people.models import Person

    rows = Person.objects.filter(erased_at__isnull=True)
    if with_account is not None:
        rows = rows.filter(user__isnull=not with_account)
    return list(rows.order_by("email", "pk"))


def _phone(index: int) -> str:
    """A UK number in the range kept for drama (020 7946 0000 to 0999), never a real line."""
    return f"+44 20 7946 0{index % 1000:03d}"


class OrganisationSeeder(Seeder):
    """The organisations of the shared pool: about one for every four people."""

    class Meta:
        model = "people.Organisation"
        count: ClassVar[int | None] = None

    @classmethod
    def row_count(cls, default: int) -> int:
        count = getattr(cls.Meta, "count", None)
        return max(2, default // 4) if count is None else int(count)

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for index in range(context.count):
            name = cycled(ORGANISATIONS, index)
            rows += context.create(
                1,
                name=name,
                domain=f"{slugify(name)}.example",
                phone=_phone(500 + index),
                source="seed",
                merged_into=None,
            )
        return rows


class PersonSeeder(Seeder):
    """The people of the shared pool (see the module docstring)."""

    class Meta:
        model = "people.Person"
        count: ClassVar[int | None] = None

    def seed(self, context: SeedContext) -> list[Any]:
        from karni.people.models import Address, Membership, Organisation, Person

        organisations = list(Organisation.objects.order_by("name", "pk"))
        demo = (
            get_user_model()
            ._default_manager.filter(**{get_user_model().USERNAME_FIELD: DEMO_LOGIN})
            .filter(person__isnull=True)
            .first()
        )
        taken = set(Person._base_manager.values_list("email", flat=True))
        rows: list[Any] = []
        for index in range(context.count):
            given = GIVEN_NAMES[(index * 7) % len(GIVEN_NAMES)]
            family = FAMILY_NAMES[(index * 11) % len(FAMILY_NAMES)]
            round_ = index // (len(GIVEN_NAMES) * len(FAMILY_NAMES))
            country, city, region, zone, language = PLACES[index % len(PLACES)]
            organisation = (
                organisations[index % len(organisations)] if index % 2 and organisations else None
            )
            domain = (
                organisation.domain if organisation is not None else PERSONAL_DOMAINS[index % 3]
            )
            local = f"{given}.{family}{round_ + 1 if round_ else ''}".lower()
            email = f"{local}@{domain}"
            user = None
            if index == 0 and demo is not None:
                user = demo
                email = str(getattr(demo, "email", "") or email).lower()
                given = str(getattr(demo, "first_name", "") or given)
                family = str(getattr(demo, "last_name", "") or family)
            if email in taken:
                continue
            taken.add(email)
            person = context.create(
                1,
                given_name=given,
                family_name=family,
                display_name="",
                email=email,
                phone=_phone(index),
                organisation=organisation,
                user=None,
                time_zone=zone,
                language=language,
                source="seed",
                merged_into=None,
                erased_at=None,
            )[0]
            if index % 3 == 0:
                self.give_account(person, user)
            if organisation is not None:
                Membership.objects.create(
                    person=person, organisation=organisation, title=cycled(TITLES, index)
                )
            if index % 2 == 0:
                Address.objects.create(
                    person=person,
                    label="Home",
                    line1=f"{10 + index % 90} {STREETS[index % len(STREETS)]}",
                    city=city,
                    region=region,
                    postcode=f"{1000 + (index * 37) % 9000}",
                    country=country,
                    is_default_billing=True,
                    is_default_shipping=True,
                )
            rows.append(person)
        return rows

    def give_account(self, person: Any, user: Any) -> None:
        """Link ``user`` (or a new verified account with the person's email) to ``person``."""
        from karni.accounts.permissions import assign_role
        from karni.testing.factories import DEFAULT_PASSWORD

        model = get_user_model()
        if user is None:
            user = model._default_manager.filter(email=person.email).first()
        if user is None:
            user = model._default_manager.create_user(
                email=person.email,
                password=DEFAULT_PASSWORD,
                first_name=person.given_name,
                last_name=person.family_name,
                email_verified=True,
            )
            for role in getattr(settings, "KARNI_ACCOUNTS_DEFAULT_ROLES", None) or []:
                assign_role(user, role)
        elif not getattr(user, "email_verified", True):
            model._default_manager.filter(pk=user.pk).update(email_verified=True)
        person.refresh_from_db(fields=["user"])
        if person.user_id is None:
            person.user = user
            person.save(update_fields=["user"])
