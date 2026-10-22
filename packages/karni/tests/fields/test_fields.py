"""Field behaviour: migrations stay stable, values are normalised, the layers above agree."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps as global_apps
from django.db import connection, models
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.questioner import MigrationQuestioner
from django.db.migrations.state import ProjectState
from django.test.utils import isolate_apps
from rest_framework.exceptions import ValidationError

from karni.api.search.simple import SimpleSearchProvider
from karni.api.serializers import build_serializer
from karni.exceptions import KarniImproperlyConfigured
from karni.fields import (
    CountryField,
    CurrencyField,
    EmailField,
    JSONField,
    MoneyField,
    PercentField,
    PhoneField,
    QuantityField,
    SearchField,
    SlugField,
    is_unique,
    normalize_phone,
)
from karni.meta import natural_key
from karni.testing.factories import create
from tests.fieldsapp.models import Account, Customer, Membership, Product

# migrations: deconstruct, autodetector, historical models


FIELDS: list[Any] = [
    MoneyField(currency="EUR", min_value=0),
    MoneyField(currency_field="currency"),
    PercentField(min_value=-50, max_value=50),
    QuantityField(default=0),
    EmailField(unique=True),
    SlugField(populate_from="name"),
    SlugField(unique=False, max_length=80),
    PhoneField(blank=True),
    CountryField(codes=["DE", "FR"], extra_codes=["XK"]),
    CurrencyField(default="EUR"),
    JSONField(default=dict, queried=True),
    SearchField(sources=["name"], config="english", weights={"name": "A"}),
]


@pytest.mark.parametrize("field", FIELDS, ids=lambda f: type(f).__name__)
def test_deconstruct_round_trips_under_a_stable_path(field: Any) -> None:
    name, path, args, kwargs = field.deconstruct()
    assert path == f"karni.fields.{type(field).__name__}"
    rebuilt = type(field)(*args, **kwargs)
    assert rebuilt.deconstruct()[1:] == (path, args, kwargs)


def _fieldsapp_operations(from_state: ProjectState) -> list[Any]:
    changes = MigrationAutodetector(
        from_state,
        ProjectState.from_apps(global_apps),
        MigrationQuestioner(specified_apps={"fieldsapp"}),
    ).changes(graph=MigrationGraph(), trim_to_apps={"fieldsapp"})
    return [op for migration in changes.get("fieldsapp", []) for op in migration.operations]


def test_migrations_are_stable_and_carry_every_constraint() -> None:
    """makemigrations writes the Karni constraints once, then sees no change."""
    operations = _fieldsapp_operations(ProjectState())
    names = {getattr(op, "name", "") for op in operations}
    assert {"Product", "Customer", "Account", "Membership", "LogEntry"} <= names
    added = [
        getattr(op, "constraint", None) or getattr(op, "index", None)
        for op in operations
        if type(op).__name__ in ("AddConstraint", "AddIndex")
    ]
    created = [
        item
        for op in operations
        if type(op).__name__ == "CreateModel"
        for item in (op.options.get("constraints", []) + op.options.get("indexes", []))
    ]
    objects = {item.name for item in [*added, *created] if item is not None}
    assert any(name.endswith("_uniq") and "customer_email" in name for name in objects)
    assert any(name.endswith("_gin") for name in objects)
    assert any(name.endswith("_brin") for name in objects)

    state = ProjectState()
    for operation in operations:
        operation.state_forwards("fieldsapp", state)
    assert _fieldsapp_operations(state) == []


def test_historical_models_build_the_same_tables() -> None:
    """The models migrations render (StateApps) produce exactly the real models' DDL."""
    state = ProjectState.from_apps(global_apps)
    historical = state.apps.get_model("fieldsapp", "Customer")

    def ddl(model: Any) -> list[str]:
        editor = connection.schema_editor(collect_sql=True)  # collect only, never executed
        editor.deferred_sql = []
        editor.create_model(model)
        return [*editor.collected_sql, *(str(sql) for sql in editor.deferred_sql)]

    assert ddl(historical) == ddl(Customer)
    assert not historical._meta.get_field("email").unique  # never a column-level UNIQUE


# values: normalisation and generation


def test_email_domain_is_lower_cased_and_local_part_kept() -> None:
    field = Customer._meta.get_field("email")
    assert field.to_python("  Alice.Smith@Example.COM ") == "Alice.Smith@example.com"
    assert not Customer._meta.get_field("email").unique
    assert is_unique(Customer._meta.get_field("email"))


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("+44 (0)20 7946 0958", "+442079460958"),
        ("0044 20 7946 0958", "+442079460958"),
        ("+1 (415) 555-2671", "+14155552671"),
        ("+91.98765.43210", "+919876543210"),
        ("415 555 2671", "415 555 2671"),  # no country code: left for validation to reject
    ],
)
def test_phone_numbers_normalise_to_e164(raw: str, stored: str) -> None:
    assert normalize_phone(raw) == stored


@pytest.mark.django_db
def test_saving_normalises_and_the_check_backs_it() -> None:
    product = Product.objects.create(
        name="Desk Lamp", price=Decimal("10"), phone="+1 (415) 555-2671", made_in="de"
    )
    product.refresh_from_db()
    assert (product.phone, product.made_in) == ("+14155552671", "DE")
    customer = Customer.objects.create(email="Alice@Example.COM")
    assert customer.email == "Alice@example.com"
    assert Customer.objects.get(email="Alice@EXAMPLE.com") == customer  # lookups normalise too


