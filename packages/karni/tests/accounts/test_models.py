"""Tests for the ``karni_accounts`` data layer: manager, user model, APIMeta."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from karni.accounts.models import AbstractKarniUser, User
from karni.models import BaseModel

from .factories import DEFAULT_PASSWORD, UserFactory

# --- manager -----------------------------------------------------------------


@pytest.mark.django_db
def test_create_user_sets_password_and_defaults() -> None:
    user = User.objects.create_user("ada@example.com", "s3cret-pass")
    assert user.email == "ada@example.com"
    assert user.check_password("s3cret-pass")
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.email_verified is False


@pytest.mark.django_db
def test_create_user_normalizes_email_domain() -> None:
    user = User.objects.create_user("Ada@EXAMPLE.COM", "s3cret-pass")
    assert user.email == "Ada@example.com"


@pytest.mark.django_db
def test_create_user_requires_email() -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", "s3cret-pass")


@pytest.mark.django_db
def test_create_user_without_password_is_unusable() -> None:
    user = User.objects.create_user("ada@example.com")
    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_create_superuser_sets_flags() -> None:
    user = User.objects.create_superuser("root@example.com", "s3cret-pass")
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.check_password("s3cret-pass")


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_rejects_demoted_flags(flag: str) -> None:
    with pytest.raises(ValueError, match=flag):
        User.objects.create_superuser("root@example.com", "s3cret-pass", **{flag: False})


# --- model shape --------------------------------------------------------------


def test_email_is_the_username_field() -> None:
    assert User.USERNAME_FIELD == "email"
    assert User.EMAIL_FIELD == "email"
    assert User.REQUIRED_FIELDS == []


def test_there_is_no_username_field() -> None:
    field_names = {field.name for field in User._meta.get_fields()}
    assert "username" not in field_names
    assert User._meta.get_field("email").unique is True


def test_abstract_base_and_swappable_meta() -> None:
    assert AbstractKarniUser._meta.abstract is True
    assert issubclass(User, AbstractKarniUser)
    assert issubclass(User, BaseModel)
    assert User._meta.swappable == "AUTH_USER_MODEL"


def test_default_user_model_is_active() -> None:
    assert settings.AUTH_USER_MODEL == "karni_accounts.User"
    assert get_user_model() is User


@pytest.mark.django_db
def test_email_is_unique() -> None:
    UserFactory(email="ada@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserFactory(email="ada@example.com")


@pytest.mark.django_db
def test_base_model_fields_on_user() -> None:
    user = UserFactory()
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user._meta.pk is not None
    assert user._meta.pk.name == "id"
    assert timezone.now() - user.date_joined < timedelta(minutes=1)


@pytest.mark.django_db
def test_str_and_name_helpers() -> None:
    user = UserFactory(email="ada@example.com", first_name="Ada", last_name="Lovelace")
    assert str(user) == "ada@example.com"
    assert user.get_full_name() == "Ada Lovelace"
    assert user.get_short_name() == "Ada"

    nameless = UserFactory(first_name="", last_name="")
    assert nameless.get_full_name() == nameless.email
    assert nameless.get_short_name() == nameless.email


@pytest.mark.django_db
def test_factory_password_round_trips() -> None:
    user = UserFactory()
    assert user.check_password(DEFAULT_PASSWORD)
    assert UserFactory(verified=True).email_verified is True


# --- APIMeta (accounts amendment A14) -----------------------------------------


def test_apimeta_is_present_and_correct() -> None:
    """The user model pins the API field surface ``karni.api`` builds from."""
    assert User.APIMeta is AbstractKarniUser.APIMeta  # inherited, redeclarable
    assert User.APIMeta.fields == [
        "id",
        "email",
        "first_name",
        "last_name",
        "email_verified",
        "date_joined",
        "created_at",
        "updated_at",
    ]
    assert User.APIMeta.read_only == ["email", "email_verified", "date_joined"]
    assert "password" not in User.APIMeta.fields
    assert "is_staff" not in User.APIMeta.fields
    assert "is_superuser" not in User.APIMeta.fields
