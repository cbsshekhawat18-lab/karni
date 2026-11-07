"""National phone numbers: KARNI_PHONE_COUNTRY_CODE, _TRUNK_PREFIX and _NORMALIZER.

Two countries with different trunk prefixes (the United Kingdom's ``0``,
North America's ``1``) and one with none (Italy), through the model field,
its form field, the API's serializer field and the admin.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError

from karni.api.serializers import PhoneNumberField, build_serializer
from karni.conf.validation import validate_settings
from karni.fields import PhoneFormField, normalize_phone, to_e164
from tests.fieldsapp.models import Product


@pytest.mark.parametrize(
    ("raw", "country_code", "trunk_prefix", "stored"),
    [
        ("01234 000 111", "44", "0", "+441234000111"),
        ("(01234) 000-111", "+44", "0", "+441234000111"),
        ("+33 1 23 45 67 89", "44", "0", "+33123456789"),  # another country keeps its +
        ("0033 1 23 45 67 89", "44", "0", "+33123456789"),
        ("1 415 555 2671", "1", "1", "+14155552671"),
        ("(415) 555-2671", "1", "1", "+14155552671"),
        ("06 1234 5678", "39", "", "+390612345678"),  # Italy: the 0 is part of the number
        ("01234 000 111", None, "0", "01234 000 111"),  # no country code: left to reject
        ("ext. 12", "44", "0", "ext. 12"),
    ],
)
def test_to_e164_reads_national_numbers(
    raw: str, country_code: str | None, trunk_prefix: str, stored: str
) -> None:
    assert to_e164(raw, country_code=country_code, trunk_prefix=trunk_prefix) == stored


def test_without_a_country_code_a_national_number_is_refused_naming_the_setting(
    settings: Any,
) -> None:
    settings.KARNI_PHONE_COUNTRY_CODE = None
    field = Product._meta.get_field("phone")
    with pytest.raises(ValidationError) as refused:
        field.clean("01234 000 111", Product())
    assert "KARNI_PHONE_COUNTRY_CODE" in refused.value.messages[0]


def test_the_model_field_stores_a_national_number_in_e164(settings: Any, db: None) -> None:
    settings.KARNI_PHONE_COUNTRY_CODE = "44"
    product = Product.objects.create(name="Lamp", price=Decimal("10"), phone="01234 000 111")
    product.refresh_from_db()
    assert product.phone == "+441234000111"
    assert Product.objects.get(phone="01234 000 111") == product  # lookups normalise too
    settings.KARNI_PHONE_COUNTRY_CODE = "1"
    settings.KARNI_PHONE_TRUNK_PREFIX = "1"
    other = Product.objects.create(name="Desk", price=Decimal("10"), phone="1 (415) 555-2671")
    other.refresh_from_db()
    assert other.phone == "+14155552671"
    with pytest.raises(ValidationError) as refused:
        Product._meta.get_field("phone").clean("ext. 12", other)
    assert "+1 (KARNI_PHONE_COUNTRY_CODE)" in refused.value.messages[0]


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "price", "phone")


def test_the_form_field_cleans_to_e164(settings: Any, db: None) -> None:
    settings.KARNI_PHONE_COUNTRY_CODE = "39"
    settings.KARNI_PHONE_TRUNK_PREFIX = ""
    form = ProductForm(data={"name": "Lamp", "price": "10", "phone": "06 1234 5678"})
    assert isinstance(form.fields["phone"], PhoneFormField)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone"] == "+390612345678"
    product = form.save()
    again = ProductForm(
        data={"name": "Lamp", "price": "10", "phone": "06 1234 5678"}, instance=product
    )
    assert again.is_valid() and "phone" not in again.changed_data
    settings.KARNI_PHONE_COUNTRY_CODE = None
    refused = ProductForm(data={"name": "Lamp", "price": "10", "phone": "06 1234 5678"})
    assert not refused.is_valid()
    assert "KARNI_PHONE_COUNTRY_CODE" in refused.errors["phone"][0]


def test_the_api_cleans_to_e164_before_validating(settings: Any, db: None) -> None:
    settings.KARNI_PHONE_COUNTRY_CODE = "44"
    serializer_class = build_serializer(Product)
    field = serializer_class().fields["phone"]
    assert isinstance(field, PhoneNumberField)
    assert field.run_validation("01234 000 111") == "+441234000111"
    serializer = serializer_class(data={"name": "Lamp", "price": "10", "phone": "020 7946 0958"})
    assert serializer.is_valid(), serializer.errors
    assert serializer.save().phone == "+442079460958"
    settings.KARNI_PHONE_COUNTRY_CODE = None
    refused = serializer_class(data={"name": "Lamp", "price": "10", "phone": "020 7946 0958"})
    assert not refused.is_valid()
    assert "KARNI_PHONE_COUNTRY_CODE" in str(refused.errors["phone"][0])


def test_the_admin_form_cleans_to_e164(settings: Any, db: None) -> None:
    from django.contrib import admin
    from django.test import RequestFactory

    if Product not in admin.site._registry:
        pytest.skip("Product is not registered on the default admin site")
    settings.KARNI_PHONE_COUNTRY_CODE = "44"
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    product = Product.objects.create(name="Lamp", price=Decimal("10"), phone="+441234000111")
    form_class = admin.site._registry[Product].get_form(request, product, change=True)
    phone = form_class.base_fields["phone"]
    assert isinstance(phone, PhoneFormField)
    assert phone.clean("01234 000 111") == "+441234000111"
    assert not phone.has_changed("+441234000111", "01234 000 111")
    assert form_class(instance=product)["phone"].value() == "+441234000111"  # shown as stored


def desk_extension(value: Any) -> Any:
    """A project's own normalizer: its desk extensions, then Karni's rules."""
    if isinstance(value, str) and value.startswith("desk "):
        return "+44123400" + value.removeprefix("desk ")
    return to_e164(value, country_code="44")


def test_the_normalizer_setting_replaces_the_rules(settings: Any) -> None:
    settings.KARNI_PHONE_NORMALIZER = "tests.fields.test_phone_country_code.desk_extension"
    assert normalize_phone("desk 0111") == "+441234000111"
    assert normalize_phone("01234 000 111") == "+441234000111"
    field = Product._meta.get_field("phone")
    assert field.to_python("desk 0111") == "+441234000111"


def test_the_settings_are_checked_at_startup(make_settings: Any) -> None:
    validate_settings(make_settings("dev", DEBUG=True, KARNI_PHONE_COUNTRY_CODE="44"))
    validate_settings(make_settings("dev", DEBUG=True, KARNI_PHONE_COUNTRY_CODE="+1"))
    validate_settings(make_settings("dev", DEBUG=True, KARNI_PHONE_TRUNK_PREFIX=""))
    with pytest.raises(ImproperlyConfigured, match="KARNI_PHONE_COUNTRY_CODE"):
        validate_settings(make_settings("dev", DEBUG=True, KARNI_PHONE_COUNTRY_CODE="UK"))
    with pytest.raises(ImproperlyConfigured, match="KARNI_PHONE_TRUNK_PREFIX"):
        validate_settings(make_settings("dev", DEBUG=True, KARNI_PHONE_TRUNK_PREFIX="O"))