@pytest.mark.django_db
def test_slugs_are_generated_collision_free_and_reusable_after_delete() -> None:
    first = Product.objects.create(name="Desk Lamp", price=1)
    second = Product.objects.create(name="Desk Lamp", price=1)
    explicit = Product.objects.create(name="Desk Lamp", slug="custom", price=1)
    assert (first.slug, second.slug, explicit.slug) == ("desk-lamp", "desk-lamp-2", "custom")
    first.delete()  # soft delete frees "desk-lamp" for a live row
    third = Product.objects.create(name="Desk Lamp", price=1)
    assert third.slug == "desk-lamp"


def test_invalid_declarations_raise_at_class_definition() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        PercentField(min_value=10, max_value=5)
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        PercentField(max_value=1000, max_digits=4)
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        CountryField(codes=["DE", "ZZ"])
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        SearchField(sources=[])
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        SearchField(sources=["title"], config="english; drop table x")


def test_iso_revision_selects_the_list() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E963"):
        CountryField(iso_revision="1999-01")
    field = CurrencyField()
    assert field.deconstruct()[3]["iso_revision"] == field.iso_revision
    assert {"EUR", "USD", "INR", "JPY"} <= set(field.allowed_codes)
    assert "HRK" not in field.allowed_codes  # withdrawn when Croatia adopted the euro
    assert len(CountryField().allowed_codes) == 249


# the layers above: API, search, factories, natural keys


@pytest.mark.django_db
def test_the_api_refuses_a_case_variant_duplicate_with_a_400() -> None:
    Customer.objects.create(email="frank@x.com")
    serializer_class = build_serializer(Customer)
    serializer = serializer_class(data={"email": "Frank@X.com", "name": "F"})
    with pytest.raises(ValidationError) as caught:
        serializer.is_valid(raise_exception=True)
    assert "email" in caught.value.detail
    assert "search" not in build_serializer(Product)().fields  # a generated column is not data


@pytest.mark.django_db
def test_the_api_lets_a_deleted_rows_email_be_reused() -> None:
    Customer.objects.create(email="gina@x.com").delete()
    serializer = build_serializer(Customer)(data={"email": "gina@x.com"})
    assert serializer.is_valid(), serializer.errors
    serializer.save()


@pytest.mark.django_db
def test_the_api_checks_live_uniqueness_across_two_fields() -> None:
    customer = Customer.objects.create(email="hal@x.com")
    product = Product.objects.create(name="Pen", price=1)
    Membership.objects.create(customer=customer, product=product)
    serializer = build_serializer(Membership)(
        data={"customer": str(customer.pk), "product": str(product.pk)}
    )
    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


@pytest.mark.django_db
def test_portable_search_expands_a_search_field_to_its_sources() -> None:
    Product.objects.create(name="Walnut desk", description="solid wood", price=1)
    Product.objects.create(name="Chair", description="steel", price=1)
    found = SimpleSearchProvider().search(
        queryset=Product.objects.all(), query="wood", fields=["search"]
    )
    assert [p.name for p in found] == ["Walnut desk"]


@pytest.mark.django_db
def test_factories_and_seeds_produce_rows_the_database_accepts() -> None:
    """Every generated value passes the CHECKs: ISO codes, E.164, bounds, unique emails."""
    for _ in range(5):
        product = create(Product)
        assert product.made_in == "" or len(product.made_in) == 2
        assert Decimal(0) <= product.discount <= Decimal(100)
        create(Customer)
        create(Account)
    assert Product.objects.count() == 5


def test_natural_key_finds_a_karni_unique_field() -> None:
    assert natural_key(Customer) == "email"
    assert natural_key(Product) == "slug"


@isolate_apps("tests.fieldsapp")
def test_every_field_accepts_its_django_arguments() -> None:
    class Everything(models.Model):
        price = MoneyField(currency="EUR", null=True, blank=True, help_text="h", db_column="p")
        rate = PercentField(default=Decimal("5"), verbose_name="rate")
        stock = QuantityField(db_default=0)
        email = EmailField(max_length=100, db_comment="contact")
        phone = PhoneField(null=True, editable=False)
        country = CountryField(default="IN", choices=[("IN", "India")])

        class Meta:
            app_label = "fieldsapp"

    meta = Everything._meta
    assert meta.get_field("price").column == "p" and meta.get_field("price").null
    assert meta.get_field("country").choices == [("IN", "India")]
    assert "choices" in meta.get_field("country").deconstruct()[3]  # explicit choices are kept


def test_converting_an_existing_column_adds_its_check_in_the_migration() -> None:
    """A CHECK is a named constraint, so altering a DecimalField into a bounded MoneyField
    gets an AddConstraint (Django re-creates column-level CHECKs only for its own types)."""
    before = ProjectState.from_apps(global_apps)
    product = before.models["fieldsapp", "product"]
    product.fields["price"] = models.DecimalField(max_digits=19, decimal_places=4)
    product.options["constraints"] = [
        c for c in product.options["constraints"] if "price" not in c.name
    ]
    operations = _fieldsapp_operations(before)
    kinds = sorted(type(op).__name__ for op in operations)
    assert kinds == ["AddConstraint", "AlterField"]
    added = next(op for op in operations if type(op).__name__ == "AddConstraint")
    assert added.constraint.name.startswith("fieldsapp_product_price_")
    assert added.constraint.name.endswith("_check")
