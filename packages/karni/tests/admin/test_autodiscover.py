"""Startup autodiscovery: who gets registered, who is skipped, and the
autocomplete second pass (contract amendments C1/C2/C5)."""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core import checks
from django.test import override_settings

from karni.admin import autodiscover
from tests.adminapp.admin import ExplicitAdmin
from tests.adminapp.models import (
    Bot,
    Citation,
    Explicit,
    Hidden,
    KitchenSink,
    Note,
    Operator,
    Reading,
    Tuned,
)


def test_unregistered_models_get_generated_unfold_admins(site: admin.AdminSite) -> None:
    from unfold.admin import ModelAdmin as UnfoldModelAdmin

    from karni.admin import KarniModelAdmin

    model_admin = site._registry[KitchenSink]
    assert type(model_admin)._karni_generated
    assert isinstance(model_admin, KarniModelAdmin)
    assert isinstance(model_admin, UnfoldModelAdmin)


def test_explicit_registration_always_wins(site: admin.AdminSite) -> None:
    assert type(site._registry[Explicit]) is ExplicitAdmin


def test_admin_meta_exclude_skips_the_model(site: admin.AdminSite) -> None:
    assert not site.is_registered(Hidden)


def test_settings_exclude_skips_apps_and_single_models(site: admin.AdminSite) -> None:
    # Defaults: app labels ("sessions", "contenttypes", "admin") and the
    # app_label.ModelName form ("auth.Permission").
    assert not site.is_registered(Session)
    assert not site.is_registered(ContentType)
    assert not site.is_registered(Permission)
    # auth.Group is registered — but by django.contrib.auth, not Karni.
    assert site.is_registered(Group)
    assert not getattr(type(site._registry[Group]), "_karni_generated", False)


def test_settings_exclude_is_honored_on_a_fresh_site() -> None:
    with override_settings(KARNI_ADMIN_EXCLUDE=["sessions", "contenttypes", "adminapp.Tuned"]):
        fresh = admin.AdminSite(name="karni-exclude-model")
        autodiscover(site=fresh)
    assert not fresh.is_registered(Tuned)
    assert fresh.is_registered(KitchenSink)
    assert not fresh.is_registered(Session)


def test_settings_exclude_accepts_whole_app_labels() -> None:
    with override_settings(KARNI_ADMIN_EXCLUDE=["sessions", "contenttypes", "adminapp"]):
        fresh = admin.AdminSite(name="karni-exclude-app")
        autodiscover(site=fresh)
    assert not fresh.is_registered(KitchenSink)
    assert not fresh.is_registered(Tuned)
    assert fresh.is_registered(Group)


def test_abstract_base_user_subclasses_are_skipped_unless_opted_in(
    site: admin.AdminSite,
) -> None:
    assert not site.is_registered(Operator)
    assert site.is_registered(Bot)
    assert type(site._registry[Bot])._karni_generated


def test_the_default_user_model_is_registered_by_accounts_not_karni_admin(
    site: admin.AdminSite,
) -> None:
    user_model = get_user_model()
    assert site.is_registered(user_model)
    assert not getattr(type(site._registry[user_model]), "_karni_generated", False)


def test_autodiscover_is_idempotent(site: admin.AdminSite) -> None:
    before = dict(site._registry)
    autodiscover()  # must not raise AlreadyRegistered
    assert set(site._registry) == set(before)
    # Explicit registrations are the exact same instances.
    assert site._registry[Explicit] is before[Explicit]


def test_second_pass_assigns_autocomplete_fields(site: admin.AdminSite) -> None:
    # FK and M2M both qualify when the target admin is searchable.
    assert list(site._registry[KitchenSink].autocomplete_fields) == ["category", "tags"]
    assert list(site._registry[Note].autocomplete_fields) == ["kitchen"]
    assert list(site._registry[Citation].autocomplete_fields) == ["note"]


def test_second_pass_skips_unsearchable_targets(site: admin.AdminSite) -> None:
    assert list(site._registry[Reading].autocomplete_fields) == []


def test_second_pass_never_touches_explicit_admins(site: admin.AdminSite) -> None:
    assert list(site._registry[Explicit].autocomplete_fields) == []


def test_autodiscover_accepts_a_custom_site() -> None:
    custom = admin.AdminSite(name="karni-custom")
    autodiscover(site=custom)
    assert custom.is_registered(KitchenSink)
    assert custom.is_registered(Tuned)
    assert not custom.is_registered(Hidden)
    # The second pass resolves targets on *that* site.
    assert list(custom._registry[KitchenSink].autocomplete_fields) == ["category", "tags"]
    # The default-user special case lives in karni.accounts, which only
    # registers on KARNI_ADMIN_SITE — on a custom site the user model is an
    # ordinary AbstractBaseUser subclass and stays skipped.
    assert not custom.is_registered(get_user_model())


def test_ready_respects_the_autodiscover_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("karni.admin.autodiscover", lambda: calls.append(True))
    config = django_apps.get_app_config("karni_admin")
    with override_settings(KARNI_ADMIN_AUTODISCOVER=False):
        config.ready()
    assert calls == []
    config.ready()
    assert calls == [True]


def test_module_getattr_lazily_exposes_the_admin_classes() -> None:
    import karni.admin as karni_admin
    from karni.admin import base as admin_base
    from karni.admin import soft_delete

    assert karni_admin.KarniModelAdmin is admin_base.KarniModelAdmin
    assert karni_admin.KarniAdminMixin is admin_base.KarniAdminMixin
    assert karni_admin.SoftDeleteAdminMixin is soft_delete.SoftDeleteAdminMixin
    assert karni_admin.SoftDeleteListFilter is soft_delete.SoftDeleteListFilter
    assert "KarniModelAdmin" in dir(karni_admin)
    with pytest.raises(AttributeError):
        karni_admin.NoSuchName  # noqa: B018


@pytest.mark.django_db
def test_generated_admins_pass_django_system_checks() -> None:
    """Every derived option must survive Django's admin checks (E035/E039/…)."""
    messages: list[Any] = checks.run_checks()
    admin_errors = [
        message
        for message in messages
        if message.id.startswith("admin.") and message.level >= checks.ERROR
    ]
    assert admin_errors == []
